"""consensus-metrics.py — P2 共识度量工具

Usage:
    from consensus_metrics import ConsensusMetrics
    
    metrics = ConsensusMetrics()
    result = metrics.evaluate(votes, quality_report)
    # {"level": "strong", "score": 0.85, "action": "deliver"}
"""

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from enum import Enum


class ConsensusLevel(str, Enum):
    STRONG = "strong"         # score >= 0.8, 全员✅+充分论证
    MODERATE = "moderate"     # 0.6 <= score < 0.8
    WEAK = "weak"             # 0.4 <= score < 0.6
    FAILED = "failed"         # score < 0.4 或有❌


@dataclass
class ConsensusResult:
    """共识评估结果"""
    level: str
    score: float
    action: str
    details: Dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "level": self.level,
            "score": self.score,
            "action": self.action,
            **self.details,
        }


class ConsensusMetrics:
    """共识度量评估器"""

    # 评分权重
    WEIGHTS = {
        "agreement_ratio": 0.3,    # 一致率
        "reasoning_depth": 0.3,    # 论证深度
        "citation_rate": 0.2,      # 引用率
        "response_rate": 0.2,      # 响应率
    }

    def evaluate(
        self,
        votes: Dict[str, str],
        quality_report: Optional[dict] = None,
        vote_details: Optional[Dict[str, dict]] = None,
    ) -> ConsensusResult:
        """
        评估共识质量

        Args:
            votes: {agent_id: "✅"/"⚠️"/"❌"}
            quality_report: 讨论质量报告（来自 discussion-quality.py）
            vote_details: {agent_id: {"vote": ..., "detail": ..., "reason_length": ...}}

        Returns:
            ConsensusResult
        """
        if not votes:
            return ConsensusResult(
                level=ConsensusLevel.FAILED.value,
                score=0.0,
                action="return",
                details={"reason": "no_votes"},
            )

        # 检查是否有❌
        has_objection = any(v == "❌" for v in votes.values())
        if has_objection:
            return ConsensusResult(
                level=ConsensusLevel.FAILED.value,
                score=0.0,
                action="return",
                details={"reason": "has_objection", "objectors": [k for k, v in votes.items() if v == "❌"]},
            )

        # 计算各维度分数
        scores = {}

        # 1. 一致率
        agree_count = sum(1 for v in votes.values() if v == "✅")
        concern_count = sum(1 for v in votes.values() if v == "⚠️")
        scores["agreement_ratio"] = agree_count / len(votes)

        # 2. 论证深度（基于理由长度）
        if vote_details:
            reason_lengths = []
            for detail in vote_details.values():
                reason_len = detail.get("reason_length", len(detail.get("detail", "")))
                reason_lengths.append(reason_len)
            avg_reason_len = sum(reason_lengths) / max(len(reason_lengths), 1)
            # 50字符以上算充分
            scores["reasoning_depth"] = min(1.0, avg_reason_len / 80)
        elif quality_report:
            scores["reasoning_depth"] = min(1.0, quality_report.get("avg_length", 0) / 80)
        else:
            scores["reasoning_depth"] = 0.5  # 默认中等

        # 3. 引用率
        if vote_details:
            cited = sum(1 for d in vote_details.values()
                       if re.search(r'\[|§|第\d+段|第\d+页', d.get("detail", "")))
            scores["citation_rate"] = cited / max(len(vote_details), 1)
        elif quality_report:
            scores["citation_rate"] = quality_report.get("citation_rate", 0.3)
        else:
            scores["citation_rate"] = 0.3

        # 4. 响应率
        responded = sum(1 for v in votes.values() if v is not None)
        scores["response_rate"] = responded / len(votes)

        # 加权总分
        total_score = sum(
            scores[dim] * weight
            for dim, weight in self.WEIGHTS.items()
        )

        # 关注点惩罚
        if concern_count > 0:
            concern_penalty = concern_count / len(votes) * 0.2
            total_score = max(0.0, total_score - concern_penalty)

        # 判定等级
        level, action = self._classify(total_score, has_objection, concern_count)

        return ConsensusResult(
            level=level.value,
            score=round(total_score, 3),
            action=action,
            details={
                "dimension_scores": {k: round(v, 3) for k, v in scores.items()},
                "agree_count": agree_count,
                "concern_count": concern_count,
                "total_experts": len(votes),
            },
        )

    def _classify(self, score: float, has_objection: bool, concern_count: int):
        """根据分数判定等级和动作"""
        if has_objection:
            return ConsensusLevel.FAILED, "return"
        if score >= 0.8:
            return ConsensusLevel.STRONG, "deliver"
        elif score >= 0.6:
            return ConsensusLevel.MODERATE, "deliver_with_concerns" if concern_count > 0 else "deliver"
        elif score >= 0.4:
            return ConsensusLevel.WEAK, "return_for_improvement"
        else:
            return ConsensusLevel.FAILED, "return"

    def merge_with_synthesis(self, synthesis_status: str, metrics_result: ConsensusResult) -> str:
        """与 synthesis-check.py 的结果合并（使用现有状态）"""
        # 不新增状态，映射到现有状态
        if synthesis_status == "returned":
            return "returned"

        if metrics_result.level == ConsensusLevel.WEAK.value:
            # 弱共识 → 附带说明交付（映射到 delivered_with_concerns）
            return "delivered_with_concerns"

        if synthesis_status == "delivered_with_concerns":
            return "delivered_with_concerns"

        return synthesis_status


if __name__ == "__main__":
    # 测试
    metrics = ConsensusMetrics()

    # 场景1: 强共识
    votes1 = {"a1": "✅", "a2": "✅", "a3": "✅"}
    details1 = {
        "a1": {"detail": "分析充分，[见consensus.md §2.1]", "reason_length": 50},
        "a2": {"detail": "同意，数据支持结论。[见findings/估值.md]", "reason_length": 45},
        "a3": {"detail": "论证完整，引用了3处数据", "reason_length": 40},
    }
    r1 = metrics.evaluate(votes1, vote_details=details1)
    print(f"强共识: {r1.to_dict()}")

    # 场景2: 弱共识
    votes2 = {"a1": "✅", "a2": "✅", "a3": "✅"}
    details2 = {
        "a1": {"detail": "同意", "reason_length": 2},
        "a2": {"detail": "可以", "reason_length": 2},
        "a3": {"detail": "没问题", "reason_length": 3},
    }
    r2 = metrics.evaluate(votes2, vote_details=details2)
    print(f"弱共识: {r2.to_dict()}")

    # 场景3: 有反对
    votes3 = {"a1": "✅", "a2": "❌", "a3": "⚠️"}
    r3 = metrics.evaluate(votes3)
    print(f"有反对: {r3.to_dict()}")
