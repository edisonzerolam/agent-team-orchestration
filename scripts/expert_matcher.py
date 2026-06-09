"""expert-matcher.py — P2 专家能力匹配


# [中文说明]
# 本文件：expert_matcher.py
# 用途：OpenClaw 框架的核心脚本之一
# 详细文档：请阅读对应的 SKILL.md 和 references/

Usage:
    from expert_matcher import ExpertMatcher
    
    matcher = ExpertMatcher(team_root)
    best_team = matcher.match(task_domain="估值", task_type="分析", available_agents=[...])
"""

import json
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from pathlib import Path


@dataclass
class AgentProfile:
    """专家能力画像"""
    agent_id: str
    roles: List[str] = field(default_factory=list)       # 擅长角色
    domains: List[str] = field(default_factory=list)     # 擅长领域
    specialties: List[str] = field(default_factory=list) # 专长标签
    track_record: float = 0.5                            # 历史准确率
    avg_quality: float = 0.5                             # 平均讨论质量
    total_tasks: int = 0

    def to_dict(self) -> dict:
        return {
            "agent_id": self.agent_id,
            "roles": self.roles,
            "domains": self.domains,
            "specialties": self.specialties,
            "track_record": self.track_record,
            "avg_quality": self.avg_quality,
            "total_tasks": self.total_tasks,
        }


class ExpertMatcher:
    """专家能力匹配器"""

    def __init__(self, team_root: Path):
        self.team_root = Path(team_root)
        self._profiles: Dict[str, AgentProfile] = {}
        self._load()

    def _profiles_file(self) -> Path:
        return self.team_root / "expert-profiles.json"

    def _load(self):
        pf = self._profiles_file()
        if pf.exists():
            try:
                data = json.loads(pf.read_text(encoding="utf-8"))
                for agent_id, p in data.items():
                    self._profiles[agent_id] = AgentProfile(agent_id=agent_id, **{
                        k: v for k, v in p.items()
                        if k in AgentProfile.__dataclass_fields__
                    })
            except Exception:
                pass

    def _save(self):
        data = {aid: p.to_dict() for aid, p in self._profiles.items()}
        self.team_root.mkdir(parents=True, exist_ok=True)
        with open(self._profiles_file(), 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def update_profile(self, agent_id: str, **kwargs):
        """更新专家画像"""
        if agent_id not in self._profiles:
            self._profiles[agent_id] = AgentProfile(agent_id=agent_id)
        p = self._profiles[agent_id]
        for k, v in kwargs.items():
            if hasattr(p, k):
                setattr(p, k, v)
        self._save()

    def match(
        self,
        task_domain: str = "",
        task_type: str = "",
        available_agents: Optional[List[str]] = None,
        team_size: int = 3,
    ) -> List[dict]:
        """匹配最佳专家组合"""
        candidates = []
        for agent_id, profile in self._profiles.items():
            if available_agents and agent_id not in available_agents:
                continue

            score = self._score_agent(profile, task_domain, task_type)
            candidates.append({
                "agent_id": agent_id,
                "score": score,
                "profile": profile.to_dict(),
            })

        # 按分数排序
        candidates.sort(key=lambda x: x["score"], reverse=True)

        # 贪心选择：确保角色多样性
        selected = []
        used_roles = set()
        for c in candidates:
            if len(selected) >= team_size:
                break
            # 优先选不同角色
            primary_role = c["profile"]["roles"][0] if c["profile"]["roles"] else "unknown"
            if primary_role not in used_roles or len(selected) >= team_size - 1:
                selected.append(c)
                used_roles.add(primary_role)

        return selected

    def _score_agent(self, profile: AgentProfile, task_domain: str, task_type: str) -> float:
        """计算专家与任务的匹配分数"""
        score = 0.0

        # 领域匹配（0-0.4）
        if task_domain and task_domain in profile.domains:
            score += 0.4
        elif task_domain:
            # 部分匹配
            for d in profile.domains:
                if task_domain in d or d in task_domain:
                    score += 0.2
                    break

        # 类型匹配（0-0.3）
        type_keywords = {
            "分析": ["analyst", "researcher", "analyst"],
            "评估": ["reviewer", "evaluator", "analyst"],
            "规划": ["planner", "strategist", "orchestrator"],
            "执行": ["builder", "developer", "executor"],
        }
        if task_type:
            expected_roles = type_keywords.get(task_type, [])
            for role in profile.roles:
                if role.lower() in [r.lower() for r in expected_roles]:
                    score += 0.3
                    break

        # 历史表现（0-0.2）
        score += profile.track_record * 0.2

        # 讨论质量（0-0.1）
        score += profile.avg_quality * 0.1

        return round(score, 3)

    def get_recommendation(self, agent_id: str, task_domain: str = "") -> dict:
        """获取单个专家的任务建议"""
        profile = self._profiles.get(agent_id)
        if not profile:
            return {"error": f"Agent {agent_id} not found"}

        strengths = []
        weaknesses = []

        if task_domain:
            if task_domain in profile.domains:
                strengths.append(f"领域匹配: {task_domain}")
            else:
                weaknesses.append(f"领域不匹配: 擅长 {profile.domains}")

        if profile.track_record >= 0.7:
            strengths.append(f"历史准确率高: {profile.track_record:.0%}")
        elif profile.track_record < 0.5:
            weaknesses.append(f"历史准确率低: {profile.track_record:.0%}")

        return {
            "agent_id": agent_id,
            "strengths": strengths,
            "weaknesses": weaknesses,
            "recommendation": "推荐" if not weaknesses else "谨慎使用",
        }

    def get_all_profiles(self) -> Dict[str, dict]:
        """获取所有专家画像"""
        return {aid: p.to_dict() for aid, p in self._profiles.items()}


if __name__ == "__main__":
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        matcher = ExpertMatcher(Path(tmp))

        # 模拟画像
        matcher.update_profile("analyst-1", roles=["DomainExpert"], domains=["估值", "财务分析"], track_record=0.85)
        matcher.update_profile("analyst-2", roles=["Reviewer"], domains=["估值", "风险评估"], track_record=0.78)
        matcher.update_profile("builder-1", roles=["Builder"], domains=["执行", "开发"], track_record=0.92)

        # 匹配
        team = matcher.match(task_domain="估值", team_size=2)
        print(f"最佳团队: {[t['agent_id'] for t in team]}")

        # 推荐
        rec = matcher.get_recommendation("analyst-1", task_domain="估值")
        print(f"推荐: {rec}")
