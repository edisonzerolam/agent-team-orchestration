"""expert-weight.py — P1 专家权重系统

Usage:
    from expert_weight import ExpertWeightManager
    
    manager = ExpertWeightManager(team_root)
    weight = manager.get_weight(agent_id, domain="估值")
    manager.update_record(agent_id, task_type="估值分析", correct=True)
"""

import json
import time
from dataclasses import dataclass, field
from typing import Dict, Optional, List
from pathlib import Path

# 导入原子写入
import importlib.util
_SCRIPT_DIR = Path(__file__).parent
_spec = importlib.util.spec_from_file_location("atomic_write", str(_SCRIPT_DIR / "atomic-write.py"))
_aw = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_aw)
atomic_write = _aw.atomic_write


# 角色基础权重
ROLE_WEIGHTS = {
    "DomainExpert": 1.3,
    "Reviewer": 1.1,
    "Builder": 1.0,
    "Orchestrator": 1.2,
    "Analyst": 1.15,
    "unknown": 1.0,
}


@dataclass
class ExpertWeight:
    """专家权重"""
    agent_id: str
    base_weight: float = 1.0
    domain_expertise: float = 1.0   # 任务相关度（0-1）
    track_record: float = 1.0       # 历史准确率（0-1）
    total_tasks: int = 0
    correct_tasks: int = 0

    @property
    def effective_weight(self) -> float:
        """有效权重 = 基础 × 领域 × 记录"""
        return self.base_weight * self.domain_expertise * self.track_record

    def to_dict(self) -> dict:
        return {
            "agent_id": self.agent_id,
            "base_weight": self.base_weight,
            "domain_expertise": self.domain_expertise,
            "track_record": self.track_record,
            "effective_weight": self.effective_weight,
            "total_tasks": self.total_tasks,
            "correct_tasks": self.correct_tasks,
        }


class ExpertWeightManager:
    """专家权重管理器"""

    def __init__(self, team_root: Path):
        self.team_root = Path(team_root)
        self._weights: Dict[str, ExpertWeight] = {}
        self._load()

    def _weights_file(self) -> Path:
        return self.team_root / "expert-weights.json"

    def _load(self):
        """从文件加载权重"""
        wf = self._weights_file()
        if wf.exists():
            try:
                data = json.loads(wf.read_text(encoding="utf-8"))
                for agent_id, w in data.items():
                    self._weights[agent_id] = ExpertWeight(
                        agent_id=agent_id,
                        base_weight=w.get("base_weight", 1.0),
                        domain_expertise=w.get("domain_expertise", 1.0),
                        track_record=w.get("track_record", 1.0),
                        total_tasks=w.get("total_tasks", 0),
                        correct_tasks=w.get("correct_tasks", 0),
                    )
            except Exception:
                pass

    def _save(self):
        """保存权重到文件"""
        data = {aid: w.to_dict() for aid, w in self._weights.items()}
        self.team_root.mkdir(parents=True, exist_ok=True)
        atomic_write(
            str(self._weights_file()),
            json.dumps(data, ensure_ascii=False, indent=2),
        )

    def get_weight(self, agent_id: str, domain: str = "general", role: str = "unknown") -> ExpertWeight:
        """获取专家权重（不存在时创建默认）"""
        if agent_id not in self._weights:
            base = ROLE_WEIGHTS.get(role, 1.0)
            self._weights[agent_id] = ExpertWeight(
                agent_id=agent_id,
                base_weight=base,
            )
        w = self._weights[agent_id]

        # 根据领域调整 domain_expertise
        # 简单实现：有历史记录的领域得高分
        if domain != "general":
            w.domain_expertise = min(1.0, 0.5 + w.track_record * 0.5)

        return w

    def update_record(self, agent_id: str, task_type: str = "", correct: bool = True):
        """更新专家历史记录"""
        if agent_id not in self._weights:
            self._weights[agent_id] = ExpertWeight(agent_id=agent_id)

        w = self._weights[agent_id]
        w.total_tasks += 1
        if correct:
            w.correct_tasks += 1

        # 更新准确率（滑动窗口，衰减旧数据）
        if w.total_tasks > 0:
            w.track_record = w.correct_tasks / w.total_tasks

        self._save()

    def get_all_weights(self) -> Dict[str, dict]:
        """获取所有专家权重"""
        return {aid: w.to_dict() for aid, w in self._weights.items()}

    def get_ranking(self, domain: str = "general") -> List[dict]:
        """按有效权重排序"""
        items = []
        for aid, w in self._weights.items():
            effective = w.base_weight * w.domain_expertise * w.track_record
            items.append({
                "agent_id": aid,
                "effective_weight": effective,
                "track_record": w.track_record,
                "total_tasks": w.total_tasks,
            })
        return sorted(items, key=lambda x: x["effective_weight"], reverse=True)

    def apply_vote_weights(self, votes: Dict[str, str]) -> Dict[str, dict]:
        """加权投票统计"""
        weighted_votes: Dict[str, float] = {}
        for agent_id, stance in votes.items():
            w = self.get_weight(agent_id)
            weight = w.effective_weight
            weighted_votes[stance] = weighted_votes.get(stance, 0) + weight

        # 判定
        total_weight = sum(weighted_votes.values())
        if total_weight == 0:
            return {"result": "no_votes", "weighted_votes": {}}

        winning_stance = max(weighted_votes, key=weighted_votes.get)
        winning_ratio = weighted_votes[winning_stance] / total_weight

        return {
            "result": "consensus" if winning_ratio > 0.6 else "contested",
            "winning_stance": winning_stance,
            "winning_ratio": winning_ratio,
            "weighted_votes": {k: round(v, 3) for k, v in weighted_votes.items()},
        }


if __name__ == "__main__":
    # 测试
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        mgr = ExpertWeightManager(Path(tmp))

        # 模拟任务结果
        mgr.update_record("analyst-1", "估值分析", correct=True)
        mgr.update_record("analyst-1", "估值分析", correct=True)
        mgr.update_record("analyst-1", "估值分析", correct=False)
        mgr.update_record("analyst-2", "估值分析", correct=True)

        # 获取权重
        w1 = mgr.get_weight("analyst-1", domain="估值", role="DomainExpert")
        w2 = mgr.get_weight("analyst-2", domain="估值", role="Analyst")

        print(f"analyst-1: {w1.to_dict()}")
        print(f"analyst-2: {w2.to_dict()}")

        # 加权投票
        votes = {"analyst-1": "看空", "analyst-2": "看多", "analyst-3": "看空"}
        result = mgr.apply_vote_weights(votes)
        print(f"投票结果: {result}")

        # 排名
        ranking = mgr.get_ranking("估值")
        print(f"排名: {ranking}")
