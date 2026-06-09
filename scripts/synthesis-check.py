"""synthesis-check.py — Expert consensus confirmation before final delivery.


# [中文说明]
# 本文件：synthesis-check.py
# 用途：OpenClaw 框架的核心脚本之一
# 详细文档：请阅读对应的 SKILL.md 和 references/

Usage:
    python synthesis-check.py <team_id> <final_report_path> [--timeout=300]

Workflow:
    1. Read team status file to get all expert agents
    2. Collect consensus responses from each expert: ✅ / ⚠️ / ❌
    3. Timeout unresponding experts after --timeout seconds
    4. Generate consensus report at synthesis/{team_id}-consensus-check.md
    5. Print result JSON: delivered / delivered_with_concerns / returned
"""

import json
import sys
import time
import re
from pathlib import Path
from datetime import datetime

SCRIPT_DIR = Path(__file__).parent
SKILL_DIR = SCRIPT_DIR.parent
TEAM_BRAIN_ROOT = SKILL_DIR.parent / "shared" / "team-brain"
DEFAULT_TIMEOUT = 300  # 5 minutes


def load_team(team_id: str) -> dict:
    team_file = TEAM_BRAIN_ROOT / "teams" / f"{team_id}.json"
    if not team_file.exists():
        return {}
    with open(team_file, encoding="utf-8") as f:
        return json.load(f)


def load_final_report(final_report_path: str) -> str:
    p = Path(final_report_path)
    if p.exists():
        return p.read_text(encoding="utf-8")
    return ""


def validate_response(vote: str, detail: str, _report_content: str) -> tuple[bool, str]:
    """校验响应格式是否合规。

    规则：
    - ✅ 只需要理由 ≥10 字符
    - ⚠️/❌ 需要理由 ≥10 字符 + 必须包含 [段落引用]

    Returns:
        (is_valid, error_message)
    """
    if vote == "✅":
        if detail != "No details" and len(detail) < 10:
            return False, "理由不足10字符"
        return True, ""

    if vote in ("⚠️", "❌"):
        if len(detail) < 10:
            return False, "理由不足10字符"
        if not re.search(r'\[[^\]]+\]', detail):
            return False, "⚠️/❌必须包含[具体段落引用]"
        return True, ""

    return True, ""


def parse_response(text: str, report_content: str = "") -> tuple[str, str, bool]:
    """Parse + validate expert response. Returns (vote, detail, is_valid)
    is_valid=False 时由 Orchestrator 退回重填，不计入5分钟倒计时。
    """
    text = text.strip()

    if text.startswith("✅") or "agree" in text.lower() or "approve" in text.lower():
        vote = "✅"
    elif text.startswith("❌") or "object" in text.lower() or "reject" in text.lower():
        vote = "❌"
    elif text.startswith("⚠️") or "concern" in text.lower() or "with concerns" in text.lower():
        vote = "⚠️"
    else:
        vote = "✅"

    lines = text.split("\n", 1)
    if len(lines) > 1:
        detail = lines[1].strip()
    else:
        if text.startswith(("✅", "⚠️", "❌")):
            detail = "No details"
        else:
            detail = text or "No details"

    is_valid, error = validate_response(vote, detail, report_content)
    if not is_valid:
        return vote, f"[格式错误] {error} — 请重新提交", False

    return vote, detail, True


def collect_expert_consensus(team_id: str, final_report_path: str, timeout: int = DEFAULT_TIMEOUT) -> dict:
    """Collect consensus from all experts in the team."""
    team = load_team(team_id)
    if not team:
        return {"error": f"Team {team_id} not found", "team_id": team_id}

    agents = team.get("agents", [])
    if not agents:
        return {"error": "No agents in team", "team_id": team_id}

    final_report = load_final_report(final_report_path)
    if not final_report:
        return {"error": f"Final report not found: {final_report_path}", "team_id": team_id}

    # Build consensus check directory
    consensus_dir = TEAM_BRAIN_ROOT / "synthesis" / team_id
    consensus_dir.mkdir(parents=True, exist_ok=True)

    # Create consensus request file — each expert writes their response here
    request_file = consensus_dir / f"{team_id}-consensus-request.md"
    request_content = f"""# Consensus Check Request — Team {team_id}

## Final Report
```
Path: {final_report_path}
```

## Please Confirm
Read the final report and respond with one of:
- ✅ **Agree** — Report is ready for delivery
- ⚠️ **Concern** — Agree with concerns (state your concern below)
- ❌ **Object** — Object to delivery (state your objection below)

## Your Response
Save your response to:
  {consensus_dir}/{{your_agent_id}}-response.md

Format:
```
[✅/⚠️/❌] — {{your_reason_here}}
```

## Experts to Respond
{chr(10).join(f"- {a['id']} ({a.get('role', 'unknown')})" for a in agents)}
"""
    request_file.write_text(request_content, encoding="utf-8")

    votes = {}
    start_time = time.time()

    # Check for existing response files
    for agent in agents:
        agent_id = agent["id"]
        response_file = consensus_dir / f"{agent_id}-response.md"

        if response_file.exists():
            text = response_file.read_text(encoding="utf-8")
            vote, detail, is_valid = parse_response(text, final_report)
            if is_valid:
                votes[agent_id] = {"vote": vote, "detail": detail, "responded": True, "elapsed": "pre-existing"}
            else:
                votes[agent_id] = {"vote": vote, "detail": detail, "responded": False, "elapsed": "format_invalid"}
        else:
            votes[agent_id] = {"vote": None, "detail": None, "responded": False}

    # Wait for responses with timeout
    while time.time() - start_time < timeout:
        all_responded = all(v.get("responded") for v in votes.values())
        if all_responded:
            break

        time.sleep(5)  # Check every 5 seconds

        for agent in agents:
            agent_id = agent["id"]
            if not votes[agent_id]["responded"]:
                response_file = consensus_dir / f"{agent_id}-response.md"
                if response_file.exists():
                    text = response_file.read_text(encoding="utf-8")
                    vote, detail, is_valid = parse_response(text, final_report)
                    if is_valid:
                        votes[agent_id] = {
                            "vote": vote,
                            "detail": detail,
                            "responded": True,
                            "elapsed": f"{int(time.time() - start_time)}s"
                        }
                    else:
                        votes[agent_id] = {
                            "vote": vote,
                            "detail": detail,
                            "responded": False,
                            "elapsed": f"format_invalid"
                        }

    # Timeout: mark non-respondents as "no objection"
    for agent_id, vote_data in votes.items():
        if not vote_data["responded"]:
            vote_data["vote"] = "✅"
            vote_data["detail"] = "Timeout — treated as no objection"
            vote_data["responded"] = False
            vote_data["elapsed"] = f"timeout_after_{timeout}s"

    # Determine final status
    has_objection = any(v["vote"] == "❌" for v in votes.values())
    has_concern = any(v["vote"] == "⚠️" for v in votes.values())

    if has_objection:
        status = "returned"
    elif has_concern:
        status = "delivered_with_concerns"
    else:
        status = "delivered"

    # Generate consensus report
    report_path = consensus_dir / f"{team_id}-consensus-check.md"
    report_lines = [
        f"# Consensus Check Report — Team {team_id}",
        f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"**Final Report:** `{final_report_path}`",
        f"**Status:** `{status}`",
        "",
        "## Vote Summary",
        ""
    ]

    for agent in agents:
        agent_id = agent["id"]
        v = votes.get(agent_id, {})
        vote = v.get("vote", "❓")
        detail = v.get("detail", "No response")
        responded = v.get("responded", False)
        elapsed = v.get("elapsed", "unknown")
        marker = "✅" if responded else "⏱️"
        report_lines.append(f"{marker} **{agent_id}** ({agent.get('role', '')}): {vote}")
        report_lines.append(f"    Detail: {detail}")
        report_lines.append(f"    Responded: {responded} ({elapsed})")
        report_lines.append("")

    if has_objection:
        report_lines.append("## Objections (Blocking)")
        for agent_id, v in votes.items():
            if v["vote"] == "❌":
                report_lines.append(f"- **{agent_id}**: {v['detail']}")
        report_lines.append("")
        report_lines.append("**Action:** Returned to Builder for revision.")

    if has_concern:
        report_lines.append("## Concerns (Non-blocking)")
        for agent_id, v in votes.items():
            if v["vote"] == "⚠️":
                report_lines.append(f"- **{agent_id}**: {v['detail']}")
        report_lines.append("")
        report_lines.append("**Action:** Delivered with attached concerns.")

    if status == "delivered":
        report_lines.append("**Action:** All experts agree. Report delivered.")

    report_path.write_text("\n".join(report_lines), encoding="utf-8")

    result = {
        "team_id": team_id,
        "final_report_path": final_report_path,
        "consensus_report_path": str(report_path),
        "status": status,
        "votes": {aid: v["vote"] for aid, v in votes.items()},
        "details": {aid: v["detail"] for aid, v in votes.items()},
        "responded_count": sum(1 for v in votes.values() if v["responded"]),
        "total_experts": len(agents),
        "elapsed_seconds": int(time.time() - start_time)
    }

    # Update team status to reflect consensus check phase
    team_file = TEAM_BRAIN_ROOT / "teams" / f"{team_id}.json"
    if team_file.exists():
        with open(team_file, encoding="utf-8") as f:
            team_data = json.load(f)
        team_data["phase"] = "consensus_check"
        team_data["consensus_status"] = status
        team_file.write_text(json.dumps(team_data, ensure_ascii=False, indent=2), encoding="utf-8")

    return result


def main():
    import sys
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python synthesis-check.py <team_id> <final_report_path> [--timeout=300]")
        sys.exit(1)

    # Parse arguments (flexible: team_id and final_report_path can be positional or named)
    team_id = None
    final_report_path = None
    timeout = DEFAULT_TIMEOUT

    args = sys.argv[1:]
    for arg in args:
        if arg.startswith("--timeout="):
            timeout = int(arg.split("=", 1)[1])
        elif not arg.startswith("--") and not arg.startswith("-"):
            if team_id is None:
                team_id = arg
            elif final_report_path is None:
                final_report_path = arg

    if not team_id or not final_report_path:
        print("Usage: python synthesis-check.py <team_id> <final_report_path> [--timeout=300]")
        print(__doc__)
        sys.exit(1)

    result = collect_expert_consensus(team_id, final_report_path, timeout)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()