"""timebox-enforcer.py — P0 时间盒执行器（无 Timer 泄漏，monotonic clock）

Usage:
    from timebox_enforcer import TimeBoxEnforcer, TIMEBOX_CONFIG
    
    enforcer = TimeBoxEnforcer(on_timeout=my_callback)
    enforcer.start("debate_round_1", timeout=600, label="辩论第1轮")
    enforcer.extend("debate_round_1", extra_seconds=300)
    remaining = enforcer.remaining("debate_round_1")
    enforcer.cancel("debate_round_1")
"""

import threading
import time
from dataclasses import dataclass, field
from typing import Dict, Optional, Callable, Any
from enum import Enum


class TimeBoxStatus(str, Enum):
    RUNNING = "running"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


@dataclass
class TimeBox:
    """单个时间盒"""
    box_id: str
    timeout: float
    label: str = ""
    deadline: float = 0.0
    status: TimeBoxStatus = TimeBoxStatus.RUNNING
    cancel_event: threading.Event = field(default_factory=threading.Event)
    thread: Optional[threading.Thread] = None
    created_at: float = 0.0
    expired_at: float = 0.0


# 分层时间盒配置（秒）
TIMEBOX_CONFIG = {
    "simple": {
        "pre_discussion": 5 * 60,      # 5min
        "debate_round": 5 * 60,        # 5min per round
        "consensus_check": 5 * 60,     # 5min
        "total": 30 * 60,              # 30min 总时间
    },
    "medium": {
        "pre_discussion": 10 * 60,     # 10min
        "debate_round": 10 * 60,       # 10min per round
        "consensus_check": 10 * 60,    # 10min
        "total": 60 * 60,              # 60min
    },
    "complex": {
        "pre_discussion": 15 * 60,     # 15min
        "debate_round": 10 * 60,       # 10min per round
        "consensus_check": 10 * 60,    # 10min
        "total": 120 * 60,             # 120min
    },
}


class TimeBoxEnforcer:
    """时间盒执行器（修正版：threading.Event + monotonic clock，无 Timer 泄漏）"""

    def __init__(self, on_timeout: Optional[Callable[[str, str], None]] = None):
        """
        Args:
            on_timeout: 超时回调 (box_id, label) -> None
        """
        self._boxes: Dict[str, TimeBox] = {}
        self._lock = threading.Lock()
        self._on_timeout = on_timeout

    def start(self, box_id: str, timeout: float, label: str = "") -> None:
        """启动时间盒"""
        with self._lock:
            # 如果已存在同名时间盒，先取消
            if box_id in self._boxes:
                self._cancel_unlocked(box_id)

            now = time.monotonic()
            box = TimeBox(
                box_id=box_id,
                timeout=timeout,
                label=label or box_id,
                deadline=now + timeout,
                created_at=now,
            )

            def _worker():
                cancelled = box.cancel_event.wait(timeout=timeout)
                with self._lock:
                    if not cancelled and box_id in self._boxes:
                        box.status = TimeBoxStatus.EXPIRED
                        box.expired_at = time.monotonic()
                        if self._on_timeout:
                            try:
                                self._on_timeout(box_id, box.label)
                            except Exception:
                                pass

            t = threading.Thread(
                target=_worker,
                daemon=True,
                name=f"TimeBox-{box_id}",
            )
            t.start()
            box.thread = t
            self._boxes[box_id] = box

    def cancel(self, box_id: str) -> bool:
        """取消时间盒"""
        with self._lock:
            return self._cancel_unlocked(box_id)

    def _cancel_unlocked(self, box_id: str) -> bool:
        """取消时间盒（内部，需持锁）"""
        box = self._boxes.get(box_id)
        if not box:
            return False
        box.cancel_event.set()
        box.status = TimeBoxStatus.CANCELLED
        del self._boxes[box_id]
        return True

    def extend(self, box_id: str, extra_seconds: float) -> bool:
        """延长时间盒（先取消旧的，再启动新的）"""
        with self._lock:
            box = self._boxes.get(box_id)
            if not box or box.status != TimeBoxStatus.RUNNING:
                return False
            old_label = box.label
            self._cancel_unlocked(box_id)

        # 重新启动（在锁外，避免死锁）
        self.start(box_id, box.timeout + extra_seconds, old_label)
        return True

    def remaining(self, box_id: str) -> float:
        """剩余时间（秒），不存在或已过期返回 0"""
        with self._lock:
            box = self._boxes.get(box_id)
            if not box or box.status != TimeBoxStatus.RUNNING:
                return 0.0
            return max(0.0, box.deadline - time.monotonic())

    def status(self, box_id: str) -> Optional[TimeBoxStatus]:
        """获取时间盒状态"""
        with self._lock:
            box = self._boxes.get(box_id)
            return box.status if box else None

    def active_boxes(self) -> list:
        """列出所有活跃时间盒"""
        with self._lock:
            return [
                {
                    "box_id": b.box_id,
                    "label": b.label,
                    "remaining": max(0.0, b.deadline - time.monotonic()),
                    "timeout": b.timeout,
                    "status": b.status.value,
                }
                for b in self._boxes.values()
                if b.status == TimeBoxStatus.RUNNING
            ]

    def cancel_all(self) -> int:
        """取消所有时间盒"""
        with self._lock:
            count = len(self._boxes)
            for box_id in list(self._boxes.keys()):
                self._cancel_unlocked(box_id)
            return count


# ── 便捷函数 ─────────────────────────────────────────────

_global_enforcer: Optional[TimeBoxEnforcer] = None


def get_enforcer() -> TimeBoxEnforcer:
    """获取全局时间盒执行器"""
    global _global_enforcer
    if _global_enforcer is None:
        _global_enforcer = TimeBoxEnforcer()
    return _global_enforcer


def start_timebox(box_id: str, timeout: float, label: str = "", 
                  on_timeout: Optional[Callable] = None) -> None:
    """启动全局时间盒"""
    enforcer = get_enforcer()
    if on_timeout:
        enforcer._on_timeout = on_timeout
    enforcer.start(box_id, timeout, label)


def cancel_timebox(box_id: str) -> bool:
    """取消全局时间盒"""
    return get_enforcer().cancel(box_id)


if __name__ == "__main__":
    # 测试
    def on_expire(box_id, label):
        print(f"⏰ 时间盒超时: {box_id} ({label})")

    enforcer = TimeBoxEnforcer(on_timeout=on_expire)
    
    enforcer.start("test1", 3, "测试时间盒")
    print(f"剩余: {enforcer.remaining('test1'):.1f}s")
    
    import time
    time.sleep(1)
    enforcer.extend("test1", 2)
    print(f"延长后剩余: {enforcer.remaining('test1'):.1f}s")
    
    time.sleep(1)
    enforcer.cancel("test1")
    print(f"取消后状态: {enforcer.status('test1')}")
    
    # 测试自动超时
    enforcer.start("test2", 2, "自动超时测试")
    print(f"活跃时间盒: {enforcer.active_boxes()}")
    time.sleep(3)
    print("测试完成")
