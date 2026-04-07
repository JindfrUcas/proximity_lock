"""
ProximityLock 信号滤波模块
原始 RSSI -> 异常值检测 -> 滤波
"""
from collections import deque

import numpy as np


class OutlierDetector:
    """异常值检测器：偏离均值超过 N 倍标准差的数据直接丢弃"""

    def __init__(self, sigma_threshold=2.0, min_samples=3):
        self.sigma = sigma_threshold
        self.min_samples = min_samples

    def is_outlier(self, value, history):
        """判断新值是否为异常值"""
        if len(history) < self.min_samples:
            return False
        arr = np.array(history)
        mean = np.mean(arr)
        std = np.std(arr)
        if std < 1e-6:
            return False
        return abs(value - mean) > self.sigma * std


class MeanFilter:
    """简单移动平均滤波"""

    def __init__(self, window_size=5):
        self.window = deque(maxlen=window_size)

    def update(self, value):
        self.window.append(value)
        return float(np.mean(self.window))

    def reset(self):
        self.window.clear()

    @property
    def value(self):
        return float(np.mean(self.window)) if self.window else None


class MedianFilter:
    """中位数滤波：对单次异常值免疫"""

    def __init__(self, window_size=7):
        self.window = deque(maxlen=window_size)

    def update(self, value):
        self.window.append(value)
        return float(np.median(self.window))

    def reset(self):
        self.window.clear()

    @property
    def value(self):
        return float(np.median(self.window)) if self.window else None


class EMAFilter:
    """指数移动平均：近期数据权重更大"""

    def __init__(self, alpha=0.3):
        self.alpha = alpha
        self._value = None

    def update(self, value):
        if self._value is None:
            self._value = float(value)
        else:
            self._value = self.alpha * value + (1 - self.alpha) * self._value
        return self._value

    def reset(self):
        self._value = None

    @property
    def value(self):
        return self._value


class KalmanFilter:
    """一维卡尔曼滤波器"""

    def __init__(self, process_noise=1.0, measurement_noise=5.0):
        self.Q = process_noise
        self.R = measurement_noise
        self.x = None
        self.P = 100.0

    def update(self, measurement):
        if self.x is None:
            self.x = float(measurement)
            return self.x

        x_pred = self.x
        P_pred = self.P + self.Q

        gain = P_pred / (P_pred + self.R)
        self.x = x_pred + gain * (measurement - x_pred)
        self.P = (1 - gain) * P_pred
        return self.x

    def reset(self):
        self.x = None
        self.P = 100.0

    @property
    def value(self):
        return self.x


class SignalProcessor:
    """信号处理器：组合滤波 + 异常值检测"""

    def __init__(self, config):
        self.config = config
        self.outlier_detector = OutlierDetector(
            sigma_threshold=config["outlier_sigma"]
        )
        self.raw_history = deque(maxlen=20)
        self.filter = self._create_filter()
        self.outlier_count = 0
        self.total_count = 0

    def _create_filter(self):
        filter_type = self.config["filter_type"]
        if filter_type == "mean":
            return MeanFilter(self.config["filter_window"])
        if filter_type == "median":
            return MedianFilter(self.config["filter_window"])
        if filter_type == "ema":
            return EMAFilter(self.config["ema_alpha"])
        return KalmanFilter(
            self.config["kalman_process_noise"],
            self.config["kalman_measurement_noise"],
        )

    def process(self, raw_rssi):
        """
        返回: (filtered_rssi, is_valid)
        """
        self.total_count += 1

        if self.outlier_detector.is_outlier(raw_rssi, list(self.raw_history)):
            self.outlier_count += 1
            return self.filter.value, False

        self.raw_history.append(raw_rssi)
        filtered = self.filter.update(raw_rssi)
        return filtered, True

    def reset(self):
        self.raw_history.clear()
        self.filter.reset()
        self.outlier_count = 0
        self.total_count = 0

    @property
    def current_value(self):
        return self.filter.value

    @property
    def stats(self):
        if not self.raw_history:
            return {"mean": None, "std": None, "outlier_rate": 0}
        arr = np.array(self.raw_history)
        rate = self.outlier_count / max(self.total_count, 1)
        return {
            "mean": float(np.mean(arr)),
            "std": float(np.std(arr)),
            "outlier_rate": rate,
        }
