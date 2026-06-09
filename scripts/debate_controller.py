"""debate-controller.py — P1 辩论控制器（嵌入 Hub，管理辩论轮次）


# [中文说明]
# 本文件：debate_controller.py
# 用途：OpenClaw 框架的核心脚本之一
# 详细文档：请阅读对应的 SKILL.md 和 references/

Usage:
    from debate_controller import DebateController
    
    controller = DebateController(hub)
    controller.start_pre_discussion()
    controller.submit_argument(agent_id, argument)
    # ... 辩论自动推进
"""

import json
import time
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Callable, TYPE_CHECKING
from pathlib import Path

if TYPE_CHECKING:
    from hub import Hub, Message

# 导入冲突检测
import importlib.util
import sys
from pathlib import Path as _Path

_SCRIPT_DIR = _Path(__file__).parent
_spec = importlib.util.spec_from_file_location("conflict_detector", str(_SCRIPT_DIR / "conflict_detector.py"))
_cd = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_cd)
ConflictDetector = _cd.ConflictDetector
Argument = _cd.Argument
Conflict = _cd.Conflict

# 导入配置
_config_path = _SCRIPT_DIR / "enhancement_config.json"
if _config_path.exists():
    with open(_config_path, encoding="utf-8") as _f:
        _CONFIG = json.load(_f)
else:
    _CONFIG = {}

_DEBATE_CONFIG = _CONFIG.get("debate", {})
_MAX_ROUNDS = _DEBATE_CONFIG.get("max_rounds", 3)
_MAX_MSGS_PER_ROUND = _DEBATE_CONFIG.get("max_messages_per_round", 10)


@dataclass
class DebateRound:
    """单轮辩论"""
    round_num: int
    start_time: float = 0.0
    arguments: Dict[str, Argument] = field(default_factory=dict)
    challenges: List[dict] = field(default_factory=list)
    responses: List[dict] = field(default_factory=list)
    end_time: float = 0.0


class DebateController:
    """辩论控制器 — 嵌入 Hub，管理辩论轮次和冲突驱动的讨论"""

    def __init__(self, hub: "Hub"):
        self.hub = hub
        self.rounds: List[DebateRound] = []
        self.current_round: Optional[DebateRound] = None
        self.arguments: Dict[str, Argument] = {}
        self.conflicts: List[Conflict] = []
        self.detector = ConflictDetector()
        self._debate_active = False
        self._pre_discussion_done = False

    def start_pre_discussion(self):
        """启动独立意见收集（预讨论期）"""
        self._pre_discussion_done = False
        self.arguments.clear()
        self.conflicts.clear()
        self.rounds.clear()

        self.hub.broadcast("system", {
            "content": "pre_discussion_started",
            "instruction": "请各位专家独立撰写观点，提交到 outbox。格式：{'subject': '...', 'content': '...', 'structured': {'claim': '...', 'evidence': [...], 'confidence': 0.x, 'domain': '...'}}",
            "timeout_minutes": self.hub._disc.pre_discussion_minutes,
        })

    def submit_argument(self, agent_id: str, msg_dict: dict) -> bool:
        """专家提交论点（预讨论阶段收集，辩论阶段作为挑战）"""
        argument = Argument.from_message(msg_dict)
        argument.agent_id = agent_id

        if not self._pre_discussion_done:
            # 预讨论阶段：收集论点
            self.arguments[agent_id] = argument
            # 检查是否所有专家都已提交
            if len(self.arguments) >= len(self.hub.agent_ids):
                self._on_pre_discussion_complete()
            return True
        else:
            # 辩论阶段：作为挑战/回应处理
            if self.current_round:
                self.current_round.arguments[agent_id] = argument
            return True

    def _on_pre_discussion_complete(self):
        """预讨论期结束，检测冲突"""
        self._pre_discussion_done = True

        # 冲突检测
        args_list = list(self.arguments.values())
        self.conflicts = self.detector.detect(args_list)

        if not self.conflicts:
            # 无冲突：直接进入收敛阶段
            self.hub.broadcast("system", {
                "content": "no_conflict_detected",
                "message": "所有专家意见一致，无需辩论，直接进入共识确认。",
            })
            self.hub._transition_to("converge")
            return

        # 有冲突：启动辩论
        议题 = self.detector.get辩论议题(self.conflicts)
        self.hub.broadcast("system", {
            "content": "debate_started",
            "conflict_count": len(self.conflicts),
            "议题": 议题,
            "max_rounds": _MAX_ROUNDS,
        })
        self._start_round(1)

    def _start_round(self, round_num: int):
        """开始新一轮辩论"""
        self.current_round = DebateRound(
            round_num=round_num,
            start_time=time.time(),
        )
        self.rounds.append(self.current_round)
        self._debate_active = True

        # 通知专家
        self.hub.broadcast("system", {
            "content": "round_start",
            "round": round_num,
            "max_rounds": _MAX_ROUNDS,
            "instruction": f"辩论第{round_num}轮。请对上述议题发表观点，可发起 challenge 或 agree/disagree。",
        })

    def submit_challenge(self, from_agent: str, to_agent: str, content: str, structured: dict = None):
        """提交挑战"""
        if not self.current_round or not self._debate_active:
            return

        challenge = {
            "from": from_agent,
            "to": to_agent,
            "content": content,
            "structured": structured,
            "timestamp": time.time(),
        }
        self.current_round.challenges.append(challenge)

        # 转发给被挑战者
        payload = {
            "subject": f"挑战来自 {from_agent}",
            "content": content,
        }
        if structured:
            payload["structured"] = structured

        self.hub.send_to(to_agent, "challenge", payload, from_agent=from_agent)

    def submit_response(self, agent_id: str, content: str, stance: str = "defense"):
        """提交回应"""
        if not self.current_round:
            return

        response = {
            "agent_id": agent_id,
            "content": content,
            "stance": stance,
            "timestamp": time.time(),
        }
        self.current_round.responses.append(response)

    def check_round_end(self) -> bool:
        """检查当前轮是否应结束"""
        if not self.current_round or not self._debate_active:
            return False

        # 条件1: 达到最大轮次
        if self.current_round.round_num >= _MAX_ROUNDS:
            self._adjudicate()
            return True

        # 条件2: 本轮消息数达到上限
        total_msgs = len(self.current_round.challenges) + len(self.current_round.responses)
        if total_msgs >= _MAX_MSGS_PER_ROUND:
            self._advance_round()
            return False

        # 条件3: 无新活动（由 TimeBoxEnforcer 管理超时）
        # 由外部超时触发

        return False

    def _advance_round(self):
        """进入下一轮"""
        next_round = self.current_round.round_num + 1
        self.current_round.end_time = time.time()
        self._start_round(next_round)

    def _adjudicate(self):
        """裁决：辩论结束，生成共识"""
        self._debate_active = False
        if self.current_round:
            self.current_round.end_time = time.time()

        # 统计辩论结果
        debate_summary = self._summarize_debate()

        self.hub.broadcast("system", {
            "content": "debate_ended",
            "total_rounds": len(self.rounds),
            "summary": debate_summary,
        })

        # 进入收敛阶段
        self.hub._transition_to("converge")

    def _summarize_debate(self) -> dict:
        """总结辩论"""
        total_challenges = sum(len(r.challenges) for r in self.rounds)
        total_responses = sum(len(r.responses) for r in self.rounds)
        return {
            "total_rounds": len(self.rounds),
            "total_challenges": total_challenges,
            "total_responses": total_responses,
            "conflicts_detected": len(self.conflicts),
            "conflicts_addressed": self._count_addressed_conflicts(),
        }

    def _count_addressed_conflicts(self) -> int:
        """统计已讨论的冲突数"""
        discussed = set()
        for r in self.rounds:
            for c in r.challenges:
                content = c.get("content", "")
                for conflict in self.conflicts:
                    if conflict.issue in content:
                        discussed.add(conflict.conflict_id)
        return len(discussed)

    def get_status(self) -> dict:
        """获取辩论状态"""
        return {
            "debate_active": self._debate_active,
            "pre_discussion_done": self._pre_discussion_done,
            "current_round": self.current_round.round_num if self.current_round else 0,
            "total_rounds": len(self.rounds),
            "arguments_count": len(self.arguments),
            "conflicts_count": len(self.conflicts),
        }

    def reset(self):
        """重置辩论状态"""
        self.rounds.clear()
        self.current_round = None
        self.arguments.clear()
        self.conflicts.clear()
        self._debate_active = False
        self._pre_discussion_done = False
