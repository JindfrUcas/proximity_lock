"""
ProximityLock GUI 设置界面
使用 macOS 原生对话框，让用户不需要命令行也能完成所有设置
"""
import subprocess
import asyncio
import threading


def show_alert(title, message, buttons=None):
    """显示 macOS 原生对话框"""
    if buttons:
        btn_str = ", ".join(f'"{b}"' for b in buttons)
        script = f'''
        set theButtons to {{{btn_str}}}
        display dialog "{message}" with title "{title}" buttons theButtons default button 1
        return button returned of result
        '''
    else:
        script = f'display dialog "{message}" with title "{title}" buttons {{"确定"}} default button 1'
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=120
        )
        return result.stdout.strip().replace("button returned:", "")
    except Exception:
        return None


def show_input_dialog(title, message, hidden=False):
    """显示输入对话框"""
    hidden_str = "with hidden answer" if hidden else ""
    script = f'''
    display dialog "{message}" with title "{title}" default answer "" {hidden_str} buttons {{"取消", "确定"}} default button "确定"
    return text returned of result
    '''
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=120
        )
        return result.stdout.strip()
    except Exception:
        return None


def show_device_list(devices):
    """显示设备选择列表"""
    if not devices:
        show_alert("ProximityLock", "未发现任何 BLE 设备，请确保 iPhone 蓝牙已开启。")
        return None

    # 构建设备列表
    items = []
    for d in devices[:15]:  # 最多显示 15 个
        name = d["name"] or "未知设备"
        items.append(f'{name} ({d["rssi"]}dBm)')

    items_str = ", ".join(f'"{item}"' for item in items)
    script = f'''
    choose from list {{{items_str}}} with title "ProximityLock" with prompt "请选择你的 iPhone:" OK button name "选择" cancel button name "取消"
    '''
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=120
        )
        chosen = result.stdout.strip()
        if chosen and chosen != "false":
            # 找到对应设备
            for i, item in enumerate(items):
                if item == chosen:
                    return devices[i]
    except Exception:
        pass
    return None


def show_progress(message):
    """显示通知"""
    try:
        subprocess.run([
            "osascript", "-e",
            f'display notification "{message}" with title "ProximityLock"'
        ], capture_output=True, timeout=5)
    except Exception:
        pass


class SetupWizard:
    """一站式 GUI 设置向导"""

    def __init__(self, config):
        self.config = config

    def run(self):
        """运行设置向导"""
        btn = show_alert(
            "ProximityLock 设置向导",
            "欢迎使用 ProximityLock！\\n\\n"
            "本应用通过蓝牙感应 iPhone 的距离，\\n"
            "在你离开时自动锁屏。\\n"
            "系统会在本地无操作几秒后才开始检测，\\n"
            "不会持续进行靠近亮屏。\\n\\n"
            "首先需要进行初始设置。",
            ["开始设置", "跳过"]
        )
        if btn and "跳过" in btn:
            return False

        # 第 1 步：扫描设备
        show_progress("正在扫描蓝牙设备...")
        device = self._scan_and_select()
        if not device:
            return False

        # 第 2 步：提示完成
        show_alert(
            "设置完成 ✅",
            f"已绑定设备: {device.get('name', '未知')}\\n"
            f"空闲触发: {self.config.get('idle_grace_seconds', 5.0)}秒\\n"
            f"锁屏阈值: {self.config['lock_rssi']}dBm\\n\\n"
            "ProximityLock 将在菜单栏运行。"
        )
        return True

    def _scan_and_select(self):
        """扫描并选择设备"""
        from scanner import BLEProximityScanner

        scanner = BLEProximityScanner(self.config.to_dict() if hasattr(self.config, 'to_dict') else self.config)

        # 在新线程中运行异步扫描
        devices = []

        def scan_task():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            nonlocal devices
            devices = loop.run_until_complete(scanner.discover_devices(duration=8.0))
            loop.close()

        t = threading.Thread(target=scan_task)
        t.start()
        t.join(timeout=15)

        if not devices:
            show_alert("ProximityLock", "未找到蓝牙设备。\\n请确保 iPhone 蓝牙已开启且在附近。")
            return None

        # 优先显示 Apple 设备
        phone_keywords = ["iphone", "ipad", "apple"]
        prioritized = [d for d in devices if any(kw in (d["name"] or "").lower() for kw in phone_keywords)]
        others = [d for d in devices if d not in prioritized]
        sorted_devices = prioritized + others

        selected = show_device_list(sorted_devices)
        if selected:
            self.config["device_uuid"] = selected["uuid"]
            self.config["device_name"] = selected["name"]
            self.config.save()
            show_progress(f"已绑定: {selected['name']}")
            return selected
        return None

    def _setup_password(self):
        """兼容旧流程：自动解锁已移除"""
        show_alert(
            "ProximityLock",
            "当前版本已移除自动亮屏/自动解锁，\\n无需再设置密码。"
        )
