"""
checkpoint-manager.py — T3+ 任务 checkpoint 管理器

功能：
- 写入 checkpoint（团队状态、已完成子任务、下一步）
- 读取 checkpoint（恢复团队状态）
- 检测超时（2分钟无写入则告警）
- 支持 sessions_spawn 主会话直接调用

使用方式：
    from checkpoint_manager import CheckpointManager
    
    cm = CheckpointManager(team_id="my-team", checkpoint_dir=".checkpoints")
    cm.save(state={"completed_subtasks": [...], "can_resume_from": "..."})
    
    # 检测超时
    if cm.is_stale(threshold_minutes=2):
        print("⚠️ Checkpoint 已超时，可能需要干预")
"""

import json
import time
import os
from pathlib import Path
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta


@dataclass
class Checkpoint:
    """Checkpoint 数据结构"""
    team_id: str
    timestamp: str          # ISO 格式
    completed_subtasks: List[str]
    can_resume_from: str
    next_action: str
    agent_states: Dict[str, str]  # agent_id -> state
    metadata: Dict[str, Any]


class CheckpointManager:
    """T3+ 任务 checkpoint 管理器"""
    
    def __init__(
        self,
        team_id: str,
        checkpoint_dir: str = ".checkpoints",
        stale_threshold_minutes: int = 2,
    ):
        self.team_id = team_id
        self.checkpoint_dir = Path(checkpoint_dir)
        self.stale_threshold = timedelta(minutes=stale_threshold_minutes)
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)
        self.checkpoint_file = self.checkpoint_dir / f"{team_id}.json"
    
    def _now_iso(self) -> str:
        return datetime.now().isoformat()
    
    def save(
        self,
        state: Dict[str, Any],
        completed_subtasks: Optional[List[str]] = None,
        next_action: str = "",
        agent_states: Optional[Dict[str, str]] = None,
    ) -> str:
        """
        保存 checkpoint。
        
        Returns: checkpoint 文件路径
        """
        checkpoint = Checkpoint(
            team_id=self.team_id,
            timestamp=self._now_iso(),
            completed_subtasks=completed_subtasks or state.get("completed_subtasks", []),
            can_resume_from=state.get("can_resume_from", ""),
            next_action=next_action or state.get("next_action", ""),
            agent_states=agent_states or state.get("agent_states", {}),
            metadata=state.get("metadata", {}),
        )
        
        with open(self.checkpoint_file, "w", encoding="utf-8") as f:
            json.dump(asdict(checkpoint), f, ensure_ascii=False, indent=2)
        
        return str(self.checkpoint_file)
    
    def load(self) -> Optional[Checkpoint]:
        """加载 checkpoint，不存在返回 None"""
        if not self.checkpoint_file.exists():
            return None
        try:
            with open(self.checkpoint_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            return Checkpoint(**data)
        except (json.JSONDecodeError, TypeError):
            return None
    
    def is_stale(self) -> bool:
        """检查 checkpoint 是否超时（超过 stale_threshold 无更新）"""
        cp = self.load()
        if cp is None:
            return True  # 不存在 = 陈旧
        
        last_time = datetime.fromisoformat(cp.timestamp)
        return datetime.now() - last_time > self.stale_threshold
    
    def time_since_last_update(self) -> Optional[timedelta]:
        """距离上次更新的时间，不存在返回 None"""
        cp = self.load()
        if cp is None:
            return None
        last_time = datetime.fromisoformat(cp.timestamp)
        return datetime.now() - last_time
    
    def delete(self) -> bool:
        """删除 checkpoint 文件"""
        if self.checkpoint_file.exists():
            self.checkpoint_file.unlink()
            return True
        return False
    
    def summary(self) -> str:
        """生成 checkpoint 摘要字符串（用于日志输出）"""
        cp = self.load()
        if cp is None:
            return f"[{self.team_id}] 无 checkpoint"
        
        age = self.time_since_last_update()
        age_str = f"{age.total_seconds():.0f}s 前" if age else "未知"
        
        return (
            f"[{self.team_id}] checkpoint @ {cp.timestamp}\n"
            f"  已完成 {len(cp.completed_subtasks)} 个子任务 | "
            f"上次更新 {age_str} | "
            f"可恢复点: {cp.can_resume_from or '无'}"
        )


# ═══════════════════════════════════════════════════
# 便捷函数（供主会话 sessions_spawn 调用）
# ═══════════════════════════════════════════════════

def checkpoint_save(
    team_id: str,
    completed_subtasks: List[str],
    can_resume_from: str,
    next_action: str = "",
    agent_states: Optional[Dict[str, str]] = None,
    checkpoint_dir: str = ".checkpoints",
) -> str:
    """一键保存 checkpoint"""
    cm = CheckpointManager(team_id=team_id, checkpoint_dir=checkpoint_dir)
    return cm.save(
        state={},
        completed_subtasks=completed_subtasks,
        next_action=next_action,
        agent_states=agent_states,
    )


def checkpoint_status(
    team_id: str,
    checkpoint_dir: str = ".checkpoints",
) -> str:
    """获取 checkpoint 状态摘要"""
    cm = CheckpointManager(team_id=team_id, checkpoint_dir=checkpoint_dir)
    return cm.summary()


def checkpoint_is_stale(
    team_id: str,
    threshold_minutes: int = 2,
    checkpoint_dir: str = ".checkpoints",
) -> bool:
    """检查 checkpoint 是否超时"""
    cm = CheckpointManager(
        team_id=team_id,
        checkpoint_dir=checkpoint_dir,
        stale_threshold_minutes=threshold_minutes,
    )
    return cm.is_stale()