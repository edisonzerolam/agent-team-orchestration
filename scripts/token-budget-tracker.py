"""token-budget-tracker.py — Token消耗追踪与告警

功能：
- 记录每个agent的token消耗
- 计算总预算消耗百分比
- 达到80%时在progress.md告警
- 超限时停止新spawn并告警

数据存储：{team_id}-token-budget.json（shared/team-brain/teams/目录）
"""

import json
import sys
from pathlib import Path
from datetime import datetime
from typing import Optional

# 复杂度→预算映射
TOKEN_BUDGETS = {
    "simple": 30000,
    "medium": 60000,
    "complex": 100000,
    "ultra": 150000
}

# 阶段预算分配
STAGE_BUDGETS = {
    "pre_task": 0.15,   # 15% for Pre-task Discussion
    "mid_task": 0.70,   # 70% for Mid-task Execution
    "post_task": 0.10,  # 10% for Post-task Consensus
    "buffer": 0.05      # 5% buffer
}


class TokenBudgetTracker:
    def __init__(self, team_id: str, complexity: str = "medium"):
        self.team_id = team_id
        self.total_budget = TOKEN_BUDGETS.get(complexity, 60000)
        self.complexity = complexity
        self.stage_budgets = {k: int(self.total_budget * v) for k, v in STAGE_BUDGETS.items()}

        # 存储路径：scripts/ 向上两级 → agent-team-orchestration/ → shared/team-brain/teams/
        self.team_dir = Path(__file__).parent.parent / "shared" / "team-brain" / "teams"
        self.team_dir.mkdir(parents=True, exist_ok=True)
        self.data_file = self.team_dir / f"{team_id}-token-budget.json"

        self.data = self._load()

    def _load(self) -> dict:
        if self.data_file.exists():
            return json.loads(self.data_file.read_text(encoding="utf-8"))
        return {
            "team_id": self.team_id,
            "total_budget": self.total_budget,
            "complexity": self.complexity,
            "agents": {},  # agent_id -> {"consumed": int, "last_update": str}
            "stages": {k: 0 for k in STAGE_BUDGETS},
            "warnings": [],  # ["[HH:MM] warning message"]
            "stop_spawn": False
        }

    def _save(self):
        self.data_file.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")

    def record(self, agent_id: str, tokens: int, stage: str = "mid_task"):
        """记录某agent的token消耗"""
        if agent_id not in self.data["agents"]:
            self.data["agents"][agent_id] = {"consumed": 0, "last_update": ""}
        self.data["agents"][agent_id]["consumed"] += tokens
        self.data["agents"][agent_id]["last_update"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.data["stages"][stage] = self.data["stages"].get(stage, 0) + tokens
        self._save()
        self._check_warnings()

    def get_total_consumed(self) -> int:
        return sum(a["consumed"] for a in self.data["agents"].values())

    def get_consumption_pct(self) -> float:
        return self.get_total_consumed() / self.total_budget * 100

    def _check_warnings(self):
        pct = self.get_consumption_pct()
        if pct >= 100 and not self.data["stop_spawn"]:
            self.data["stop_spawn"] = True
            self.data["warnings"].append(
                f"[{datetime.now().strftime('%H:%M')}] ⚠️ Token预算超限！停止新spawn。"
            )
            self._write_progress_warning(f"## ⚠️ [Token告警] 预算超限，已停止新spawn")
        elif pct >= 80:
            self.data["warnings"].append(
                f"[{datetime.now().strftime('%H:%M')}] ⚠️ Token消耗已达{pct:.0f}%，注意控制。"
            )
            self._write_progress_warning(
                f"## ⚠️ [Token告警] 消耗已达{pct:.0f}%，请注意控制"
            )
        self._save()

    def _write_progress_warning(self, message: str):
        """向 progress.md 写入告警行"""
        progress_file = self.team_dir.parent.parent / "progress.md"
        try:
            progress_file.parent.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            line = f"[{timestamp}] {message}\n"
            with open(progress_file, "a", encoding="utf-8") as f:
                f.write(line)
        except Exception:
            pass

    def should_stop_spawn(self) -> bool:
        return self.data.get("stop_spawn", False)

    def get_summary(self) -> dict:
        return {
            "team_id": self.team_id,
            "total_budget": self.total_budget,
            "consumed": self.get_total_consumed(),
            "pct": self.get_consumption_pct(),
            "warnings": self.data["warnings"],
            "stop_spawn": self.should_stop_spawn()
        }


def main():
    if len(sys.argv) < 3:
        print("Usage: token-budget-tracker.py <record|summary|check-stop> <team_id> [tokens]")
        sys.exit(1)

    cmd = sys.argv[1]
    team_id = sys.argv[2]

    tracker = TokenBudgetTracker(team_id)

    if cmd == "--record" or cmd == "record":
        if len(sys.argv) < 5:
            print("Usage: tracker.py record <team_id> <agent_id> <tokens> [stage]")
            sys.exit(1)
        agent_id = sys.argv[3]
        tokens = int(sys.argv[4])
        stage = sys.argv[5] if len(sys.argv) > 5 else "mid_task"
        tracker.record(agent_id, tokens, stage)
        print(f"Recorded {tokens} tokens for {agent_id}, total: {tracker.get_total_consumed()}")

    elif cmd == "--summary" or cmd == "summary":
        summary = tracker.get_summary()
        print(json.dumps(summary, ensure_ascii=False, indent=2))

    elif cmd == "--check-stop" or cmd == "check-stop":
        stop = tracker.should_stop_spawn()
        print("STOP" if stop else "OK")
        sys.exit(1 if stop else 0)

    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)


if __name__ == "__main__":
    main()