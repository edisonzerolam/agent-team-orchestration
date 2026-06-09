"""checkpoint-poller.py — Agent卡住检测与Checkpoint轮询


# [中文说明]
# 本文件：checkpoint-poller.py
# 用途：OpenClaw 框架的核心脚本之一
# 详细文档：请阅读对应的 SKILL.md 和 references/

功能：
- 每30秒检查一次所有agent的checkpoint
- 检测progress连续2次无变化 → 标记为"可能卡住"
- 120秒无心跳 → is_stale=True
- 发现卡住时写警告到progress.md，通知Orchestrator

使用场景：Orchestrator发起spawn后，等待时用此脚本监控子agent
"""

import json
import time
import sys
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict

DEFAULT_INTERVAL = 30   # 每30秒轮询
STALE_THRESHOLD = 120   # 120秒无心跳视为stale

# ---------------------------------------------------------------------------
# 辅助：atomic_write 跨平台原子写入（内联，避免循环导入问题）
# ---------------------------------------------------------------------------

def _atomic_write(path: str, content: str, encoding: str = "utf-8") -> None:
    """原子写入：临时文件+os.replace，跨平台"""
    import os
    import uuid
    p = Path(path).resolve()
    tmp = p.parent / f".{uuid.uuid4().hex[:8]}.tmp"
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_text(content, encoding=encoding)
    os.replace(str(tmp), str(p))


def _atomic_append(path: str, line: str, encoding: str = "utf-8", max_lines: int = 20) -> None:
    """原子追加：保留最近max_lines行，再追加新行"""
    p = Path(path).resolve()
    if p.exists():
        lines = p.read_text(encoding=encoding).splitlines()
        lines = lines[-max_lines:]
    else:
        lines = []
    lines.append(line)
    content = "\n".join(lines) + "\n"
    _atomic_write(str(p), content, encoding)


# ---------------------------------------------------------------------------
# 核心逻辑
# ---------------------------------------------------------------------------

def load_checkpoints(team_id: str) -> List[dict]:
    """加载所有checkpoint文件"""
    script_dir = Path(__file__).parent
    ck_dir = script_dir.parent / "shared" / "team-brain" / "checkpoints" / team_id
    if not ck_dir.exists():
        return []
    results = []
    for f in ck_dir.glob("*.json"):
        try:
            results.append(json.loads(f.read_text(encoding="utf-8")))
        except Exception:
            pass
    return results


def detect_stuck_agents(checkpoints: List[dict], _stuck_threshold: int = 2) -> List[dict]:
    """检测连续无进展的agent
    - 按agent_id分组，取最新2条checkpoint
    - progress字段连续2次相同 → 标记为"可能卡住"
    """
    # 按agent_id分组
    latest_by_agent: Dict[str, List[dict]] = {}
    for ck in checkpoints:
        aid = ck.get("agent_id")
        if aid:
            latest_by_agent.setdefault(aid, []).append(ck)

    stuck = []
    for aid, cks in latest_by_agent.items():
        # 取最新2条（按timestamp倒序）
        cks_sorted = sorted(cks, key=lambda x: x.get("timestamp", ""), reverse=True)[:2]
        if len(cks_sorted) >= 2:
            p1 = cks_sorted[0].get("progress", "")
            p2 = cks_sorted[1].get("progress", "")
            if p1 and p1 == p2:          # progress非空且两次相同
                stuck.append({
                    "agent_id": aid,
                    "progress": p1,
                    "last_checkpoint": cks_sorted[0].get("timestamp", ""),
                    "reason": f"连续2次progress无变化: {p1}"
                })
    return stuck


def detect_stale_agents(checkpoints: List[dict], stale_seconds: int = STALE_THRESHOLD) -> List[dict]:
    """检测心跳超时的agent
    - 检查 last_heartbeat 或 timestamp 字段
    - 超时阈值默认120秒
    """
    now = datetime.now()
    stale = []
    for ck in checkpoints:
        # 优先用 last_heartbeat，其次用 timestamp
        ts = ck.get("last_heartbeat") or ck.get("timestamp", "")
        if not ts:
            continue
        try:
            last = datetime.fromisoformat(ts)
            age = (now - last).total_seconds()
            if age > stale_seconds:
                stale.append({
                    "agent_id": ck.get("agent_id", "unknown"),
                    "last_heartbeat": ts,
                    "age_seconds": int(age),
                    "reason": f"心跳超时({age:.0f}s>{stale_seconds}s)"
                })
        except Exception:
            pass
    return stale


def write_progress_warning(team_id: str, message: str) -> None:
    """写告警到 progress.md（原子追加，防止并发覆盖）"""
    script_dir = Path(__file__).parent
    progress_file = script_dir.parent / "shared" / "team-brain" / f"{team_id}-progress.md"
    timestamp = datetime.now().strftime("%H:%M:%S")
    line = f"[{timestamp}] [CHECKPOINT POLLER] ⚠️ {message}"
    _atomic_append(str(progress_file), line)


def poll_team(team_id: str, interval: int = DEFAULT_INTERVAL,
              max_iterations: Optional[int] = None) -> None:
    """持续轮询团队状态，直到所有agent完成或达到max_iterations"""
    iteration = 0
    print(f"[CHECKPOINT POLLER] Started monitoring team={team_id} interval={interval}s")

    while True:
        if max_iterations is not None and iteration >= max_iterations:
            print(f"[CHECKPOINT POLLER] Max iterations {max_iterations} reached. Exiting.")
            break

        checkpoints = load_checkpoints(team_id)
        stuck = detect_stuck_agents(checkpoints)
        stale = detect_stale_agents(checkpoints)

        now_str = datetime.now().strftime("%H:%M:%S")

        for agent in stuck:
            msg = f"Agent {agent['agent_id']} 可能卡住: {agent['reason']}"
            print(f"[{now_str}] STUCK: {msg}")
            write_progress_warning(team_id, msg)

        for agent in stale:
            msg = f"Agent {agent['agent_id']} 已失联: {agent['reason']}"
            print(f"[{now_str}] STALE: {msg}")
            write_progress_warning(team_id, msg)

        if not stuck and not stale:
            print(f"[{now_str}] All agents healthy. Checkpoints: {len(checkpoints)}")

        time.sleep(interval)
        iteration += 1


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(
        description="Checkpoint poller for team monitoring — detect stuck/stale agents"
    )
    parser.add_argument("team_id", help="Team ID to monitor")
    parser.add_argument(
        "--interval", type=int, default=DEFAULT_INTERVAL,
        help=f"Polling interval in seconds (default: {DEFAULT_INTERVAL})"
    )
    parser.add_argument(
        "--max-iterations", type=int, default=None,
        help="Max polling iterations (None=infinite, default: None)"
    )
    args = parser.parse_args()
    poll_team(args.team_id, args.interval, args.max_iterations)


if __name__ == "__main__":
    main()