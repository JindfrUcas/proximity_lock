"""
ProximityLock 校准模块
优化点 6：引导用户做校准，自动计算最佳阈值
"""
import asyncio
import time
import json
import os
import numpy as np
from config import CALIBRATION_FILE, CONFIG_DIR


class Calibrator:
    """
    交互式校准

    流程：
    1. 让用户坐在电脑前，采集 "近" 的 RSSI 分布
    2. 让用户走到门口/远处，采集 "远" 的 RSSI 分布
    3. 自动计算最佳阈值
    """

    def __init__(self, scanner, config):
        self.scanner = scanner
        self.config = config
        self.near_samples = []
        self.far_samples = []

    async def collect_samples(self, duration=10, label=""):
        """收集指定时间段的 RSSI 样本"""
        samples = []
        start = time.time()

        def on_rssi(rssi, name):
            samples.append(rssi)
            elapsed = time.time() - start
            remaining = duration - elapsed
            if remaining > 0:
                print(f"\r  📡 RSSI: {rssi}dBm | 已采集 {len(samples)} 个样本 | 剩余 {remaining:.0f}秒", end="", flush=True)

        self.scanner._on_rssi_update = on_rssi
        self.scanner._running = True

        # 运行采集
        end_time = time.time() + duration
        while time.time() < end_time and self.scanner._running:
            await self.scanner._scan_once()
            await asyncio.sleep(0.5)

        print()  # 换行
        return samples

    async def run_calibration(self):
        """运行完整校准流程"""
        print("\n" + "=" * 60)
        print("  🎯 ProximityLock 校准向导")
        print("=" * 60)

        # 第一步：采集近距离数据
        print("\n📍 第 1 步：请坐在电脑旁边，保持正常使用姿态")
        input("  准备好后按回车开始采集... ")
        print(f"  开始采集 \"近距离\" 数据 (10秒)...")
        self.near_samples = await self.collect_samples(duration=10, label="near")

        if len(self.near_samples) < 3:
            print("❌ 近距离样本不足，请检查蓝牙连接")
            return None

        # 第二步：采集远距离数据
        print("\n📍 第 2 步：请拿着手机走到门口或另一个房间")
        input("  准备好后按回车开始采集... ")
        print(f"  开始采集 \"远距离\" 数据 (10秒)...")
        self.far_samples = await self.collect_samples(duration=10, label="far")

        if len(self.far_samples) < 3:
            print("❌ 远距离样本不足")
            return None

        # 第三步：计算最佳阈值
        result = self._calculate_thresholds()
        return result

    def _calculate_thresholds(self):
        """根据采集数据计算最佳阈值"""
        near = np.array(self.near_samples)
        far = np.array(self.far_samples)

        near_mean = np.mean(near)
        near_std = np.std(near)
        far_mean = np.mean(far)
        far_std = np.std(far)

        print(f"\n📊 采集结果:")
        print(f"  近距离: 均值={near_mean:.1f}dBm, 标准差={near_std:.1f}dBm, 样本数={len(near)}")
        print(f"  远距离: 均值={far_mean:.1f}dBm, 标准差={far_std:.1f}dBm, 样本数={len(far)}")

        # 检查数据有效性
        if near_mean <= far_mean:
            print("⚠️ 警告: 近距离信号不强于远距离信号，数据可能有误")
            print("  使用默认阈值")
            return {
                "unlock_rssi": -55,
                "lock_rssi": -75,
                "quality": "poor",
            }

        gap = near_mean - far_mean
        print(f"  信号差: {gap:.1f}dBm")

        # 计算阈值：
        # unlock_rssi 保留为“近距离参考值”，仅用于兼容旧配置
        # lock_rssi 才是当前版本实际用于锁屏的阈值
        unlock_rssi = int(near_mean - near_std)
        lock_rssi = int(far_mean + far_std)

        # 确保迟滞区间足够
        min_gap = self.config["min_hysteresis"]
        if unlock_rssi - lock_rssi < min_gap:
            mid = (unlock_rssi + lock_rssi) / 2
            unlock_rssi = int(mid + min_gap / 2)
            lock_rssi = int(mid - min_gap / 2)

        quality = "excellent" if gap > 20 else "good" if gap > 10 else "fair"

        result = {
            "unlock_rssi": unlock_rssi,
            "lock_rssi": lock_rssi,
            "near_mean": float(near_mean),
            "near_std": float(near_std),
            "far_mean": float(far_mean),
            "far_std": float(far_std),
            "quality": quality,
        }

        print(f"\n✅ 推荐阈值:")
        print(f"  近距离参考值: {unlock_rssi}dBm")
        print(f"  锁屏阈值: {lock_rssi}dBm")
        print(f"  迟滞区间: {unlock_rssi - lock_rssi}dBm")
        print(f"  校准质量: {quality}")

        # 保存校准结果
        self._save_calibration(result)

        return result

    def _save_calibration(self, result):
        """保存校准结果"""
        os.makedirs(CONFIG_DIR, exist_ok=True)
        data = {
            "timestamp": time.time(),
            "near_samples": self.near_samples,
            "far_samples": self.far_samples,
            "result": result,
        }
        with open(CALIBRATION_FILE, "w") as f:
            json.dump(data, f, indent=2)
        print(f"  校准数据已保存到 {CALIBRATION_FILE}")

    @staticmethod
    def load_calibration():
        """加载上次校准结果"""
        if os.path.exists(CALIBRATION_FILE):
            try:
                with open(CALIBRATION_FILE, "r") as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                pass
        return None
