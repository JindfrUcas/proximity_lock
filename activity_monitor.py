"""
macOS 本地活动监控
"""
try:
    from Quartz import (
        CGEventSourceSecondsSinceLastEventType,
        kCGAnyInputEventType,
        kCGEventSourceStateCombinedSessionState,
    )
except Exception:  # pragma: no cover - 非 macOS 环境只做降级
    CGEventSourceSecondsSinceLastEventType = None
    kCGAnyInputEventType = None
    kCGEventSourceStateCombinedSessionState = None


class ActivityMonitor:
    """读取本地键盘/鼠标空闲时间"""

    def __init__(self):
        self.available = CGEventSourceSecondsSinceLastEventType is not None

    def get_idle_seconds(self):
        """返回本地输入空闲秒数"""
        if not self.available:
            return 0.0
        try:
            return float(
                CGEventSourceSecondsSinceLastEventType(
                    kCGEventSourceStateCombinedSessionState,
                    kCGAnyInputEventType,
                )
            )
        except Exception:
            return 0.0
