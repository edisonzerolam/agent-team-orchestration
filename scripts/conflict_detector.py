"""conflict-detector.py — P0 冲突检测器（关键词+规则，无 NLP 依赖）


# [中文说明]
# 本文件：conflict_detector.py
# 用途：OpenClaw 框架的核心脚本之一
# 详细文档：请阅读对应的 SKILL.md 和 references/

Usage:
    from conflict_detector import ConflictDetector, Conflict, Argument
    
    detector = ConflictDetector()
    conflicts = detector.detect(arguments)
"""

import re
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple
from enum import Enum


class Severity(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass
class Argument:
    """结构化论证"""
    argument_id: str
    claim: str
    evidence: List[str] = field(default_factory=list)
    confidence: float = 0.5
    domain: str = "general"
    counter_to: Optional[str] = None
    agent_id: str = ""

    @classmethod
    def from_message(cls, msg_dict: dict) -> "Argument":
        """从消息字典创建 Argument（向后兼容旧格式）"""
        payload = msg_dict.get("payload", {})
        structured = payload.get("structured")

        if structured and "claim" in structured:
            return cls(
                argument_id=msg_dict.get("msg_id", ""),
                claim=structured["claim"],
                evidence=structured.get("evidence", []),
                confidence=structured.get("confidence", 0.5),
                domain=structured.get("domain", "general"),
                counter_to=structured.get("counter_to"),
                agent_id=msg_dict.get("from", ""),
            )

        # Fallback: 从 content 解析
        return cls(
            argument_id=msg_dict.get("msg_id", ""),
            claim=payload.get("subject", payload.get("content", ""))[:200],
            evidence=[],
            confidence=0.3,
            domain="general",
            agent_id=msg_dict.get("from", ""),
        )


@dataclass
class Conflict:
    """检测到的冲突"""
    conflict_id: str = ""
    parties: List[str] = field(default_factory=list)  # 冲突方的 claim
    agent_ids: List[str] = field(default_factory=list)  # 冲突方的 agent_id
    issue: str = ""
    severity: Severity = Severity.MEDIUM
    domain: str = ""

    def to_dict(self) -> dict:
        return {
            "conflict_id": self.conflict_id,
            "parties": self.parties,
            "agent_ids": self.agent_ids,
            "issue": self.issue,
            "severity": self.severity.value,
            "domain": self.domain,
        }


class ConflictDetector:
    """P0 冲突检测器 — 关键词 + 规则（零 NLP 依赖）"""

    # 对立词对
    OPPOSITE_PAIRS = [
        ("看好", "看空"), ("乐观", "悲观"), ("推荐", "不推荐"),
        ("可行", "不可行"), ("风险低", "风险高"), ("收益高", "收益低"),
        ("增加", "削减"), ("支持", "反对"), ("同意", "不同意"),
        ("快速", "稳健"), ("创新", "保守"), ("进攻", "防守"),
        ("立即执行", "暂缓执行"), ("应该做", "不应该做"),
        ("正面", "负面"), ("积极", "消极"),
    ]

    # 强度修饰词（增强冲突判定）
    INTENSIFIERS = [
        "明显", "显著", "强烈", "绝对", "完全", "肯定",
        "毫无疑问", "毫无疑问", "显然", "明确",
    ]

    def __init__(self, custom_opposites: Optional[List[Tuple[str, str]]] = None):
        self.opposite_pairs = custom_opposites or self.OPPOSITE_PAIRS

    def detect(self, arguments: List[Argument]) -> List[Conflict]:
        """检测论点间的冲突"""
        if len(arguments) < 2:
            return []

        conflicts: List[Conflict] = []
        conflict_counter = 0

        for i, a1 in enumerate(arguments):
            for a2 in arguments[i + 1:]:
                # 跳过同一 agent 的论点
                if a1.agent_id and a1.agent_id == a2.agent_id:
                    continue

                detected = self._check_conflict(a1, a2)
                for conflict in detected:
                    conflict_counter += 1
                    conflict.conflict_id = f"conflict-{conflict_counter}"
                    conflicts.append(conflict)

        return self._deduplicate(conflicts)

    def _check_conflict(self, a1: Argument, a2: Argument) -> List[Conflict]:
        """检查两个论点间的冲突"""
        conflicts = []

        # 规则1: 显式反驳关系
        if a1.counter_to == a2.argument_id or a2.counter_to == a1.argument_id:
            conflicts.append(Conflict(
                parties=[a1.claim, a2.claim],
                agent_ids=[a1.agent_id, a2.agent_id],
                issue="显式反驳关系",
                severity=Severity.HIGH,
                domain=a1.domain if a1.domain == a2.domain else "",
            ))

        # 规则2: 同领域 + 置信度差异大
        if a1.domain == a2.domain and a1.domain != "general":
            diff = abs(a1.confidence - a2.confidence)
            if diff > 0.4:
                conflicts.append(Conflict(
                    parties=[a1.claim, a2.claim],
                    agent_ids=[a1.agent_id, a2.agent_id],
                    issue=f"同领域置信度差异: {a1.confidence:.2f} vs {a2.confidence:.2f} (Δ={diff:.2f})",
                    severity=Severity.HIGH if diff > 0.6 else Severity.MEDIUM,
                    domain=a1.domain,
                ))

        # 规则3: 关键词对立
        c1 = a1.claim.lower()
        c2 = a2.claim.lower()
        for pos, neg in self.opposite_pairs:
            if (pos in c1 and neg in c2) or (neg in c1 and pos in c2):
                # 检查是否有强度修饰词
                has_intensifier = any(
                    intensifier in c1 or intensifier in c2
                    for intensifier in self.INTENSIFIERS
                )
                conflicts.append(Conflict(
                    parties=[a1.claim, a2.claim],
                    agent_ids=[a1.agent_id, a2.agent_id],
                    issue=f"观点对立: {pos} vs {neg}",
                    severity=Severity.HIGH if has_intensifier else Severity.MEDIUM,
                    domain=a1.domain if a1.domain == a2.domain else "",
                ))

        # 规则4: 证据矛盾（同一证据，不同结论）
        if a1.evidence and a2.evidence:
            common = set(a1.evidence) & set(a2.evidence)
            if common and a1.domain == a2.domain:
                conflicts.append(Conflict(
                    parties=[a1.claim, a2.claim],
                    agent_ids=[a1.agent_id, a2.agent_id],
                    issue=f"引用相同证据但结论不同: {list(common)[:2]}",
                    severity=Severity.MEDIUM,
                    domain=a1.domain,
                ))

        return conflicts

    def _deduplicate(self, conflicts: List[Conflict]) -> List[Conflict]:
        """去重（同一对 agent 只保留最高严重度）"""
        seen: Dict[str, Conflict] = {}
        for c in conflicts:
            key = tuple(sorted(c.agent_ids))
            key_str = str(key)
            if key_str not in seen or c.severity.value > seen[key_str].severity.value:
                seen[key_str] = c
        return list(seen.values())

    def get_debate_issues(self, conflicts: List[Conflict]) -> List[dict]:
        """将冲突转化为辩论议题"""
        issues = []
        for c in sorted(conflicts, key=lambda x: {"high": 0, "medium": 1, "low": 2}[x.severity.value]):
            issues.append({
                "conflict_id": c.conflict_id,
                "issue": c.issue,
                "parties": c.parties,
                "agent_ids": c.agent_ids,
                "severity": c.severity.value,
                "instruction": f"请 {', '.join(c.agent_ids)} 就以下议题进行辩论: {c.issue}",
            })
        return issues


# ── 便捷函数 ─────────────────────────────────────────────

def detect_conflicts_from_messages(messages: List[dict]) -> List[Conflict]:
    """从消息列表检测冲突（便捷入口）"""
    arguments = [Argument.from_message(m) for m in messages]
    detector = ConflictDetector()
    return detector.detect(arguments)


if __name__ == "__main__":
    # 测试
    args = [
        Argument("a1", "当前PE为35倍，高于历史中位数25倍", ["consensus.md §2.1"], 0.85, "估值", agent_id="analyst-1"),
        Argument("a2", "考虑到增长潜力，35倍PE是合理的", ["growth.md §3"], 0.7, "估值", agent_id="analyst-2"),
        Argument("a3", "建议立即执行买入", agent_id="trader-1"),
        Argument("a4", "建议暂缓执行，等待回调", agent_id="trader-2"),
    ]
    detector = ConflictDetector()
    conflicts = detector.detect(args)
    for c in conflicts:
        print(f"[{c.severity.value}] {c.conflict_id}: {c.issue}")
        print(f"  方: {c.agent_ids}")
