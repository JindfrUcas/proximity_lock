"""
ProximityLock 屏幕控制模块
macOS 锁屏/解锁/唤醒控制
"""
import subprocess
import os
import time


def is_screen_locked():
    """检测屏幕是否已锁定"""
    try:
        result = subprocess.run(
            ["python3", "-c",
             "import Quartz; d=Quartz.CGSessionCopyCurrentDictionary(); "
             "print(d.get('CGSSessionScreenIsLocked', 0) if d else 0)"],
            capture_output=True, text=True, timeout=5
        )
        return result.stdout.strip() == "1"
    except Exception:
        return False


def lock_screen():
    """锁定屏幕"""
    try:
        # 方法1: 使用 pmset 让显示器休眠（会触发锁屏）
        subprocess.run(["pmset", "displaysleepnow"], check=True)
        print("[屏幕] 已锁定")
        return True
    except subprocess.CalledProcessError:
        try:
            # 方法2: 使用 AppleScript 模拟 Ctrl+Cmd+Q
            subprocess.run([
                "osascript", "-e",
                'tell application "System Events" to keystroke "q" '
                'using {control down, command down}'
            ], check=True)
            print("[屏幕] 已锁定 (AppleScript)")
            return True
        except subprocess.CalledProcessError as e:
            print(f"[屏幕] 锁定失败: {e}")
            return False


def wake_display():
    """唤醒显示器"""
    try:
        subprocess.run(["caffeinate", "-u", "-t", "2"], check=True)
        print("[屏幕] 已唤醒")
        return True
    except subprocess.CalledProcessError as e:
        print(f"[屏幕] 唤醒失败: {e}")
        return False


def unlock_screen(password=None):
    """
    尝试解锁屏幕

    注意：自动解锁需要:
    1. 密码（从 Keychain 获取或参数传入）
    2. Accessibility 权限

    如果不想存储密码，可以只做唤醒+通知用户手动输入
    """
    if not is_screen_locked():
        return True

    # 先唤醒显示器
    wake_display()
    time.sleep(0.5)

    if password:
        try:
            # 使用 AppleScript 模拟键盘输入密码
            # 先按 Esc 确保在密码输入框
            subprocess.run([
                "osascript", "-e",
                'tell application "System Events" to key code 53'  # Esc
            ], check=True, timeout=3)
            time.sleep(0.3)

            # 输入密码
            escaped_password = password.replace('"', '\\"').replace("'", "\\'")
            subprocess.run([
                "osascript", "-e",
                f'tell application "System Events" to keystroke "{escaped_password}"'
            ], check=True, timeout=3)
            time.sleep(0.1)

            # 按回车
            subprocess.run([
                "osascript", "-e",
                'tell application "System Events" to keystroke return'
            ], check=True, timeout=3)

            print("[屏幕] 已解锁")
            return True
        except Exception as e:
            print(f"[屏幕] 解锁失败: {e}")
            return False
    else:
        print("[屏幕] 无密码，仅唤醒屏幕")
        return False


# ===== Keychain 密码管理 =====

KEYCHAIN_SERVICE = "ProximityLock"
KEYCHAIN_ACCOUNT = os.environ.get("USER", "user")


def store_password_to_keychain(password):
    """将密码存储到 macOS Keychain"""
    try:
        # 先删除旧的
        subprocess.run([
            "security", "delete-generic-password",
            "-s", KEYCHAIN_SERVICE,
            "-a", KEYCHAIN_ACCOUNT,
        ], capture_output=True)

        # 添加新的
        subprocess.run([
            "security", "add-generic-password",
            "-s", KEYCHAIN_SERVICE,
            "-a", KEYCHAIN_ACCOUNT,
            "-w", password,
            "-U",  # 允许更新
        ], check=True, capture_output=True)
        print("[Keychain] 密码已保存")
        return True
    except subprocess.CalledProcessError as e:
        print(f"[Keychain] 保存失败: {e}")
        return False


def fetch_password_from_keychain():
    """从 macOS Keychain 读取密码"""
    try:
        result = subprocess.run([
            "security", "find-generic-password",
            "-s", KEYCHAIN_SERVICE,
            "-a", KEYCHAIN_ACCOUNT,
            "-w",
        ], capture_output=True, text=True, check=True)
        password = result.stdout.strip()
        return password if password else None
    except subprocess.CalledProcessError:
        return None


def delete_password_from_keychain():
    """从 Keychain 删除密码"""
    try:
        subprocess.run([
            "security", "delete-generic-password",
            "-s", KEYCHAIN_SERVICE,
            "-a", KEYCHAIN_ACCOUNT,
        ], check=True, capture_output=True)
        print("[Keychain] 密码已删除")
        return True
    except subprocess.CalledProcessError:
        return False


# ===== 媒体控制 =====

def pause_media():
    """暂停正在播放的媒体"""
    try:
        subprocess.run([
            "osascript", "-e",
            'tell application "System Events" to key code 49 using {}'
        ], capture_output=True, timeout=3)
    except Exception:
        pass


def send_notification(title, message):
    """发送 macOS 通知"""
    try:
        subprocess.run([
            "osascript", "-e",
            f'display notification "{message}" with title "{title}"'
        ], capture_output=True, timeout=5)
    except Exception:
        pass
