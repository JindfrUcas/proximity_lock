"""
ProximityLock 配置模块
所有可调参数集中管理
"""
import json
import os

CONFIG_DIR = os.path.expanduser("~/.proximity_lock")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")
CALIBRATION_FILE = os.path.join(CONFIG_DIR, "calibration.json")

LEGACY_DEFAULTS = {
    "lock_confirm_seconds": 8.0,
    "cooldown_seconds": 15.0,
    "signal_lost_timeout": 30.0,
    "auto_unlock_enabled": True,
    "wake_on_proximity": True,
    "use_keychain": True,
}


DEFAULT_CONFIG = {
    # ---- 设备 ----
    "device_uuid": None,
    "device_name": None,

    # ---- RSSI 阈值 ----
    "unlock_rssi": -55,            # 保留旧配置兼容性，当前不再用于自动亮屏
    "lock_rssi": -72,              # 信号弱于此值时判定为离开
    "min_hysteresis": 10,

    # ---- 滤波 ----
    "filter_type": "kalman",
    "filter_window": 5,
    "ema_alpha": 0.45,
    "outlier_sigma": 2.0,

    # ---- 卡尔曼滤波参数 ----
    "kalman_process_noise": 2.0,
    "kalman_measurement_noise": 4.0,

    # ---- 锁屏判定 ----
    "lock_confirm_seconds": 0.6,   # 进入空闲检测后，持续弱信号多久视为离开
    "cooldown_seconds": 1.0,
    "signal_lost_timeout": 1.2,

    # ---- 本地空闲触发 ----
    "idle_grace_seconds": 5.0,     # 本地无输入超过该时间后才开始 BLE 检测
    "activity_poll_interval": 0.1, # 活跃阶段轮询本地空闲时间
    "idle_scan_window": 3.0,       # 单次 BLE 采样窗口；iPhone 后台广播较慢，窗口过短会漏检
    "idle_scan_pause": 0.2,        # 空闲检测阶段两次采样间隔
    "presence_confirm_samples": 2, # 进入空闲检测后，至少连续几次确认“手机在附近”才开始严格离开判断
    "presence_confirm_min_rssi": -68,  # 视为“手机就在身边”的最小 RSSI
    "unconfirmed_away_lock_seconds": 12.0,  # 还未确认手机在附近时，需要持续多久弱信号/无信号才锁屏
    "armed_missing_scan_limit": 4,  # 已确认手机在附近后，连续多少个扫描窗口都没命中才开始判离开
    "armed_missing_lock_seconds": 12.0,  # 已确认手机在附近后，连续漏检多久才判离开
    "recent_presence_memory_seconds": 180.0,  # 最近确认过手机在附近时，跨一次活跃期保留“附近”记忆

    # ---- 扫描 ----
    "scan_interval": 2.0,          # discover / calibrate 使用
    "scan_duration": 1.5,          # CLI doctor / 兼容 iPhone 较慢广播

    # ---- 功能开关 ----
    "auto_lock_enabled": True,
    "auto_unlock_enabled": False,  # 保留旧字段兼容性
    "wake_on_proximity": False,    # 保留旧字段兼容性
    "pause_media_on_lock": False,
    "notification_enabled": True,

    # ---- 安全 ----
    "use_keychain": False,         # 自动解锁已移除

    # ---- 远程授权解锁 ----
    "remote_unlock_enabled": False,
    "remote_unlock_secret": None,
    "remote_unlock_host": "0.0.0.0",
    "remote_unlock_port": 8765,
    "remote_unlock_max_attempts": 5,
    "remote_unlock_lockout_seconds": 300,
    "remote_unlock_session_minutes": 15,

    # ---- 调试 ----
    "debug_logging": False,
}


class Config:
    """配置管理器"""

    def __init__(self):
        self._config = DEFAULT_CONFIG.copy()
        self._load()

    def _ensure_dir(self):
        os.makedirs(CONFIG_DIR, exist_ok=True)

    def _load(self):
        """从文件加载配置"""
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    saved = json.load(f)
                self._config.update(saved)
                self._migrate_legacy_defaults(saved)
            except (json.JSONDecodeError, IOError):
                pass

    def _migrate_legacy_defaults(self, saved):
        """
        只替换旧版本默认值，不覆盖用户自己改过的配置。
        """
        for key, legacy_value in LEGACY_DEFAULTS.items():
            if saved.get(key) == legacy_value:
                self._config[key] = DEFAULT_CONFIG[key]

    def save(self):
        """保存配置到文件"""
        self._ensure_dir()
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(self._config, f, indent=2, ensure_ascii=False)

    def get(self, key, default=None):
        return self._config.get(key, default)

    def set(self, key, value):
        self._config[key] = value

    def __getitem__(self, key):
        return self._config[key]

    def __setitem__(self, key, value):
        self._config[key] = value

    @property
    def lock_rssi(self):
        return self._config["lock_rssi"]

    @property
    def unlock_rssi(self):
        return self._config["unlock_rssi"]

    def set_thresholds(self, unlock_rssi, lock_rssi):
        """设置阈值，强制保证迟滞区间"""
        min_gap = self._config["min_hysteresis"]
        if unlock_rssi - lock_rssi < min_gap:
            lock_rssi = unlock_rssi - min_gap
        self._config["unlock_rssi"] = unlock_rssi
        self._config["lock_rssi"] = lock_rssi

    def to_dict(self):
        return self._config.copy()
