"""discussion-history.py — P2 历史讨论模式库


# [中文说明]
# 本文件：discussion_history.py
# 用途：OpenClaw 框架的核心脚本之一
# 详细文档：请阅读对应的 SKILL.md 和 references/

Usage:
    from discussion_history import DiscussionHistory
    
    history = DiscussionHistory(team_root)
    history.record(team_id, result)
    suggestion = history.suggest(task_type="估值分析")
"""

import json
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from pathlib import Path

# 导入原子写入
import importlib.util
_SCRIPT_DIR = Path(__file__).parent
_spec = importlib.util.spec_from_file_location("atomic_write", str(_SCRIPT_DIR / "atomic-write.py"))
_aw = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_aw)
atomic_write = _aw.atomic_write


@dataclass
class DiscussionRecord:
    """讨论记录"""
    team_id: str
    timestamp: str
    task_type: str = ""
    task_description: str = ""
    conflict_count: int = 0
    rounds_needed: int = 0
    consensus_time: float = 0.0  # 秒
    consensus_level: str = ""
    quality_score: float = 0.0
    agent_ids: List[str] = field(default_factory=list)
    domain: str = ""

    def to_dict(self) -> dict:
        return {
            "team_id": self.team_id,
            "timestamp": self.timestamp,
            "task_type": self.task_type,
            "task_description": self.task_description,
            "conflict_count": self.conflict_count,
            "rounds_needed": self.rounds_needed,
            "consensus_time": self.consensus_time,
            "consensus_level": self.consensus_level,
            "quality_score": self.quality_score,
            "agent_ids": self.agent_ids,
            "domain": self.domain,
        }


class DiscussionHistory:
    """讨论历史管理器"""

    def __init__(self, team_root: Path):
        self.team_root = Path(team_root)
        self._history_dir = self.team_root / "discussion-history"
        self._history_dir.mkdir(parents=True, exist_ok=True)

    def record(self, team_id: str, result: dict):
        """记录讨论结果"""
        record = DiscussionRecord(
            team_id=team_id,
            timestamp=time.strftime("%Y-%m-%dT%H:%M:%S+08:00"),
            task_type=result.get("task_type", ""),
            task_description=result.get("task_description", "")[:200],
            conflict_count=result.get("conflict_count", 0),
            rounds_needed=result.get("rounds_needed", 0),
            consensus_time=result.get("consensus_time", 0),
            consensus_level=result.get("consensus_level", ""),
            quality_score=result.get("quality_score", 0),
            agent_ids=result.get("agent_ids", []),
            domain=result.get("domain", ""),
        )

        file_path = self._history_dir / f"{team_id}.json"
        atomic_write(
            str(file_path),
            json.dumps(record.to_dict(), ensure_ascii=False, indent=2),
        )

    def suggest(self, task_type: str = "", domain: str = "") -> dict:
        """基于历史建议讨论参数"""
        records = self._load_all()

        # 筛选相似任务
        similar = []
        for r in records:
            if task_type and r.task_type == task_type:
                similar.append(r)
            elif domain and r.domain == domain:
                similar.append(r)

        if not similar:
            return {
                "suggestion": "no_history",
                "recommended_rounds": 2,
                "recommended_timeout": 600,
            }

        # 统计
        avg_rounds = sum(r.rounds_needed for r in similar) / len(similar)
        avg_time = sum(r.consensus_time for r in similar) / len(similar)
        avg_conflicts = sum(r.conflict_count for r in similar) / len(similar)
        avg_quality = sum(r.quality_score for r in similar) / len(similar)
        success_rate = sum(1 for r in similar if r.consensus_level in ("strong", "moderate")) / len(similar)

        return {
            "suggestion": "based_on_history",
            "sample_size": len(similar),
            "avg_rounds": round(avg_rounds, 1),
            "avg_time_seconds": round(avg_time, 0),
            "avg_conflicts": round(avg_conflicts, 1),
            "avg_quality": round(avg_quality, 3),
            "success_rate": round(success_rate, 3),
            "recommended_rounds": max(1, min(3, round(avg_rounds))),
            "recommended_timeout": max(300, min(3600, round(avg_time * 1.2))),
        }

    def get_stats(self, limit: int = 50) -> dict:
        """获取历史统计"""
        records = self._load_all()[:limit]
        if not records:
            return {"total": 0}

        return {
            "total": len(records),
            "avg_rounds": sum(r.rounds_needed for r in records) / len(records),
            "avg_consensus_time": sum(r.consensus_time for r in records) / len(records),
            "avg_quality": sum(r.quality_score for r in records) / len(records),
            "consensus_levels": self._count_levels(records),
            "domain_distribution": self._count_domains(records),
        }

    def _load_all(self) -> List[DiscussionRecord]:
        """加载所有历史记录"""
        records = []
        for f in sorted(self._history_dir.glob("*.json"), reverse=True):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                records.append(DiscussionRecord(**{
                    k: v for k, v in data.items()
                    if k in DiscussionRecord.__dataclass_fields__
                }))
            except Exception:
                continue
        return records

    def _count_levels(self, records: List[DiscussionRecord]) -> Dict[str, int]:
        counts = {}
        for r in records:
            counts[r.consensus_level] = counts.get(r.consensus_level, 0) + 1
        return counts

    def _count_domains(self, records: List[DiscussionRecord]) -> Dict[str, int]:
        counts = {}
        for r in records:
            domain = r.domain or "unknown"
            counts[domain] = counts.get(domain, 0) + 1
        return counts


if __name__ == "__main__":
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        history = DiscussionHistory(Path(tmp))

        # 记录
        history.record("team-001", {
            "task_type": "估值分析",
            "conflict_count": 2,
            "rounds_needed": 3,
            "consensus_time": 1800,
            "consensus_level": "moderate",
            "quality_score": 0.75,
            "agent_ids": ["a1", "a2", "a3"],
            "domain": "估值",
        })

        # 建议
        suggestion = history.suggest(task_type="估值分析")
        print(f"建议: {suggestion}")

        # 统计
        stats = history.get_stats()
        print(f"统计: {stats}")
