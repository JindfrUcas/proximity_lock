"""
远程授权解锁

提供一个局域网内可访问的轻量页面，朋友可以在自己的手机上输入一次性授权码。
验证通过后，程序会调用已保存在 Keychain 中的 Mac 密码执行解锁。
"""
import base64
import hashlib
import hmac
import html
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import secrets
import socket
import threading
import time
from urllib.parse import parse_qs, quote


def generate_totp_secret(num_bytes=20):
    """生成 Base32 编码的 TOTP 密钥"""
    return base64.b32encode(secrets.token_bytes(num_bytes)).decode("ascii").rstrip("=")


def build_otpauth_uri(secret, account_name, issuer="ProximityLock"):
    """生成可导入认证器应用的 otpauth URI"""
    label = quote(f"{issuer}:{account_name}")
    issuer_value = quote(issuer)
    return (
        f"otpauth://totp/{label}"
        f"?secret={secret}&issuer={issuer_value}&algorithm=SHA1&digits=6&period=30"
    )


def current_totp(secret, for_time=None, digits=6, period=30):
    """生成当前时间步的一次性验证码"""
    if for_time is None:
        for_time = time.time()
    counter = int(for_time // period)
    padded_secret = secret.upper() + ("=" * (-len(secret) % 8))
    key = base64.b32decode(padded_secret, casefold=True)
    msg = counter.to_bytes(8, "big")
    digest = hmac.new(key, msg, hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code_int = int.from_bytes(digest[offset:offset + 4], "big") & 0x7FFFFFFF
    return f"{code_int % (10 ** digits):0{digits}d}"


def verify_totp(code, secret, digits=6, period=30, window=1):
    """校验一次性验证码，允许前后一个时间窗口误差"""
    digits_only = "".join(ch for ch in str(code) if ch.isdigit())
    if len(digits_only) != digits:
        return False
    now = time.time()
    for offset in range(-window, window + 1):
        expected = current_totp(
            secret,
            for_time=now + offset * period,
            digits=digits,
            period=period,
        )
        if hmac.compare_digest(digits_only, expected):
            return True
    return False


def get_access_urls(port):
    """
    返回适合发给朋友访问的 URL 列表
    """
    urls = []
    hostname = socket.gethostname()
    if hostname:
        urls.append(f"http://{hostname}.local:{port}")

    try:
        addresses = socket.getaddrinfo(hostname, None, family=socket.AF_INET)
        ips = []
        for item in addresses:
            ip = item[4][0]
            if ip.startswith("127."):
                continue
            if ip not in ips:
                ips.append(ip)
        for ip in ips:
            urls.append(f"http://{ip}:{port}")
    except socket.gaierror:
        pass

    unique_urls = []
    for url in urls:
        if url not in unique_urls:
            unique_urls.append(url)
    return unique_urls


class RemoteUnlockService:
    """远程授权 HTTP 服务"""

    def __init__(self, config, can_unlock, on_unlock):
        self.config = config
        self.can_unlock = can_unlock
        self.on_unlock = on_unlock

        self._server = None
        self._thread = None
        self._lock = threading.Lock()
        self._failed_attempts = 0
        self._lockout_until = 0.0
        self._last_message = ""
        self._server_error = None

    @property
    def enabled(self):
        return bool(
            self.config.get("remote_unlock_enabled")
            and self.config.get("remote_unlock_secret")
        )

    @property
    def is_running(self):
        return self._thread is not None and self._thread.is_alive()

    @property
    def server_error(self):
        return self._server_error

    @property
    def last_message(self):
        return self._last_message

    def start(self):
        """启动远程授权服务"""
        if not self.enabled or self.is_running:
            return

        host = self.config["remote_unlock_host"]
        port = int(self.config["remote_unlock_port"])

        handler_cls = self._build_handler()
        try:
            self._server = ThreadingHTTPServer((host, port), handler_cls)
            self._server.daemon_threads = True
        except OSError as exc:
            self._server_error = str(exc)
            self._last_message = f"远程授权服务启动失败: {exc}"
            return

        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="RemoteUnlockService",
            daemon=True,
        )
        self._thread.start()
        self._server_error = None
        self._last_message = f"远程授权服务已启动，监听 {host}:{port}"

    def stop(self):
        """停止远程授权服务"""
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=2)

        self._server = None
        self._thread = None

    def handle_code(self, code, client_ip):
        """处理一次授权码提交"""
        with self._lock:
            now = time.time()
            if not self.enabled:
                self._last_message = "远程授权未启用"
                return False, "远程授权未启用"

            if self._lockout_until > now:
                wait_seconds = int(self._lockout_until - now)
                message = f"失败次数过多，请 {wait_seconds} 秒后再试"
                self._last_message = message
                return False, message

            if not self.can_unlock():
                message = "当前电脑不在可远程解锁状态"
                self._last_message = message
                return False, message

            secret = self.config.get("remote_unlock_secret")
            if not verify_totp(code, secret):
                self._failed_attempts += 1
                remaining = self.config["remote_unlock_max_attempts"] - self._failed_attempts
                if remaining <= 0:
                    self._failed_attempts = 0
                    self._lockout_until = now + self.config["remote_unlock_lockout_seconds"]
                    message = (
                        "授权码错误次数过多，已临时锁定远程授权入口"
                    )
                    self._last_message = message
                    return False, message
                message = f"授权码无效，还可再试 {remaining} 次"
                self._last_message = message
                return False, message

            self._failed_attempts = 0
            success, message = self.on_unlock(client_ip)
            self._last_message = message
            return success, message

    def _build_handler(self):
        service = self

        class UnlockHandler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                if self.path.startswith("/status"):
                    self._send_status()
                    return
                self._send_page()

            def do_POST(self):  # noqa: N802
                if self.path != "/unlock":
                    self.send_error(404)
                    return
                content_length = int(self.headers.get("Content-Length", "0"))
                payload = self.rfile.read(content_length).decode("utf-8", errors="ignore")
                form = parse_qs(payload)
                code = form.get("code", [""])[0]
                success, message = service.handle_code(code, self.client_address[0])
                self._send_page(
                    message=message,
                    success=success,
                )

            def _send_status(self):
                if service.enabled and service.can_unlock():
                    status = "locked"
                elif service.enabled:
                    status = "idle"
                else:
                    status = "disabled"

                body = (
                    "{"
                    f"\"enabled\": {str(service.enabled).lower()}, "
                    f"\"status\": \"{status}\", "
                    f"\"message\": \"{html.escape(service.last_message)}\""
                    "}"
                )
                encoded = body.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)

            def _send_page(self, message="", success=False):
                title = "远程授权解锁"
                can_unlock = service.can_unlock()
                state_text = "电脑已锁定，可提交授权码" if can_unlock else "当前电脑未处于可解锁状态"
                message_html = ""
                if message:
                    color = "#1f7a1f" if success else "#b42318"
                    message_html = (
                        f'<p style="color:{color};font-weight:600;">'
                        f"{html.escape(message)}</p>"
                    )

                body = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <style>
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: linear-gradient(135deg, #f6f8fb, #e7eef8);
      color: #152033;
      margin: 0;
      padding: 24px;
    }}
    .card {{
      max-width: 420px;
      margin: 40px auto;
      background: rgba(255,255,255,0.95);
      border-radius: 18px;
      padding: 24px;
      box-shadow: 0 18px 40px rgba(21,32,51,0.12);
    }}
    h1 {{ margin-top: 0; font-size: 1.4rem; }}
    input {{
      width: 100%;
      font-size: 1.4rem;
      letter-spacing: 0.2rem;
      padding: 12px 14px;
      border-radius: 12px;
      border: 1px solid #c6d0df;
      box-sizing: border-box;
    }}
    button {{
      margin-top: 12px;
      width: 100%;
      border: none;
      border-radius: 12px;
      padding: 12px 14px;
      background: #1f6feb;
      color: white;
      font-size: 1rem;
      font-weight: 600;
    }}
    p {{ line-height: 1.5; }}
    .muted {{ color: #526176; font-size: 0.95rem; }}
  </style>
</head>
<body>
  <div class="card">
    <h1>{title}</h1>
    <p>{html.escape(state_text)}</p>
    {message_html}
    <form method="post" action="/unlock">
      <input
        type="text"
        inputmode="numeric"
        name="code"
        maxlength="6"
        pattern="[0-9]{{6}}"
        placeholder="输入 6 位授权码"
        autocomplete="one-time-code"
      />
      <button type="submit">提交授权码</button>
    </form>
    <p class="muted">
      授权码来自预先绑定的认证器应用。验证成功后，电脑会临时开放一段授权时长。
    </p>
  </div>
</body>
</html>
"""
                encoded = body.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)

            def log_message(self, fmt, *args):  # noqa: A003
                return

        return UnlockHandler
