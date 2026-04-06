"""
ProximityLock 锁屏状态机
只保留“离开熄屏”路径，回来后仅做静默复位，不主动亮屏/解锁
"""
import time
from enum import Enum


class ProximityState(Enum):
    """近距离状态"""

    PRESENT = "present"
    TRANSITIONING_OUT = "going"
    AWAY = "away"
    SIGNAL_LOST = "lost"


class StateMachine:
    """
    锁屏状态机

    状态转换图:
        PRESENT ──(RSSI 持续 < lock_rssi)──> TRANSITIONING_OUT ──(持续 N 秒)──> AWAY
        PRESENT / TRANSITIONING_OUT ──(信号丢失超时)──> SIGNAL_LOST
        AWAY / SIGNAL_LOST ──(检测到本地操作)──> PRESENT
    """

    def __init__(self, config, on_lock=None, on_signal_lost=None):
        self.config = config
        self.state = ProximityState.PRESENT
        self.on_lock = on_lock
        self.on_signal_lost = on_signal_lost

        self._last_state_change = 0.0
        self._last_signal_time = time.time()
        self._transition_out_start = None

    @property
    def in_cooldown(self):
        """是否在冷却期"""
        return (time.time() - self._last_state_change) < self.config["cooldown_seconds"]

    def _reset_transition(self):
        self._transition_out_start = None

    def _change_state(self, new_state, reason="", trigger_callbacks=True):
        """切换状态"""
        old_state = self.state
        if new_state == old_state:
            return

        self.state = new_state
        self._last_state_change = time.time()

        if new_state != ProximityState.TRANSITIONING_OUT:
            self._reset_transition()

        print(f"[状态] {old_state.value} → {new_state.value} ({reason})")

        if not trigger_callbacks:
            return

        if new_state in (ProximityState.AWAY, ProximityState.SIGNAL_LOST):
            if old_state in (ProximityState.PRESENT, ProximityState.TRANSITIONING_OUT):
                if self.on_lock:
                    self.on_lock(reason)
        if new_state == ProximityState.SIGNAL_LOST and self.on_signal_lost:
            self.on_signal_lost()

    def mark_present(self, reason="检测到本地操作"):
        """检测到本地活动时静默复位，不触发亮屏/解锁"""
        self._last_signal_time = time.time()
        if self.state != ProximityState.PRESENT:
            self._change_state(ProximityState.PRESENT, reason, trigger_callbacks=False)
        else:
            self._reset_transition()

    def update(self, filtered_rssi):
        """
        用滤波后的 RSSI 更新状态机

        Args:
            filtered_rssi: float | None
        """
        now = time.time()

        if filtered_rssi is None:
            time_since_signal = now - self._last_signal_time
            if (
                self.state in (ProximityState.PRESENT, ProximityState.TRANSITIONING_OUT)
                and time_since_signal >= self.config["signal_lost_timeout"]
            ):
                self._change_state(
                    ProximityState.SIGNAL_LOST,
                    f"空闲检测期间信号丢失 {time_since_signal:.1f} 秒",
                )
            return self.state

        self._last_signal_time = now

        if self.state in (ProximityState.AWAY, ProximityState.SIGNAL_LOST):
            return self.state

        if self.in_cooldown and self.state == ProximityState.PRESENT:
            return self.state

        lock_rssi = self.config["lock_rssi"]
        lock_need_sec = self.config["lock_confirm_seconds"]

        if self.state == ProximityState.PRESENT:
            if filtered_rssi < lock_rssi:
                self._transition_out_start = now
                if lock_need_sec <= 0:
                    self._change_state(
                        ProximityState.AWAY,
                        f"RSSI {filtered_rssi:.0f}dBm 低于阈值 {lock_rssi}dBm",
                    )
                else:
                    self._change_state(
                        ProximityState.TRANSITIONING_OUT,
                        f"RSSI 降至 {filtered_rssi:.0f}dBm",
                        trigger_callbacks=False,
                    )
            else:
                self._reset_transition()

        elif self.state == ProximityState.TRANSITIONING_OUT:
            if filtered_rssi < lock_rssi:
                if self._transition_out_start is None:
                    self._transition_out_start = now
                elapsed = now - self._transition_out_start
                if elapsed >= lock_need_sec:
                    self._change_state(
                        ProximityState.AWAY,
                        f"RSSI {filtered_rssi:.0f}dBm 持续 {elapsed:.2f} 秒",
                    )
            else:
                self._change_state(
                    ProximityState.PRESENT,
                    f"RSSI 回升到 {filtered_rssi:.0f}dBm",
                    trigger_callbacks=False,
                )

        return self.state

    def check_signal_timeout(self):
        """兼容旧接口"""
        self.update(None)

    def force_state(self, state, reason="手动设置"):
        """强制设置状态"""
        self._change_state(state, reason, trigger_callbacks=False)

    def lock_now(self, reason="离开确认"):
        """跳过过渡，直接进入锁屏状态"""
        self._change_state(ProximityState.AWAY, reason, trigger_callbacks=True)

    @property
    def status_text(self):
        texts = {
            ProximityState.PRESENT: "在旁边",
            ProximityState.TRANSITIONING_OUT: "正在离开...",
            ProximityState.AWAY: "已离开",
            ProximityState.SIGNAL_LOST: "信号丢失",
        }
        return texts.get(self.state, "未知")
