"""messages.py - 专家消息工具（写 outbox / 读 inbox）


# [中文说明]
# 本文件：messages.py
# 用途：OpenClaw 框架的核心脚本之一
# 详细文档：请阅读对应的 SKILL.md 和 references/

专家 subagent 在其 spawn prompt 中会包含以下函数的简化版。
这里提供 Python 模块版，供独立脚本使用。

使用方式（专家侧）：
    from messages import MessageBus
    bus = MessageBus(agent_id="agent-1", root=TEAM_BRAIN_ROOT)
    bus.send_to("agent-2", "question", subject="...", content="...")
    bus.poll_inbox()  # 返回新消息列表
"""

import json
import os
import sys
import time
import uuid
import importlib.util
from pathlib import Path
from typing import List, Dict, Optional
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

_spec = importlib.util.spec_from_file_location("atomic_write", str(Path(__file__).parent / "atomic-write.py"))
_aw = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_aw)
atomic_write = _aw.atomic_write


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
    to: str
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


class MessageBus:
    """专家侧消息总线 — 写 outbox / 读 inbox"""

    def __init__(self, agent_id: str, root: Path, poll_interval: float = 10.0):
        self.agent_id = agent_id
        self.root = Path(root)
        self.poll_interval = poll_interval
        self._last_poll = 0.0

    def _now(self) -> str:
        return time.strftime("%Y-%m-%dT%H:%M:%S+08:00")

    def _new_msg_id(self) -> str:
        return f"msg-{time.strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6]}"

    # ── 发送 ────────────────────────────────────────────────────

    def send_to(self, agent_id: str, msg_type: str, payload: Dict) -> str:
        msg = Message(
            msg_id=self._new_msg_id(),
            type=msg_type,
            from_agent=self.agent_id,
            to=agent_id,
            payload=payload,
            timestamp=self._now(),
        )
        return self._write_outbox(msg)

    def broadcast(self, msg_type: str, payload: Dict) -> str:
        msg = Message(
            msg_id=self._new_msg_id(),
            type=msg_type,
            from_agent=self.agent_id,
            to="BROADCAST",
            payload=payload,
            timestamp=self._now(),
        )
        return self._write_outbox(msg)

    def send_question(self, to_agent: str, subject: str, content: str, confidence: float = 0.8) -> str:
        return self.send_to(to_agent, "question", {
            "subject": subject,
            "content": content,
            "confidence": confidence,
        })

    def send_challenge(self, to_agent: str, subject: str, content: str, evidence: List[str] = None) -> str:
        return self.send_to(to_agent, "challenge", {
            "subject": subject,
            "content": content,
            "evidence": evidence or [],
        })

    def send_answer(self, to_agent: str, subject: str, content: str, reply_to: str = None) -> str:
        return self.send_to(to_agent, "answer", {
            "subject": subject,
            "content": content,
            "reply_to": reply_to,
        })

    def send_agree(self, subject: str, content: str = "") -> str:
        return self.broadcast("agree", {"subject": subject, "content": content})

    def send_disagree(self, subject: str, content: str, evidence: List[str] = None, reply_to: str = None) -> str:
        return self.broadcast("disagree", {
            "subject": subject,
            "content": content,
            "evidence": evidence or [],
            "reply_to": reply_to,
        })

    def _write_outbox(self, msg: Message) -> str:
        outbox = self.root / "messages" / "outbox" / self.agent_id
        outbox.mkdir(parents=True, exist_ok=True)
        path = outbox / f"{msg.msg_id}.json"
        atomic_write(str(path), json.dumps(msg.to_dict(), ensure_ascii=False, indent=2))
        return msg.msg_id

    # ── 接收 ────────────────────────────────────────────────────

    def poll_inbox(self, force: bool = False) -> List[Message]:
        """轮询收件箱，返回新消息列表"""
        if not force and (time.time() - self._last_poll < self.poll_interval):
            return []
        self._last_poll = time.time()
        inbox = self.root / "messages" / "inbox" / self.agent_id
        if not inbox.exists():
            return []
        messages = []
        for msg_file in sorted(inbox.glob("*.json")):
            try:
                msg_data = json.loads(msg_file.read_text(encoding="utf-8"))
                messages.append(Message.from_dict(msg_data))
                msg_file.unlink()  # 消费
            except Exception:
                pass
        return messages

    def has_messages(self) -> bool:
        """检查是否有新消息（不消费）"""
        inbox = self.root / "messages" / "inbox" / self.agent_id
        return inbox.exists() and any(inbox.glob("*.json"))

    def peek_inbox(self) -> List[Message]:
        """查看收件箱（不消费）"""
        inbox = self.root / "messages" / "inbox" / self.agent_id
        if not inbox.exists():
            return []
        messages = []
        for msg_file in sorted(inbox.glob("*.json")):
            try:
                msg_data = json.loads(msg_file.read_text(encoding="utf-8"))
                messages.append(Message.from_dict(msg_data))
            except Exception:
                pass
        return messages

    # ── 便捷 ────────────────────────────────────────────────────

    def notify_analysis_done(self, summary: str, findings_path: str = None) -> str:
        """分析完成后通知 Hub（通过特殊 outbox 路径，Hub 感知）"""
        return self.send_to("HUB", "system", {
            "content": "analysis_done",
            "summary": summary,
            "findings_path": findings_path or "",
        })