#!/usr/bin/env python3

"""


# [中文说明]
# 本文件：health-monitor.py
# 用途：OpenClaw 框架的核心脚本之一
# 详细文档：请阅读对应的 SKILL.md 和 references/

Health Monitor -- 协调人健康检查系统

检测 Agent 是否存活,超时,失败



用法:

    python health-monitor.py check <team_id>      # 检查团队健康状态

    python health-monitor.py watch <team_id>       # 持续监控(每秒)

    python health-monitor.py summary               # 所有团队汇总

"""



import json

import sys

import time

from datetime import datetime, timedelta

from pathlib import Path



TEAM_BRAIN_ROOT = Path(__file__).parent.parent.parent / "shared" / "team-brain"

PERIODIC_CHECK_TIMEOUT = 120  # 超过120秒无心跳认为已挂



def load_team_status(team_id):

    status_file = TEAM_BRAIN_ROOT / "teams" / f"{team_id}.json"

    if not status_file.exists():

        return None

    with open(status_file, encoding="utf-8") as f:

        return json.load(f)



def check_agent_health(agent, now=None):

    """检查单个 Agent 的健康状态"""

    if now is None:

        now = datetime.now()

    

    last_heartbeat = agent.get("last_heartbeat")

    status = agent.get("status", "unknown")

    

    if last_heartbeat:

        try:

            last = datetime.fromisoformat(last_heartbeat)

            seconds_since = (now - last).total_seconds()

            is_alive = seconds_since < PERIODIC_CHECK_TIMEOUT

            return {

                "id": agent["id"],

                "role": agent.get("role"),

                "status": status,

                "last_heartbeat": last_heartbeat,

                "seconds_ago": int(seconds_since),

                "is_alive": is_alive,

                "is_stale": seconds_since > PERIODIC_CHECK_TIMEOUT,

                "is_failed": status in ("failed", "failed_with_error")

            }

        except:

            pass

    

    return {

        "id": agent["id"],

        "role": agent.get("role"),

        "status": status,

        "last_heartbeat": last_heartbeat,

        "seconds_ago": None,

        "is_alive": False,

        "is_stale": True,

        "is_failed": status in ("failed", "failed_with_error")

    }



def check_team_health(team_id):

    """检查整个团队的健康状态"""

    status = load_team_status(team_id)

    if not status:

        return {"error": f"team {team_id} not found"}

    

    now = datetime.now()

    agent_health = []

    alive_count = 0

    stale_count = 0

    failed_count = 0

    

    for agent in status.get("agents", []):

        h = check_agent_health(agent, now)

        agent_health.append(h)

        if h["is_alive"]:

            alive_count += 1

        if h["is_stale"] and not h["is_failed"]:

            stale_count += 1

        if h["is_failed"]:

            failed_count += 1

    

    total = len(status.get("agents", []))

    

    # 整体健康评分

    if total == 0:

        health_score = 0

    else:

        health_score = alive_count / total

    

    return {

        "team_id": team_id,

        "task": status.get("task"),

        "phase": status.get("phase"),

        "total_agents": total,

        "alive": alive_count,

        "stale": stale_count,

        "failed": failed_count,

        "health_score": round(health_score, 2),

        "agents": agent_health,

        "warnings": _generate_warnings(alive_count, stale_count, failed_count, total)

    }



def _generate_warnings(alive, stale, failed, total):

    warnings = []

    if stale > 0:

        warnings.append(f"{stale} 个 Agent 无心跳响应,可能已挂")

    if failed > 0:

        warnings.append(f"{failed} 个 Agent 执行失败")

    if alive < total:

        warnings.append(f"团队不完整:{alive}/{total} Agent 存活")

    return warnings



def get_all_teams():

    """获取所有团队状态"""

    teams_dir = TEAM_BRAIN_ROOT / "teams"

    if not teams_dir.exists():

        return {}

    

    teams = {}

    for f in teams_dir.glob("*.json"):

        team_id = f.stem

        health = check_team_health(team_id)

        teams[team_id] = health

    return teams



def print_team_health(health):

    """打印团队健康状态(人类可读格式)"""

    print(f"\n{'='*60}")

    print(f"团队: {health['team_id']}")

    print(f"任务: {health.get('task', 'N/A')}")

    print(f"阶段: {health.get('phase', 'N/A')}")

    print(f"健康评分: {health['health_score']} ({health['alive']}/{health['total_agents']} 存活)")

    

    if health.get("warnings"):

        print("\n⚠️  警告:")

        for w in health["warnings"]:

            print(f"   - {w}")

    

    print("\nAgent 状态:")

    for a in health["agents"]:

        alive_mark = "✓" if a["is_alive"] else "✗"

        stale_mark = " (无心跳)" if a["is_stale"] else ""

        failed_mark = " [失败]" if a["is_failed"] else ""

        secs = f" ({a['seconds_ago']}s前)" if a["seconds_ago"] else ""

        print(f"   {alive_mark} {a['id']:12} | {a['status']:20} | {a['role']}{stale_mark}{failed_mark}{secs}")



def main():

    if len(sys.argv) < 2:

        print(__doc__)

        sys.exit(1)

    

    cmd = sys.argv[1]

    

    if cmd == "check":

        team_id = sys.argv[2] if len(sys.argv) > 2 else None

        if not team_id:

            print("需要 team_id")

            sys.exit(1)

        health = check_team_health(team_id)

        print_team_health(health)

        

        # 输出 JSON 格式(便于程序处理)

        print("\n--- JSON Output ---")

        print(json.dumps(health, ensure_ascii=False, indent=2))

    

    elif cmd == "watch":

        team_id = sys.argv[2] if len(sys.argv) > 2 else None

        if not team_id:

            print("需要 team_id")

            sys.exit(1)

        

        print(f"持续监控 {team_id},按 Ctrl+C 停止...")

        try:

            while True:

                health = check_team_health(team_id)

                # 清屏(简单实现)

                print("\n" * 2)

                print_team_health(health)

                time.sleep(10)

        except KeyboardInterrupt:

            print("\n监控停止")

    

    elif cmd == "summary":

        teams = get_all_teams()

        print(f"\n{'='*60}")

        print(f"所有团队健康状态 ({len(teams)} 个团队)")

        print(f"{'='*60}")

        

        for tid, health in teams.items():

            print(f"\n{tid}: {health['health_score']} ({health['alive']}/{health['total_agents']})")

            if health.get("warnings"):

                for w in health["warnings"]:

                    print(f"   ⚠️ {w}")

    

    else:

        print(f"未知命令: {cmd}")

        print(__doc__)

        sys.exit(1)



if __name__ == "__main__":

    main()
