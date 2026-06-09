"""hub.py - Team-Brain 协作中心（后台线程版）

Hub 运行在独立后台线程中，不阻塞主 agent 响应。
消息通过文件 MessageBus 传递（messages/inbox/ + messages/outbox/）。

使用方式：
    from hub import Hub, start_hub
    hub = start_hub(team_id, agent_ids, team_brain_root)
    # 主 agent 可以随时 hub.send_to(agent_id, message) 或 hub.broadcast(msg)
"""

import json
import os
import sys
import time
import uuid
import threading
import importlib.util
from pathlib import Path
from typing import List, Dict, Optional, Callable, Set
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum

# 强制 stdout/stderr 使用 UTF-8，解决 Windows GBK 控制台输出中文乱码
if sys.platform == "win32":
    import locale
    locale.setlocale(locale.LC_ALL, '')
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

# P2: watchdog 支持（可选）
try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler, FileModifiedEvent
    WATCHDOG_AVAILABLE = True
except ImportError:
    WATCHDOG_AVAILABLE = False

# 导入原子写入
SCRIPT_DIR = Path(__file__).parent
_spec = importlib.util.spec_from_file_location("atomic_write", str(SCRIPT_DIR / "atomic-write.py"))
_aw = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_aw)
atomic_write = _aw.atomic_write

# ── v4.0 增强模块（可选加载） ──────────────────────────────
_ENHANCEMENTS_LOADED = False
_conflict_detector = None
_timebox_enforcer = None
_debate_controller = None
_anti_formalism = None
_expert_weight = None
_consensus_metrics = None
def _load_enhancements():
    global _ENHANCEMENTS_LOADED, _conflict_detector, _timebox_enforcer
    global _debate_controller, _anti_formalism, _expert_weight, _consensus_metrics
    if _ENHANCEMENTS_LOADED:
        return
    _ENHANCEMENTS_LOADED = True
    try:
        import conflict_detector as cd
        _conflict_detector = cd
    except ImportError:
        pass
    try:
        import timebox_enforcer as tb
        _timebox_enforcer = tb
    except ImportError:
        pass
    try:
        import anti_formalism as af
        _anti_formalism = af
    except ImportError:
        pass
    try:
        import expert_weight as ew
        _expert_weight = ew
    except ImportError:
        pass
    try:
        import consensus_metrics as cm
        _consensus_metrics = cm
    except ImportError:
        pass

# 加载增强配置
_ENHANCEMENT_CONFIG = {}
def _load_config():
    global _ENHANCEMENT_CONFIG
    config_path = SCRIPT_DIR / "enhancement_config.json"
    if config_path.exists():
        try:
            with open(config_path, encoding="utf-8") as f:
                _ENHANCEMENT_CONFIG = json.load(f)
        except Exception:
            pass
_load_config()


class MessageType(str, Enum):
    QUESTION = "question"
    ANSWER = "answer"
    CHALLENGE = "challenge"
    AGREE = "agree"
    DISAGREE = "disagree"
    RETRACT = "retract"
    VOTE = "vote"
    SYSTEM = "system"


@dataclass
class Message:
    msg_id: str
    type: str
    from_agent: str
    to: str  # agent_id or "HUB" or "BROADCAST"
    round: int = 0
    thread_id: Optional[str] = None
    payload: Dict = field(default_factory=dict)
    timestamp: str = ""
    reply_to: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "msg_id": self.msg_id,
            "type": self.type,
            "from": self.from_agent,
            "to": self.to,
            "round": self.round,
            "thread_id": self.thread_id,
            "payload": self.payload,
            "timestamp": self.timestamp,
            "reply_to": self.reply_to,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Message":
        return cls(
            msg_id=d["msg_id"],
            type=d["type"],
            from_agent=d["from"],
            to=d["to"],
            round=d.get("round", 0),
            thread_id=d.get("thread_id"),
            payload=d.get("payload", {}),
            timestamp=d.get("timestamp", ""),
            reply_to=d.get("reply_to"),
        )


class DiscussionPhase(str, Enum):
    IDLE = "idle"
    PRE_DISCUSSION = "pre_discussion"
    DEBATE = "debate"
    CONVERGE = "converge"
    CONSENSUS = "consensus"


@dataclass
class DiscussionState:
    phase: DiscussionPhase = DiscussionPhase.IDLE
    round: int = 0
    round_start: float = 0.0
    pre_discussion_minutes: float = 5.0
    debate_rounds: int = 2
    silence_timeout: float = 600.0  # 10min
    converge_timeout: float = 600.0  # 10min after converge starts
    votes: List[Dict] = field(default_factory=list)
    consensus_reached: bool = False


class Hub:
    """协作中心 — 后台线程运行，不阻塞主 agent"""

    def __init__(
        self,
        team_id: str,
        agent_ids: List[str],
        root: Path,
        poll_interval: float = 2.0,
        on_message: Optional[Callable[[Message, "Hub"], None]] = None,
        use_watchdog: bool = True,
    ):
        self.team_id = team_id
        self.agent_ids: List[str] = agent_ids
        self.root = Path(root)
        self.poll_interval = poll_interval
        self.on_message = on_message
        # 注意：watchdog 在 Windows 上与 daemon 线程存在兼容性问题，暂时默认关闭
        # 如需启用，传入 use_watchdog=True（需在主线程启动后的非 daemon 环境）
        self.use_watchdog = False  # 暂用 polling 模式（poll_interval=0.3s ≈ 300ms 延迟）

        self._active = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._observer: Optional[Observer] = None
        # Watchdog → Hub 通信：线程安全队列
        self._watchdog_queue: List[Dict] = []
        self._wq_lock = threading.Lock()

        # 消息统计
        self._msg_count = 0
        self._round = 0
        self._discussion_active = False
        self._last_activity = time.time()

        # 讨论状态机
        self._disc = DiscussionState()
        self._disc_start_time: float = 0.0

        # v4.0 增强组件（延迟加载）
        self._debate = None
        self._timebox = None
        self._anti_formalism_checker = None
        self._expert_weight_mgr = None

        # 每个 agent 的 inbox 目录
        self._ensure_dirs()

    def _ensure_dirs(self):
        for agent_id in self.agent_ids:
            (self.root / "messages" / "inbox" / agent_id).mkdir(parents=True, exist_ok=True)
            (self.root / "messages" / "outbox" / agent_id).mkdir(parents=True, exist_ok=True)

    def _now(self) -> str:
        return time.strftime("%Y-%m-%dT%H:%M:%S+08:00")

    def _new_msg_id(self) -> str:
        return f"msg-{time.strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6]}"

    # ── 发送消息 ────────────────────────────────────────────────

    def send_to(self, agent_id: str, msg_type: str, payload: Dict, from_agent: str = "HUB") -> str:
        """发送消息给指定专家"""
        msg = Message(
            msg_id=self._new_msg_id(),
            type=msg_type,
            from_agent=from_agent,
            to=agent_id,
            round=self._round,
            thread_id=None,
            payload=payload,
            timestamp=self._now(),
        )
        self._write_to_inbox(agent_id, msg)
        return msg.msg_id

    def broadcast(self, msg_type: str, payload: Dict, from_agent: str = "HUB") -> List[str]:
        """广播消息给所有专家"""
        msg_ids = []
        for agent_id in self.agent_ids:
            msg_id = self.send_to(agent_id, msg_type, payload, from_agent)
            msg_ids.append(msg_id)
        return msg_ids

    def send_question(self, to_agent: str, subject: str, content: str, from_agent: str = "HUB") -> str:
        return self.send_to(to_agent, MessageType.QUESTION, {"subject": subject, "content": content}, from_agent)

    def send_system(self, content: str, broadcast: bool = True) -> List[str]:
        payload = {"content": content}
        if broadcast:
            return self.broadcast(MessageType.SYSTEM, payload)
        return []

    # ── 消息写入 ────────────────────────────────────────────────

    def _write_to_inbox(self, agent_id: str, msg: Message):
        inbox_path = self.root / "messages" / "inbox" / agent_id / f"{msg.msg_id}.json"
        atomic_write(str(inbox_path), json.dumps(msg.to_dict(), ensure_ascii=False, indent=2))

    def _write_to_outbox(self, agent_id: str, msg: Message):
        outbox_path = self.root / "messages" / "outbox" / agent_id / f"{msg.msg_id}.json"
        atomic_write(str(outbox_path), json.dumps(msg.to_dict(), ensure_ascii=False, indent=2))

    # ── 后台线程 ───────────────────────────────────────────────

    def start(self):
        """启动 Hub 后台线程"""
        with self._lock:
            if self._active:
                return
            self._active = True
            if self.use_watchdog:
                self._observer = self._setup_watchdog_observer()
            self._thread = threading.Thread(target=self._loop, daemon=True, name=f"Hub-{self.team_id}")
            self._thread.start()

    def stop(self):
        """停止 Hub 后台线程"""
        with self._lock:
            self._active = False
            if self._observer:
                self._observer.stop()
                self._observer = None
            # v4.0: 停止时间盒
            if self._timebox:
                self._timebox.cancel_all()

    def _setup_watchdog_observer(self) -> Optional[Observer]:
        """设置 Watchdog 文件监控（替代轮询）"""
        if not WATCHDOG_AVAILABLE:
            return None

        _hub = self  # closure-captured reference
        _queue = self._watchdog_queue  # shared queue
        _q_lock = self._wq_lock
        class _MsgHandler(FileSystemEventHandler):
            def on_created(self, event):
                if event.is_directory:
                    return
                path = Path(event.src_path)
                if path.suffix == ".json" and path.parent.name == "outbox":
                    try:
                        msg_data = json.loads(path.read_text(encoding="utf-8"))
                        with _q_lock:
                            _queue.append(msg_data)
                        path.unlink()
                    except Exception:
                        pass

        observer = Observer()
        for agent_id in self.agent_ids:
            outbox = self.root / "messages" / "outbox" / agent_id
            if outbox.exists():
                observer.schedule(_MsgHandler(), str(outbox), recursive=False)
        observer.start()
        return observer

    def _loop(self):
        """Hub 主循环 — watchdog 事件通过队列路由，polling 降级路径"""
        while self._active:
            try:
                # 1. Watchdog 事件队列（事件驱动路径）
                if self.use_watchdog:
                    with self._wq_lock:
                        while self._watchdog_queue:
                            msg_data = self._watchdog_queue.pop(0)
                            msg = Message.from_dict(msg_data)
                            self._route(msg)
                # 2. 降级轮询路径（watchdog 不可用时）
                else:
                    self._poll_outboxes()
                self._check_activity()
            except Exception as e:
                pass
            time.sleep(self.poll_interval)

    def _poll_outboxes(self):
        """轮询所有专家的 outbox，路由消息"""
        for agent_id in self.agent_ids:
            outbox = self.root / "messages" / "outbox" / agent_id
            if not outbox.exists():
                continue
            for msg_file in outbox.glob("*.json"):
                try:
                    msg_data = json.loads(msg_file.read_text(encoding="utf-8"))
                    msg = Message.from_dict(msg_data)
                    self._route(msg)
                    msg_file.unlink()  # 消费消息
                except Exception:
                    pass

    def _route(self, msg: Message):
        """路由消息"""
        self._last_activity = time.time()
        self._msg_count += 1

        if msg.type == MessageType.VOTE:
            self._record_vote(msg)

        # v4.0: 反形式主义检查（仅对 CHALLENGE 类消息）
        if self._anti_formalism_checker and msg.type in (MessageType.CHALLENGE, MessageType.DISAGREE):
            if _ENHANCEMENT_CONFIG.get("enhancements", {}).get("anti_formalism", {}).get("enabled", True):
                content = msg.payload.get("content", "")
                result = self._anti_formalism_checker.check(content, msg.type, msg.from_agent)
                if not result.valid and result.action in ("downweight", "ignore"):
                    # 低质量回复：降权或忽略
                    return  # 不路由此消息

        # v4.0: 结构化论证 → 辩论控制器
        if self._debate and msg.type == MessageType.CHALLENGE:
            structured = msg.payload.get("structured")
            if structured:
                from conflict_detector import Argument
                arg = Argument.from_message(msg.to_dict())
                self._debate.submit_argument(msg.from_agent, msg.to_dict())

        # 回调处理
        if self.on_message:
            try:
                self.on_message(msg, self)
            except Exception:
                pass

        # 系统消息处理
        if msg.type == MessageType.SYSTEM:
            self._handle_system(msg)
        elif msg.to == MessageType.BROADCAST:
            self._relay_broadcast(msg)
        elif msg.to not in (a for a in self.agent_ids) and msg.to != "HUB":
            pass  # 未知目标，忽略
        else:
            pass  # 点对点消息，Hub 只负责转发，不需要中继

    def _handle_system(self, msg: Message):
        content = msg.payload.get("content", "")
        if "discussion_started" in content:
            self._start_discussion(msg)
        elif "discussion_ended" in content:
            self._end_discussion()
        elif "pre_discussion_ended" in content:
            self._transition_to(DiscussionPhase.DEBATE)
        # v4.0: 辩论控制器事件
        elif "pre_discussion_started" in content:
            self._init_debate_components()
            if self._debate:
                self._debate.start_pre_discussion()
        elif content.startswith("timer_expired:"):
            box_id = content.split(":", 1)[1]
            self._on_timebox_expired(box_id)
        # v4.0: 用户干预命令
        elif content.startswith("//extend "):
            self._handle_extend(content)
        elif content == "//skip":
            self._handle_skip()
        elif content == "//force-consensus":
            self._finalize_converge()

    def _start_discussion(self, msg: Message):
        """启动讨论：进入预讨论期"""
        self._disc.phase = DiscussionPhase.PRE_DISCUSSION
        self._disc.round = 1
        self._disc_start_time = time.time()
        self._disc.round_start = time.time()
        self._disc.votes = []
        self._disc.consensus_reached = False
        # v4.0: 初始化增强组件
        self._init_debate_components()
        self._broadcast_system(
            f"预讨论期开始，请各专家独立撰写观点（{self._disc.pre_discussion_minutes:.0f}分钟）"
        )
        # v4.0: 启动预讨论时间盒
        if self._timebox and _ENHANCEMENT_CONFIG.get("enhancements", {}).get("timebox_enforcer", {}).get("enabled", True):
            profile = self._get_timebox_profile()
            self._timebox.start(
                "pre_discussion",
                profile.get("pre_discussion", 300),
                "预讨论期",
            )

    def _init_debate_components(self):
        """延迟初始化增强组件"""
        _load_enhancements()
        if self._debate is None and _conflict_detector is not None:
            try:
                from debate_controller import DebateController
                self._debate = DebateController(self)
            except ImportError:
                pass
        if self._timebox is None and _timebox_enforcer is not None:
            self._timebox = _timebox_enforcer.TimeBoxEnforcer(
                on_timeout=self._on_timebox_expired
            )
        if self._anti_formalism_checker is None and _anti_formalism is not None:
            self._anti_formalism_checker = _anti_formalism.AntiFormalismChecker()
        if self._expert_weight_mgr is None and _expert_weight is not None:
            self._expert_weight_mgr = _expert_weight.ExpertWeightManager(self.root)

    def _get_timebox_profile(self) -> dict:
        """获取时间盒配置（根据任务复杂度）"""
        profiles = _ENHANCEMENT_CONFIG.get("timebox_profiles", {})
        # 简单实现：根据 round 判断复杂度
        if self._disc.pre_discussion_minutes >= 15:
            return profiles.get("complex", profiles.get("medium", {}))
        elif self._disc.pre_discussion_minutes >= 10:
            return profiles.get("medium", {})
        return profiles.get("simple", {})

    def _on_timebox_expired(self, box_id: str, label: str = ""):
        """时间盒超时处理"""
        if box_id == "pre_discussion":
            self._transition_to(DiscussionPhase.DEBATE)
        elif box_id.startswith("debate_round_"):
            if self._debate:
                self._debate.check_round_end()
        elif box_id == "consensus_check":
            self._finalize_converge()

    def _handle_extend(self, content: str):
        """处理 //extend 命令"""
        import re as _re
        match = _re.search(r'//extend\s+(\d+)(min|s)?', content)
        if match and self._timebox:
            num = int(match.group(1))
            unit = match.group(2) or "min"
            extra = num * 60 if unit == "min" else num
            # 延长当前阶段的时间盒
            active = self._timebox.active_boxes()
            if active:
                self._timebox.extend(active[0]["box_id"], extra)
                self._broadcast_system(f"时间盒已延长 {num}{unit}")

    def _handle_skip(self):
        """处理 //skip 命令"""
        if self._timebox:
            self._timebox.cancel_all()
        if self._disc.phase == DiscussionPhase.PRE_DISCUSSION:
            self._transition_to(DiscussionPhase.DEBATE)
        elif self._disc.phase == DiscussionPhase.DEBATE:
            self._transition_to(DiscussionPhase.CONVERGE)
        elif self._disc.phase == DiscussionPhase.CONVERGE:
            self._finalize_converge()

    def _transition_to(self, new_phase: DiscussionPhase):
        """切换讨论阶段"""
        old = self._disc.phase
        self._disc.phase = new_phase
        self._disc.round_start = time.time()
        if new_phase == DiscussionPhase.DEBATE:
            self._broadcast_system("预讨论期结束，进入辩论环节。可主动发起 challenge/question。")
            # v4.0: 启动辩论轮次时间盒
            if self._timebox and _ENHANCEMENT_CONFIG.get("enhancements", {}).get("timebox_enforcer", {}).get("enabled", True):
                profile = self._get_timebox_profile()
                self._timebox.start(
                    f"debate_round_{self._disc.round}",
                    profile.get("debate_round", 600),
                    f"辩论第{self._disc.round}轮",
                )
        elif new_phase == DiscussionPhase.CONVERGE:
            self._broadcast_system("进入收敛阶段，请在2分钟内完成投票。")
            # v4.0: 取消辩论时间盒，启动收敛时间盒
            if self._timebox:
                self._timebox.cancel_all()
                self._timebox.start("consensus_check", 120, "共识确认")
        elif new_phase == DiscussionPhase.CONSENSUS:
            self._broadcast_system("讨论结束，正在生成共识记录。")
            if self._timebox:
                self._timebox.cancel_all()

    def _end_discussion(self):
        self._disc.phase = DiscussionPhase.IDLE

    def _broadcast_system(self, content: str):
        self.broadcast(MessageType.SYSTEM, {"content": content})

    def _relay_broadcast(self, msg: Message):
        """将广播消息转发给所有专家（写入各自 inbox）"""
        for agent_id in self.agent_ids:
            if agent_id != msg.from_agent:
                self._write_to_inbox(agent_id, msg)

    def _record_vote(self, msg: Message):
        """记录投票"""
        self._disc.votes.append(msg.to_dict())
        self._last_activity = time.time()
        # v4.0: 辩论控制器处理投票
        if self._debate:
            stance = msg.payload.get("stance", "")
            if stance in ("agree", "disagree"):
                self._debate.submit_response(msg.from_agent, msg.payload.get("content", ""), stance)

    def _finalize_converge(self):
        """收敛完成，生成共识"""
        self._transition_to(DiscussionPhase.CONSENSUS)
        self._write_consensus()
        self._broadcast_system("discussion_ended")
        self._disc.phase = DiscussionPhase.IDLE

    def _write_consensus(self):
        """写入共识记录（v4.0: 集成 consensus_metrics + expert_weight）"""
        vote_summary: Dict[str, int] = {}
        for v in self._disc.votes:
            stance = v["payload"].get("stance", "")
            vote_summary[stance] = vote_summary.get(stance, 0) + 1

        # v4.0: 加权投票
        weighted_result = None
        if self._expert_weight_mgr and vote_summary:
            votes_dict = {v["from"]: v["payload"].get("stance", "") for v in self._disc.votes}
            weighted_result = self._expert_weight_mgr.apply_vote_weights(votes_dict)

        # v4.0: 共识度量
        consensus_level = "delivered"
        consensus_score = 1.0
        if _consensus_metrics and _ENHANCEMENT_CONFIG.get("enhancements", {}).get("consensus_metrics", {}).get("enabled", True):
            votes_map = {v["from"]: v["payload"].get("stance", "✅") for v in self._disc.votes}
            details_map = {v["from"]: {"detail": v["payload"].get("content", ""), "reason_length": len(v["payload"].get("content", ""))} for v in self._disc.votes}
            cm = _consensus_metrics.ConsensusMetrics()
            result = cm.evaluate(votes_map, vote_details=details_map)
            consensus_level = result.level
            consensus_score = result.score

        consensus_file = self.root / "consensus" / f"{self.team_id}.json"
        consensus_file.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "team_id": self.team_id,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S+08:00"),
            "total_votes": len(self._disc.votes),
            "vote_summary": vote_summary,
            "consensus_reached": len(vote_summary) == 1,
            "winning_stance": max(vote_summary, key=vote_summary.get) if vote_summary else None,
            "votes": self._disc.votes,
            # v4.0 新增字段
            "consensus_level": consensus_level,
            "consensus_score": consensus_score,
            "weighted_result": weighted_result,
        }
        atomic_write(str(consensus_file), json.dumps(data, ensure_ascii=False, indent=2))

    def _check_activity(self):
        """检查讨论超时，触发阶段转换"""
        if self._disc.phase == DiscussionPhase.IDLE:
            return
        elapsed = time.time() - self._disc_start_time
        if self._disc.phase == DiscussionPhase.PRE_DISCUSSION:
            if elapsed >= self._disc.pre_discussion_minutes * 60:
                self._transition_to(DiscussionPhase.DEBATE)
        elif self._disc.phase == DiscussionPhase.DEBATE:
            silence = time.time() - self._last_activity
            if silence >= self._disc.silence_timeout:
                self._transition_to(DiscussionPhase.CONVERGE)
        elif self._disc.phase == DiscussionPhase.CONVERGE:
            if elapsed >= self._disc.converge_timeout:
                self._finalize_converge()

    @property
    def is_active(self) -> bool:
        return self._active

    @property
    def discussion_active(self) -> bool:
        return self._discussion_active

    @property
    def msg_count(self) -> int:
        return self._msg_count


# ── 便捷函数 ────────────────────────────────────────────────────

_HUB_INSTANCE: Optional[Hub] = None


def start_hub(team_id: str, agent_ids: List[str], root: Path, **kwargs) -> Hub:
    """启动全局 Hub 实例"""
    global _HUB_INSTANCE
    if _HUB_INSTANCE and _HUB_INSTANCE.is_active:
        _HUB_INSTANCE.stop()
    _HUB_INSTANCE = Hub(team_id, agent_ids, root, **kwargs)
    _HUB_INSTANCE.start()
    return _HUB_INSTANCE


def get_hub() -> Optional[Hub]:
    return _HUB_INSTANCE


def stop_hub():
    global _HUB_INSTANCE
    if _HUB_INSTANCE:
        _HUB_INSTANCE.stop()
        _HUB_INSTANCE = None


# === HubBuffer: 消息批量写入缓冲（v3.4 合并自 hub_buffer.py） ===

class BufferedMessage:
    """缓冲消息"""
    def __init__(self, agent_id: str, msg_dict: Dict, timestamp: float):
        self.agent_id = agent_id
        self.msg_dict = msg_dict
        self.timestamp = timestamp


class HubBuffer:
    """消息批量写入缓冲器（从 hub_buffer.py 合并）

    Hub 在高频场景下（如 broadcast）每条消息都执行一次文件 I/O，
    本模块提供消息缓冲功能，将多条消息批量写入，以减少 I/O 操作次数。

    使用方式：
        from hub import HubBuffer
        buffer = HubBuffer(batch_size=10, flush_interval=1.0)
        buffer.add_message(msg_dict, agent_id)
    """

    def __init__(self, batch_size: int = 10, flush_interval: float = 1.0, outbox_root=None):
        self.batch_size = batch_size
        self.flush_interval = flush_interval
        self.outbox_root = Path(outbox_root) if outbox_root else None
        self._buffer: Dict[str, list] = defaultdict(list)
        self._lock = threading.Lock()
        self._last_flush = time.time()
        self._flush_timer = None
        self._running = False

    def add_message(self, msg_dict: Dict, agent_id: str):
        """添加消息到缓冲"""
        buffered = BufferedMessage(agent_id=agent_id, msg_dict=msg_dict, timestamp=time.time())
        with self._lock:
            self._buffer[agent_id].append(buffered)
            total = sum(len(v) for v in self._buffer.values())
            if total >= self.batch_size:
                self._flush_unlocked()
            elif time.time() - self._last_flush >= self.flush_interval:
                self._flush_unlocked()

    def _flush_unlocked(self):
        if not self._buffer:
            return
        for agent_id, messages in self._buffer.items():
            if not messages:
                continue
            outbox_dir = self.outbox_root / agent_id if self.outbox_root else None
            if outbox_dir:
                outbox_dir.mkdir(parents=True, exist_ok=True)
            for buffered in messages:
                if outbox_dir:
                    outbox_path = outbox_dir / f"{buffered.msg_dict.get('msg_id', 'unknown')}.json"
                    with open(outbox_path, 'w', encoding='utf-8') as f:
                        json.dump(buffered.msg_dict, f, ensure_ascii=False, indent=2)
        self._buffer.clear()
        self._last_flush = time.time()

    def flush(self):
        """手动 flush"""
        with self._lock:
            self._flush_unlocked()

    def start(self):
        """启动定时 flush"""
        self._running = True
        self._schedule_flush()

    def stop(self):
        """停止定时 flush"""
        self._running = False
        if self._flush_timer:
            self._flush_timer.cancel()
            self._flush_timer = None
        self.flush()

    def _schedule_flush(self):
        if not self._running:
            return
        self._flush_timer = threading.Timer(self.flush_interval, self._on_flush_timer)
        self._flush_timer.daemon = True
        self._flush_timer.start()

    def _on_flush_timer(self):
        with self._lock:
            if time.time() - self._last_flush >= self.flush_interval:
                self._flush_unlocked()
        if self._running:
            self._schedule_flush()

    def __len__(self):
        with self._lock:
            return sum(len(v) for v in self._buffer.values())

    def is_empty(self) -> bool:
        return len(self) == 0