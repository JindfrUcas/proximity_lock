"""
ProximityLock - macOS 菜单栏应用
仅保留 iPhone 离开自动锁屏，不再执行靠近亮屏/自动解锁

工作方式：
1. 先检测本地键盘/鼠标是否空闲
2. 本地连续无操作 5 秒后，开始快速 BLE 检测
3. RSSI 低于锁屏阈值或持续收不到信号时，自动锁屏
4. 用户手动回来操作后，仅静默复位状态，不主动亮屏
"""
import argparse
import asyncio
import signal
import sys
import threading
import time
import getpass

from activity_monitor import ActivityMonitor
from calibration import Calibrator
from config import Config
from remote_auth import (
    RemoteUnlockService,
    build_otpauth_uri,
    generate_totp_secret,
    get_access_urls,
)
from screen_control import (
    fetch_password_from_keychain,
    is_screen_locked,
    lock_screen,
    send_notification,
    store_password_to_keychain,
    unlock_screen,
)
from signal_filter import SignalProcessor
from state_machine import ProximityState, StateMachine

try:
    from scanner import BLEProximityScanner, discover_and_select
    SCANNER_IMPORT_ERROR = None
except ModuleNotFoundError as exc:
    BLEProximityScanner = None
    discover_and_select = None
    SCANNER_IMPORT_ERROR = exc


class ProximityLockApp:
    """主应用：连接所有模块"""

    def __init__(self, config):
        if BLEProximityScanner is None:
            raise RuntimeError(
                f"缺少 BLE 依赖，无法启动监控: {SCANNER_IMPORT_ERROR}"
            )
        self.config = config
        self.signal_processor = SignalProcessor(config)
        self.scanner = BLEProximityScanner(config)
        self.activity_monitor = ActivityMonitor()
        self.state_machine = StateMachine(
            config,
            on_lock=self._on_lock,
            on_signal_lost=self._on_signal_lost,
        )

        self._running = False
        self._current_rssi = None
        self._current_filtered = None
        self._device_name = config.get("device_name", "iPhone")
        self._last_idle_seconds = 0.0
        self._idle_detection_active = False
        self._remote_access_until = 0.0
        self.remote_unlock_service = RemoteUnlockService(
            config,
            can_unlock=self._can_remote_unlock,
            on_unlock=self._perform_remote_unlock,
        )

    def _on_lock(self, reason):
        """锁屏回调"""
        print(f"\n[锁屏] 原因: {reason}")
        if self.config["auto_lock_enabled"]:
            lock_screen()
        if self.config["notification_enabled"]:
            send_notification("ProximityLock", f"已锁屏 - {reason}")

    def _on_signal_lost(self):
        """信号丢失回调"""
        print("\n[BLE] 空闲检测期间信号丢失")
        if self.config["notification_enabled"]:
            send_notification("ProximityLock", "空闲检测期间 BLE 信号丢失")

    def _remote_access_active(self):
        """是否处于远程授权放行窗口"""
        return time.time() < self._remote_access_until

    def _remote_access_remaining(self):
        """远程授权剩余秒数"""
        return max(self._remote_access_until - time.time(), 0.0)

    def _can_remote_unlock(self):
        """当前是否允许通过授权码执行远程解锁"""
        return bool(
            self.config.get("remote_unlock_enabled")
            and is_screen_locked()
            and fetch_password_from_keychain()
        )

    def _perform_remote_unlock(self, client_ip):
        """执行一次远程授权解锁"""
        password = fetch_password_from_keychain()
        if not password:
            return False, "未配置 Mac 登录密码，无法远程授权解锁"

        success = unlock_screen(password)
        if not success:
            return False, "授权码正确，但系统解锁失败，请检查辅助功能权限"

        self._remote_access_until = (
            time.time() + self.config["remote_unlock_session_minutes"] * 60
        )
        self._idle_detection_active = False
        self._current_rssi = None
        self._current_filtered = None
        self.signal_processor.reset()
        self.state_machine.mark_present("远程授权解锁")

        minutes = self.config["remote_unlock_session_minutes"]
        message = f"远程授权成功，已开放 {minutes} 分钟"
        print(f"[远程授权] 来自 {client_ip}，{message}")
        if self.config["notification_enabled"]:
            send_notification("ProximityLock", message)
        return True, message

    def _consume_rssi(self, rssi, name):
        """统一处理 RSSI 数据"""
        self._current_rssi = rssi
        self._device_name = name

        filtered, is_valid = self.signal_processor.process(rssi)
        self._current_filtered = filtered

        if is_valid and filtered is not None:
            self.state_machine.update(filtered)

    def _reset_presence_from_local_activity(self):
        """本地有输入时，停止 BLE 检测并静默复位为“人在电脑旁”"""
        was_reset = (
            self._idle_detection_active
            or self._current_rssi is not None
            or self._current_filtered is not None
            or self.state_machine.state != ProximityState.PRESENT
        )

        self._idle_detection_active = False
        self._current_rssi = None
        self._current_filtered = None
        self.signal_processor.reset()
        self.state_machine.mark_present("检测到本地操作")

        if was_reset:
            print("[活动] 检测到本地操作，停止 BLE 检测并重新布防")

    async def _run_idle_detection_cycle(self):
        """空闲状态下执行一次快速 BLE 检测"""
        sample = await self.scanner.sample_rssi(self.config["idle_scan_window"])
        if sample is None:
            self._current_rssi = None
            self._current_filtered = self.signal_processor.current_value
            self.state_machine.update(None)
            return

        rssi, name = sample
        self._consume_rssi(rssi, name)

    async def run_monitor(self):
        """运行监控主循环"""
        self._running = True

        print(f"\n{'=' * 54}")
        print("  ProximityLock 已启动")
        print(f"  监控设备: {self._device_name}")
        print(f"  锁屏阈值: {self.config['lock_rssi']}dBm")
        print(f"  空闲触发: {self.config['idle_grace_seconds']}秒")
        print(f"  采样窗口: {self.config['idle_scan_window']:.2f}秒")
        print(f"  锁屏确认: {self.config['lock_confirm_seconds']:.2f}秒")
        print(f"  滤波器: {self.config['filter_type']}")
        print("  返回时不会自动亮屏或解锁")
        if self.remote_unlock_service.enabled:
            print("  已启用远程授权解锁")
            for url in get_access_urls(self.config["remote_unlock_port"]):
                print(f"  授权地址: {url}")
        print(f"{'=' * 54}\n")

        display_thread = threading.Thread(target=self._display_loop, daemon=True)
        display_thread.start()

        if self.remote_unlock_service.enabled:
            self.remote_unlock_service.start()
            if self.remote_unlock_service.server_error:
                print(f"⚠️ {self.remote_unlock_service.server_error}")
            else:
                print(f"[远程授权] {self.remote_unlock_service.last_message}")

        if not self.activity_monitor.available:
            print("⚠️ 无法读取本地空闲时间，退回旧的持续 BLE 检测模式")
            await self.scanner.start_monitoring(
                on_rssi_update=lambda rssi, name: self._consume_rssi(rssi, name),
                on_signal_lost=lambda: self.state_machine.update(None),
            )
            return

        while self._running:
            idle_seconds = self.activity_monitor.get_idle_seconds()
            self._last_idle_seconds = idle_seconds

            if self._remote_access_active():
                if self._idle_detection_active or self.state_machine.state != ProximityState.PRESENT:
                    self._idle_detection_active = False
                    self._current_rssi = None
                    self._current_filtered = None
                    self.signal_processor.reset()
                    self.state_machine.mark_present("远程授权会话保持中")
                await asyncio.sleep(self.config["activity_poll_interval"])
                continue

            if idle_seconds < self.config["idle_grace_seconds"]:
                self._reset_presence_from_local_activity()
                await asyncio.sleep(self.config["activity_poll_interval"])
                continue

            if not self._idle_detection_active:
                self._idle_detection_active = True
                self.signal_processor.reset()
                self._current_rssi = None
                self._current_filtered = None
                print(
                    f"[活动] 本地已空闲 {idle_seconds:.1f} 秒，开始快速 BLE 离开检测"
                )

            if self.state_machine.state in (ProximityState.AWAY, ProximityState.SIGNAL_LOST):
                await asyncio.sleep(self.config["activity_poll_interval"])
                continue

            try:
                await self._run_idle_detection_cycle()
            except Exception as exc:
                print(f"[BLE] 空闲检测失败: {exc}")

            await asyncio.sleep(self.config["idle_scan_pause"])

    def _display_loop(self):
        """定期显示状态"""
        while self._running:
            time.sleep(3)
            stats = self.signal_processor.stats
            if self._remote_access_active():
                mode = f"远程授权中({self._remote_access_remaining()/60:.1f}m)"
            else:
                mode = "空闲检测中" if self._idle_detection_active else "等待空闲"
            raw = "-" if self._current_rssi is None else f"{self._current_rssi}dBm"
            filtered = (
                "-"
                if self._current_filtered is None
                else f"{self._current_filtered:.1f}dBm"
            )
            outlier = (
                f" | 丢弃率:{stats['outlier_rate']:.0%}"
                if stats["outlier_rate"] > 0
                else ""
            )
            print(
                f"  ⌛ 空闲:{self._last_idle_seconds:>4.1f}s | "
                f"{mode} | 原始:{raw:>8} | 滤波:{filtered:>10} | "
                f"{self.state_machine.status_text}{outlier}"
            )

    def stop(self):
        """停止应用"""
        self._running = False
        self.scanner.stop_monitoring()
        self.remote_unlock_service.stop()
        print("\nProximityLock 已停止")


def run_menu_bar_app(config):
    """启动菜单栏应用（需要 rumps）"""
    try:
        import rumps
    except ImportError:
        print("❌ 需要安装 rumps: pip install rumps")
        print("   或者使用命令行模式: python main.py --cli")
        sys.exit(1)

    app_instance = ProximityLockApp(config)
    loop = asyncio.new_event_loop()

    class ProximityLockMenuBar(rumps.App):
        def __init__(self):
            super().__init__(
                "ProximityLock",
                icon=None,
                title="🔒",
                quit_button=None,
            )
            self.status_item = rumps.MenuItem("状态: 初始化中...", callback=None)
            self.remote_item = rumps.MenuItem("远程授权: 未启用", callback=self.remote_info)
            self.menu = [
                self.status_item,
                None,
                rumps.MenuItem(f"设备: {config.get('device_name', '未设置')}"),
                rumps.MenuItem(f"空闲触发: {config['idle_grace_seconds']}秒"),
                rumps.MenuItem(f"锁屏阈值: {config['lock_rssi']}dBm"),
                self.remote_item,
                None,
                rumps.MenuItem("手动锁屏", callback=self.manual_lock),
                rumps.MenuItem("重新扫描设备", callback=self.rescan),
                rumps.MenuItem("运行校准", callback=self.calibrate),
                None,
                rumps.MenuItem("退出", callback=self.quit_app),
            ]
            self._monitor_thread = threading.Thread(
                target=self._run_monitor_async,
                daemon=True,
            )
            self._monitor_thread.start()

            self._timer = rumps.Timer(self.update_status, 3)
            self._timer.start()

        def _run_monitor_async(self):
            asyncio.set_event_loop(loop)
            loop.run_until_complete(app_instance.run_monitor())

        @rumps.timer(3)
        def update_status(self, _):
            state = app_instance.state_machine.state
            idle_seconds = app_instance._last_idle_seconds
            filtered = app_instance._current_filtered
            if app_instance.remote_unlock_service.enabled:
                self.remote_item.title = "远程授权: 已启用"
            else:
                self.remote_item.title = "远程授权: 未启用"

            if app_instance._remote_access_active():
                self.title = "🟢"
                minutes = app_instance._remote_access_remaining() / 60
                self.status_item.title = f"状态: 远程授权中 | 剩余 {minutes:.1f} 分钟"
                return

            if state in (ProximityState.AWAY, ProximityState.SIGNAL_LOST):
                self.title = "🔒"
                self.status_item.title = "状态: 已锁屏，可远程授权"
                return

            self.title = "📡" if app_instance._idle_detection_active else "⌨️"

            if filtered is not None:
                self.status_item.title = (
                    f"状态: {app_instance.state_machine.status_text} | {filtered:.0f}dBm"
                )
            else:
                remaining = max(config["idle_grace_seconds"] - idle_seconds, 0.0)
                self.status_item.title = (
                    f"状态: 等待空闲 | {remaining:.1f}秒后开始检测"
                )

        def manual_lock(self, _):
            lock_screen()
            rumps.notification("ProximityLock", "", "已手动锁屏")

        def rescan(self, _):
            rumps.notification("ProximityLock", "", "请在终端运行: python main.py --discover")

        def calibrate(self, _):
            rumps.notification("ProximityLock", "", "请在终端运行: python main.py --calibrate")

        def remote_info(self, _):
            from gui_setup import show_alert

            if not app_instance.remote_unlock_service.enabled:
                show_alert(
                    "远程授权未启用",
                    "请先在终端运行:\npython main.py --setup-remote-unlock"
                )
                return

            urls = get_access_urls(config["remote_unlock_port"])
            message = "朋友在同一局域网内打开以下任一地址：\n\n"
            message += "\n".join(urls[:3]) if urls else f"端口 {config['remote_unlock_port']}"
            message += "\n\n输入你发给他的 6 位动态码即可。"
            show_alert("远程授权地址", message)

        def quit_app(self, _):
            app_instance.stop()
            rumps.quit_application()

    menu_app = ProximityLockMenuBar()
    menu_app.run()


async def run_cli_mode(config):
    """命令行模式（调试用）"""
    app = ProximityLockApp(config)

    def signal_handler(sig, frame):
        app.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)

    await app.run_monitor()


async def cmd_discover(config):
    """设备发现命令"""
    if discover_and_select is None:
        print(f"❌ 缺少 BLE 依赖，无法扫描设备: {SCANNER_IMPORT_ERROR}")
        return
    result = await discover_and_select()
    if result:
        uuid, name = result
        config["device_uuid"] = uuid
        config["device_name"] = name
        config.save()
        print(f"\n✅ 已保存设备: {name} ({uuid})")
        print("  下一步: python main.py --calibrate")
    else:
        print("未选择设备")


async def cmd_calibrate(config):
    """校准命令"""
    if BLEProximityScanner is None:
        print(f"❌ 缺少 BLE 依赖，无法校准: {SCANNER_IMPORT_ERROR}")
        return
    if not config.get("device_uuid"):
        print("❌ 请先选择设备: python main.py --discover")
        return

    scanner = BLEProximityScanner(config)
    calibrator = Calibrator(scanner, config)
    result = await calibrator.run_calibration()

    if result:
        config.set_thresholds(result["unlock_rssi"], result["lock_rssi"])
        config.save()
        print("\n✅ 阈值已保存！")
        print("  下一步: python main.py")


def cmd_set_password():
    """设置远程授权解锁所需的 Mac 登录密码"""
    print("\n🔐 设置 Mac 登录密码（仅用于远程授权解锁）")
    print("密码会安全保存在 macOS Keychain 中。")
    password = getpass.getpass("请输入 Mac 登录密码: ")
    if not password:
        print("❌ 密码不能为空")
        return
    confirm = getpass.getpass("请再次输入确认: ")
    if password != confirm:
        print("❌ 两次输入不一致")
        return
    if store_password_to_keychain(password):
        print("✅ 密码已保存到 Keychain")
    else:
        print("❌ 保存密码失败")


def _print_remote_unlock_info(config):
    """打印远程授权初始化信息"""
    secret = config.get("remote_unlock_secret")
    if not secret:
        print("❌ 尚未生成远程授权密钥")
        return

    hostname = config.get("device_name") or "Mac"
    uri = build_otpauth_uri(secret, hostname)

    print("\n📲 远程授权已启用")
    print(f"  动态码密钥: {secret}")
    print(f"  otpauth URI: {uri}")
    print("  可将上面的密钥或 otpauth URI 导入到认证器应用")
    print("  例如 Apple Passwords、Google Authenticator、1Password 等")
    print("\n🌐 朋友可在同一局域网内打开以下地址：")
    urls = get_access_urls(config["remote_unlock_port"])
    if urls:
        for url in urls:
            print(f"  - {url}")
    else:
        print(f"  - 端口 {config['remote_unlock_port']}（未能自动解析地址）")
    print(
        f"\n✅ 授权成功后会临时放行 {config['remote_unlock_session_minutes']} 分钟，"
        "期间不会因为手机不在而再次自动锁屏。"
    )


def cmd_setup_remote_unlock(config):
    """初始化远程授权解锁"""
    if not fetch_password_from_keychain():
        print("\n当前还没有保存 Mac 登录密码，需要先设置一次。")
        cmd_set_password()
        if not fetch_password_from_keychain():
            print("❌ 没有可用密码，无法继续配置远程授权")
            return

    if not config.get("remote_unlock_secret"):
        config["remote_unlock_secret"] = generate_totp_secret()

    config["remote_unlock_enabled"] = True
    config["use_keychain"] = True
    config.save()
    _print_remote_unlock_info(config)


def cmd_show_remote_unlock(config):
    """显示远程授权信息"""
    if not config.get("remote_unlock_enabled") or not config.get("remote_unlock_secret"):
        print("❌ 远程授权尚未启用，请先运行: python main.py --setup-remote-unlock")
        return
    _print_remote_unlock_info(config)


def main():
    parser = argparse.ArgumentParser(
        description="ProximityLock - iPhone 离开自动锁屏",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用流程:
  1. python main.py --discover     发现并选择你的 iPhone
  2. python main.py --calibrate    校准锁屏阈值
  3. python main.py --setup-remote-unlock   配置远程授权解锁（可选）
  4. python main.py                启动菜单栏应用
  5. python main.py --cli          命令行模式（调试用）
        """,
    )
    parser.add_argument("--discover", action="store_true", help="扫描发现 BLE 设备")
    parser.add_argument("--calibrate", action="store_true", help="运行校准向导")
    parser.add_argument("--set-password", action="store_true", help="设置远程授权解锁所需的 Mac 登录密码")
    parser.add_argument("--setup-remote-unlock", action="store_true", help="生成动态码密钥并启用远程授权解锁")
    parser.add_argument("--show-remote-unlock", action="store_true", help="显示远程授权地址与认证器密钥")
    parser.add_argument("--cli", action="store_true", help="命令行模式运行")
    parser.add_argument(
        "--filter",
        choices=["mean", "median", "ema", "kalman"],
        help="指定滤波器类型",
    )

    args = parser.parse_args()
    config = Config()

    if args.filter:
        config["filter_type"] = args.filter
        config.save()

    if args.discover:
        asyncio.run(cmd_discover(config))
    elif args.calibrate:
        asyncio.run(cmd_calibrate(config))
    elif args.setup_remote_unlock:
        cmd_setup_remote_unlock(config)
    elif args.show_remote_unlock:
        cmd_show_remote_unlock(config)
    elif args.set_password:
        cmd_set_password()
    elif args.cli:
        asyncio.run(run_cli_mode(config))
    else:
        if not config.get("device_uuid"):
            print("⚠️ 尚未设置目标设备！")
            print("\n请先运行以下命令完成初始设置：")
            print("  python main.py --discover")
            print("  python main.py --calibrate")
            return

        run_menu_bar_app(config)


if __name__ == "__main__":
    main()
