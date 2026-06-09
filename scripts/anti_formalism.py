"""anti-formalism.py — P0 反形式主义检查器（2维：长度+引用）

Usage:
    from anti_formalism import AntiFormalismChecker
    
    checker = AntiFormalismChecker()
    result = checker.check("同意", "✅")
    # {"valid": False, "issues": [{"type": "filler", ...}], "action": "reject_retry"}
"""

import re
from dataclasses import dataclass, field
from typing import List, Dict, Optional
from enum import Enum


class IssueType(str, Enum):
    TOO_SHORT = "too_short"
    NO_CITATION = "no_citation"
    FILLER = "filler"
    COPY_PASTE = "copy_paste"


class Action(str, Enum):
    ACCEPT = "accept"
    REJECT_RETRY = "reject_retry"
    DOWNWEIGHT = "downweight"
    IGNORE = "ignore"


@dataclass
class CheckResult:
    """检查结果"""
    valid: bool
    issues: List[dict] = field(default_factory=list)
    action: str = Action.ACCEPT.value
    score: float = 1.0  # 0-1, 1=完全合规

    def to_dict(self) -> dict:
        return {
            "valid": self.valid,
            "issues": self.issues,
            "action": self.action,
            "score": self.score,
        }


class AntiFormalismChecker:
    """反形式主义检查器（简化版：2维 + 填充词检测）"""

    # 填充词/无内容回复
    FILLER_PATTERNS = [
        "同意", "好的", "收到", "知道了", "没问题", "可以", "行",
        "同上", "无异议", "没有意见", "赞同", "认可", "OK", "ok",
        "👍", "✅", "确认", "明白", "了解",
    ]

    # 引用模式
    CITATION_PATTERNS = [
        r'\[[^\]]+\]',        # [段落引用]
        r'§\d+',              # §2.1
        r'第\d+段',           # 第3段
        r'第\d+页',           # 第5页
        r'L\d+-\d+',          # L15-20 (行号)
        r'第\d+行',           # 第15行
        r'findings/.+\.md',   # findings/xxx.md
        r'consensus\.md',     # consensus.md
    ]

    # 复制粘贴检测：多个 agent 回复完全相同
    def __init__(self, min_length: int = 50):
        self.min_length = min_length
        self._recent_replies: Dict[str, str] = {}  # agent_id -> last reply

    def check(self, text: str, msg_type: str = "", agent_id: str = "") -> CheckResult:
        """
        检查回复是否合规

        Args:
            text: 回复内容
            msg_type: 消息类型 (✅/⚠️/❌/challenge/...)
            agent_id: 专家 ID（用于复制粘贴检测）

        Returns:
            CheckResult
        """
        issues = []
        text_stripped = text.strip()

        # 维度1: 长度检查
        if len(text_stripped) < self.min_length:
            issues.append({
                "type": IssueType.TOO_SHORT.value,
                "detail": f"仅{len(text_stripped)}字符，需≥{self.min_length}",
                "severity": "high",
            })

        # 维度2: 引用检查（仅对 ⚠️/❌ 要求）
        if msg_type in ("⚠️", "❌"):
            has_citation = any(
                re.search(pattern, text)
                for pattern in self.CITATION_PATTERNS
            )
            if not has_citation:
                issues.append({
                    "type": IssueType.NO_CITATION.value,
                    "detail": "⚠️/❌ 必须引用报告段落或具体数据",
                    "severity": "high",
                })

        # 填充词检测
        if text_stripped in self.FILLER_PATTERNS:
            issues.append({
                "type": IssueType.FILLER.value,
                "detail": f"纯填充词「{text_stripped}」，无实质内容",
                "severity": "high",
            })

        # 复制粘贴检测
        if agent_id and agent_id in self._recent_replies:
            if text_stripped == self._recent_replies[agent_id]:
                issues.append({
                    "type": IssueType.COPY_PASTE.value,
                    "detail": "与上次回复完全相同，疑似复制粘贴",
                    "severity": "medium",
                })

        # 记录本次回复
        if agent_id:
            self._recent_replies[agent_id] = text_stripped

        # 计算评分
        score = 1.0
        if issues:
            high_count = sum(1 for i in issues if i["severity"] == "high")
            score = max(0.0, 1.0 - high_count * 0.3 - len(issues) * 0.1)

        # 确定动作
        action = Action.ACCEPT.value
        if issues:
            if score <= 0.3:
                action = Action.IGNORE.value
            elif score <= 0.6:
                action = Action.DOWNWEIGHT.value
            else:
                action = Action.REJECT_RETRY.value

        return CheckResult(
            valid=len(issues) == 0,
            issues=issues,
            action=action,
            score=score,
        )

    def reset(self):
        """重置历史记录"""
        self._recent_replies.clear()


# ── 惩罚权重映射 ─────────────────────────────────────────

PENALTY_WEIGHTS = {
    Action.ACCEPT.value: 1.0,
    Action.REJECT_RETRY.value: 1.0,   # 重填后恢复
    Action.DOWNWEIGHT.value: 0.5,     # 降权
    Action.IGNORE.value: 0.0,         # 忽略
}


def get_vote_weight(action: str) -> float:
    """根据惩罚动作获取投票权重"""
    return PENALTY_WEIGHTS.get(action, 1.0)


if __name__ == "__main__":
    # 测试
    checker = AntiFormalismChecker()

    tests = [
        ("同意", "✅", "agent-1"),
        ("这是一段足够长的回复，包含了具体的分析和建议。根据报告第3段的内容，我认为...", "✅", "agent-2"),
        ("我认为当前估值偏高。[见consensus.md §2.1] PE为35倍，高于历史中位数25倍。", "❌", "agent-3"),
        ("不赞同", "❌", "agent-4"),
        ("", "⚠️", "agent-5"),
    ]

    for text, msg_type, agent_id in tests:
        result = checker.check(text, msg_type, agent_id)
        print(f"[{msg_type}] {agent_id}: {text[:30]}...")
        print(f"  valid={result.valid}, action={result.action}, score={result.score:.2f}")
        if result.issues:
            for issue in result.issues:
                print(f"  ⚠️ {issue['type']}: {issue['detail']}")
        print()
