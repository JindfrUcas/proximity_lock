"""
ProximityLock BLE 扫描模块
使用 bleak 进行 BLE 设备发现和 RSSI 监测
"""
import asyncio
import time

from bleak import BleakScanner


class BLEProximityScanner:
    """
    BLE 近距离扫描器

    工作模式：
    1. discover 模式：扫描附近所有 BLE 设备，用于初始配对
    2. monitor 模式：持续监测目标设备的 RSSI 信号
    """

    def __init__(self, config):
        self.config = config
        self._scanner = None
        self._target_uuid = config.get("device_uuid")
        self._target_name = config.get("device_name")
        self._on_rssi_update = None
        self._on_device_found = None
        self._on_signal_lost = None
        self._last_seen = {}
        self._running = False

    def set_target(self, uuid):
        """设置要监控的目标设备 UUID"""
        self._target_uuid = uuid
        self.config["device_uuid"] = uuid

    def _target_matches(self, device, advertisement_data, allow_name_fallback=True):
        """
        iPhone 可能发生 BLE 地址轮换。
        优先匹配已知地址；如果地址变了，则允许通过设备名 + Apple 厂商数据回认。
        """
        if self._target_uuid and device.address == self._target_uuid:
            return True

        if not allow_name_fallback or not self._target_name:
            return False

        name = device.name or advertisement_data.local_name
        if not name or name != self._target_name:
            return False

        manufacturer_data = advertisement_data.manufacturer_data or {}
        if 0x004C not in manufacturer_data:
            return False

        if self._target_uuid and device.address != self._target_uuid:
            print(f"[BLE] 检测到地址轮换: {self._target_uuid} -> {device.address}")
        self._target_uuid = device.address
        self.config["device_uuid"] = device.address
        return True

    async def discover_devices(self, duration=5.0):
        """
        扫描附近的 BLE 设备

        Returns:
            list of dict: [{"uuid": ..., "name": ..., "rssi": ...}, ...]
        """
        print(f"[BLE] 开始扫描设备 ({duration}秒)...")
        devices = []
        seen = set()

        def detection_callback(device, advertisement_data):
            if device.address not in seen:
                seen.add(device.address)
                info = {
                    "uuid": device.address,
                    "name": device.name or advertisement_data.local_name or "未知设备",
                    "rssi": advertisement_data.rssi,
                }
                devices.append(info)
                if self._on_device_found:
                    self._on_device_found(info)

        scanner = BleakScanner(detection_callback=detection_callback)
        await scanner.start()
        await asyncio.sleep(duration)
        await scanner.stop()

        # 按 RSSI 从强到弱排序
        devices.sort(key=lambda d: d["rssi"], reverse=True)
        print(f"[BLE] 发现 {len(devices)} 个设备")
        return devices

    async def start_monitoring(self, on_rssi_update=None, on_signal_lost=None):
        """
        开始持续监控目标设备的 RSSI

        Args:
            on_rssi_update: 回调函数 (rssi: int, device_name: str)
            on_signal_lost: 回调函数 ()
        """
        if not self._target_uuid:
            print("[BLE] 错误: 未设置目标设备")
            return

        self._on_rssi_update = on_rssi_update
        self._on_signal_lost = on_signal_lost
        self._running = True
        self._last_seen_time = time.time()

        print(f"[BLE] 开始监控设备: {self._target_uuid}")

        while self._running:
            try:
                await self._scan_once()
            except Exception as e:
                print(f"[BLE] 扫描错误: {e}")
            await asyncio.sleep(self.config["scan_interval"])

    async def sample_rssi(self, scan_window=None):
        """
        在短时间窗口内采样目标设备 RSSI。

        Returns:
            (rssi, name) 或 None
        """
        if not self._target_uuid:
            return None

        scan_window = scan_window or self.config.get("idle_scan_window", 0.35)
        strongest = {"rssi": None, "name": None}

        def detection_callback(device, advertisement_data):
            if self._target_matches(device, advertisement_data):
                self._last_seen_time = time.time()
                rssi = advertisement_data.rssi
                name = device.name or advertisement_data.local_name or "iPhone"
                if strongest["rssi"] is None or rssi > strongest["rssi"]:
                    strongest["rssi"] = rssi
                    strongest["name"] = name

        scanner = BleakScanner(detection_callback=detection_callback)
        await scanner.start()
        await asyncio.sleep(max(scan_window, 0.05))
        await scanner.stop()

        if strongest["rssi"] is None:
            return None
        return strongest["rssi"], strongest["name"]

    async def debug_probe(self, duration=12.0, scan_window=None):
        """
        CLI 调试：持续输出目标设备是否被匹配到，以及 RSSI。
        """
        if not self._target_uuid and not self._target_name:
            print("[BLE] 未设置目标设备，无法调试扫描")
            return []

        scan_window = scan_window or self.config.get("scan_duration", 1.5)
        deadline = time.time() + duration
        samples = []

        while time.time() < deadline:
            strongest = {"rssi": None, "name": None, "address": None}

            def detection_callback(device, advertisement_data):
                if self._target_matches(device, advertisement_data):
                    rssi = advertisement_data.rssi
                    name = device.name or advertisement_data.local_name or "iPhone"
                    if strongest["rssi"] is None or rssi > strongest["rssi"]:
                        strongest["rssi"] = rssi
                        strongest["name"] = name
                        strongest["address"] = device.address

            scanner = BleakScanner(detection_callback=detection_callback)
            await scanner.start()
            await asyncio.sleep(max(scan_window, 0.1))
            await scanner.stop()

            ts = time.strftime("%H:%M:%S")
            if strongest["rssi"] is None:
                print(f"[{ts}] 未扫到目标设备")
                samples.append(None)
            else:
                print(
                    f"[{ts}] 命中 {strongest['name']} {strongest['address']} "
                    f"{strongest['rssi']}dBm"
                )
                samples.append((strongest["rssi"], strongest["name"], strongest["address"]))

            await asyncio.sleep(max(self.config.get("idle_scan_pause", 0.05), 0.1))

        return samples

    async def _scan_once(self):
        """执行一次扫描并分发回调"""
        sample = await self.sample_rssi(
            scan_window=min(self.config["scan_interval"], 2.0)
        )

        # 检查信号是否丢失
        if sample is None:
            elapsed = time.time() - self._last_seen_time
            if elapsed > self.config["signal_lost_timeout"]:
                if self._on_signal_lost:
                    self._on_signal_lost()
            return

        rssi, name = sample
        if self._on_rssi_update:
            self._on_rssi_update(rssi, name)

    def stop_monitoring(self):
        """停止监控"""
        self._running = False
        print("[BLE] 监控已停止")


async def discover_and_select():
    """
    交互式设备发现和选择（命令行模式）

    Returns:
        (uuid, name) 或 None
    """
    scanner = BLEProximityScanner({"device_uuid": None, "scan_interval": 2.0, "signal_lost_timeout": 30.0})
    print("\n🔍 正在扫描附近的 BLE 设备...\n")
    devices = await scanner.discover_devices(duration=8.0)

    if not devices:
        print("❌ 未发现任何设备")
        return None

    # 过滤掉明显不是手机的设备
    phone_keywords = ["iphone", "ipad", "phone", "apple"]
    prioritized = []
    others = []
    for d in devices:
        name_lower = (d["name"] or "").lower()
        if any(kw in name_lower for kw in phone_keywords):
            prioritized.append(d)
        else:
            others.append(d)

    all_devices = prioritized + others

    print(f"\n{'序号':<4} {'设备名':<30} {'UUID':<40} {'RSSI':>6}")
    print("-" * 82)
    for i, d in enumerate(all_devices):
        marker = " ⭐" if d in prioritized else ""
        print(f"{i+1:<4} {d['name']:<30} {d['uuid']:<40} {d['rssi']:>4}dBm{marker}")

    print("\n⭐ = 可能是你的 iPhone")
    choice = input("\n请输入设备序号 (或 q 退出): ").strip()

    if choice.lower() == 'q':
        return None

    try:
        idx = int(choice) - 1
        if 0 <= idx < len(all_devices):
            selected = all_devices[idx]
            return selected["uuid"], selected["name"]
    except ValueError:
        pass

    print("❌ 无效选择")
    return None
