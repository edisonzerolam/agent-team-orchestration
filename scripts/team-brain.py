"""ClawTeam Team Brain - Multi-agent orchestration script."""

__doc__ = """Usage:
  python team-brain.py plan <task> <description>
  python team-brain.py launch <topic> <description> [max_agents] [--full-discussion]
  python team-brain.py status [team_id]
  python team-brain.py metrics [team_id]
  python team-brain.py synthesis <team_id>
  python team-brain.py synthesis-check <team_id> <final_report_path> [--timeout=300]
  python team-brain.py debates <team_id>
  python team-brain.py health-monitor <team_id> [interval_seconds]
"""

import sys, os
# 强制 stdout/stderr 使用 UTF-8，解决 Windows GBK 控制台输出中文乱码
if sys.platform == "win32":
    import locale
    locale.setlocale(locale.LC_ALL, '')
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')

import json, subprocess, time, re, threading, hashlib
from datetime import datetime, timezone
from pathlib import Path

# Constants
SCRIPT_DIR = Path(__file__).parent
SKILL_DIR = SCRIPT_DIR.parent
TEAM_BRAIN_ROOT = SKILL_DIR.parent / "shared" / "team-brain"
DEFAULT_MAX_AGENTS = 5

# Hub (协作中心)
import importlib.util
_hub_spec = importlib.util.spec_from_file_location("hub", str(SCRIPT_DIR / "hub.py"))
_hub_mod = importlib.util.module_from_spec(_hub_spec)
_hub_spec.loader.exec_module(_hub_mod)
Hub = _hub_mod.Hub
DEFAULT_TIMEOUT_PER_AGENT = 600
PERIODIC_CHECK_TIMEOUT_SEC = 120  # P1-FIX: 2026-06-07 — health-monitor 超时阈值

__version__ = "3.6.0"

# Import self-heal after SCRIPT_DIR is defined
import importlib.util
spec = importlib.util.spec_from_file_location("self_heal", str(SCRIPT_DIR / "self_heal.py"))
self_heal_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(self_heal_module)
SelfHeal = self_heal_module.SelfHeal

# P1-FIX: 2026-06-07 — 独立状态文件方案
_STATUS_CACHE = {}  # (team_id, agent_id) → cached agent status dict

def _get_team_status_dir(team_id: str) -> Path:
    """P1-FIX: 获取团队独立状态目录（与 team-{id}.json 同层）"""
    return TEAM_BRAIN_ROOT / "teams" / team_id / "status"

def _get_agent_status_path(team_id: str, agent_id: str) -> Path:
    """P1-FIX: 获取 agent 独立状态文件路径"""
    return _get_team_status_dir(team_id) / f"{agent_id}.json"

def _read_agent_status(team_id: str, agent_id: str) -> dict:
    """P1-FIX: 读取单个 agent 的独立状态文件"""
    sp = _get_agent_status_path(team_id, agent_id)
    if sp.exists():
        with open(sp, encoding="utf-8") as f:
            return json.load(f)
    return None

def _write_agent_status_file(team_id: str, agent_id: str, data: dict):
    """P1-FIX: 写入 agent 独立状态文件（不锁 team JSON）"""
    status_dir = _get_team_status_dir(team_id)
    status_dir.mkdir(parents=True, exist_ok=True)
    sp = status_dir / f"{agent_id}.json"
    with open(sp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def _merge_team_with_status(team_data: dict, team_id: str) -> dict:
    """P1-FIX: 将 team snapshot 与独立状态文件合并，返回最新视图"""
    status_dir = _get_team_status_dir(team_id)
    if not status_dir.exists():
        return team_data  # 向后兼容
    merged = dict(team_data)
    merged["_status_source"] = "independent_files"
    agents = list(merged.get("agents", []))
    for i, agent in enumerate(agents):
        cached = _read_agent_status(team_id, agent["id"])
        if cached is not None:
            agents[i] = cached
    merged["agents"] = agents
    return merged

def ensure_dirs():
    root = TEAM_BRAIN_ROOT
    for sub in ["teams", "plans", "findings", "debates", "synthesis", "errors", "messages/inbox", "messages/outbox"]:
        (root / sub).mkdir(parents=True, exist_ok=True)
    return root

# Hub 实例池（team_id → Hub）
_active_hubs = {}



def get_or_create_hub(team_id, agent_ids) -> Hub:
    """获取或创建 Hub（后台线程）"""
    global _active_hubs
    if team_id in _active_hubs and _active_hubs[team_id].is_active:
        return _active_hubs[team_id]
    hub = Hub(team_id, agent_ids, TEAM_BRAIN_ROOT, poll_interval=0.3)
    hub.start()
    _active_hubs[team_id] = hub
    return hub


def stop_hub(team_id):
    global _active_hubs
    if team_id in _active_hubs:
        _active_hubs[team_id].stop()
        del _active_hubs[team_id]

def acquire_lock(lock_path, timeout=5):
    """Get file lock using Windows msvcrt."""
    start = time.time()
    while True:
        try:
            lock_file = open(lock_path, 'w')
            import msvcrt
            msvcrt.locking(lock_file.fileno(), msvcrt.LK_LOCK, 1)
            return lock_file
        except Exception:
            if time.time() - start > timeout:
                return None
            time.sleep(0.1)

def release_lock(lock_file):
    """Release file lock."""
    try:
        import msvcrt
        msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 0)
        lock_file.close()
    except Exception:
        pass

def load_auto_decider():
    """Dynamic load auto-decider module (avoid subprocess overhead)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("auto_decider", str(SCRIPT_DIR / "auto-decider.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

_auto_decider = None

def call_auto_decider(error_msg, retry_count=0):
    """Call auto-decider for decisions (importlib mode, no subprocess delay)."""
    global _auto_decider
    if _auto_decider is None:
        _auto_decider = load_auto_decider()
    return _auto_decider.decide("auto", error_msg, retry_count)

def estimate_complexity(task, description):
    """Estimate task complexity and return planning info."""
    text = f"{task} {description}".lower()
    complexity_score = 1
    estimated_minutes = 5
    domain_count = 1
    complex_indicators = [
        "深度", "全面", "详细", "完整", "系统", "多维度", "综合",
        "分析", "研究", "调研", "规划", "策略", "优化", "诊断"
    ]
    for indicator in complex_indicators:
        if indicator in text:
            complexity_score += 1
            estimated_minutes += 10
    HIGH_KEYWORDS = ["分析", "研究", "评估", "策略", "规划", "投资", "决策"]
    MED_KEYWORDS   = ["对比", "检查", "审核", "讨论"]
    h = sum(1 for k in HIGH_KEYWORDS if k in text)
    m = sum(1 for k in MED_KEYWORDS if k in text)
    use_full_discussion = h >= 2 or (h >= 1 and m >= 2)
    if any(w in text for w in ["投资", "分析", "策略", "研究", "评估"]):
        domain_count = 3
    if any(w in text for w in ["系统", "架构", "平台", "全面"]):
        domain_count = 4
    return {
        "complexity_score": complexity_score,
        "estimated_minutes": estimated_minutes,
        "domain_count": domain_count,
        "use_full_discussion": use_full_discussion,
        "debate_required": domain_count >= 3  # P1-FIX: 2026-06-07 — debate-force
    }

def plan_task(task, description, timeout_budget=300):
    """Plan task: analyze workload -> determine agents -> distribute tasks -> estimate time."""
    root = ensure_dirs()
    complexity = estimate_complexity(task, description)
    agent_count = min(5, max(2, complexity["domain_count"] + 1))
    plan = {
        "plan_id": f"plan-{time.strftime('%Y%m%d-%H%M%S')}-{time.time_ns() % 1000000}",
        "task": task,
        "description": description,
        "complexity": complexity,
        "optimal_agents": agent_count,
        "estimated_with_margin_minutes": int(complexity["estimated_minutes"] * 1.3),
        "estimated_total_minutes": complexity["estimated_minutes"],
        "subtasks": []
    }
    domains = ["宏观", "行业", "估值", "技术", "风险"]
    for i in range(agent_count):
        domain = domains[i % len(domains)]
        plan["subtasks"].append({
            "agent_id": f"agent-{i+1}",
            "domain": domain,
            "role": f"{domain}分析师",
            "timeout_seconds": min(timeout_budget, complexity["estimated_minutes"] * 60 // agent_count),
            "key_questions": []
        })
    plan_file = root / "plans" / f"{plan['plan_id']}.json"
    with open(plan_file, "w", encoding="utf-8") as f:
        json.dump(plan, f, ensure_ascii=False, indent=2)
    return plan

def generate_spawn_prompts(task, description, plan, team_id=None):
    """Generate spawn prompts for each agent based on plan."""
    prompts = {}
    # P1-FIX: 2026-06-07 — debate-force: 复杂度≥中才强制辩论
    _domain_count = plan.get("complexity", {}).get("domain_count", 0)
    _skip_debate = _domain_count < 3
    _debate_section = "" if _skip_debate else f"""
=== Debate Mandatory Requirement ===
在你完成自己的分析并写出 findings 文件后，请执行以下操作：
1. 读取 findings 目录下至少一个其他 agent 的 findings 文件
2. 如果发现与你的分析存在分歧或不同视角，在 debates/ 目录下创建一个辩论文件，命名格式遵循：team_id-debate-你的agent_id-vs-其他agent_id.md
3. 辩论文件内容包含：分歧点描述、各自的论据、你的回应
4. 如果没有分歧，在 findings 末尾注明"已阅读其他 agent 报告，未发现重大分歧"

注意：这是一个真正的团队协作任务。辩论不是可选的，是必选步骤。
"""
    ERROR_HANDLING_GUIDE = '''
=== Error Handling (Important!) ===

You may encounter PowerShell regex errors, command timeouts, or file not found issues. Guidelines:

1. PowerShell regex fix: escape $ as `$`, [ as `[`, ] as `]`
2. Timeout: skip and continue with next subtask
3. File not found: check path, create if needed

If error persists after 2 retries, record to {TEAM_BRAIN_ROOT}/errors/{team_id}/{agent_id}/ and continue.
'''
    for subtask in plan["subtasks"]:
        agent_id = subtask["agent_id"]
        timeout_s = subtask["timeout_seconds"]
        prompts[agent_id] = f"""## Task:{task}
{description}

=== Execution Plan ===
- Domain: {subtask['domain']}
- Role: {subtask['role']}
- Agent ID: {agent_id}
- Team size: {plan['optimal_agents']} experts
- Team ID: {{team_id}}

=== Time Budget ===
You must complete analysis within {timeout_s} seconds.
If timeout, complete core conclusions first, discard minor details.

=== Your Key Questions ===
- What is the core finding in {subtask['domain']}?
- What data supports this?

=== Output Requirements ===
1. Write findings to:{TEAM_BRAIN_ROOT}/findings/{subtask['domain']}/{{plan['plan_id']}}-{agent_id}.md
2. Update:{TEAM_BRAIN_ROOT}/teams/{{{{team_id}}}}.json progress (include last_heartbeat)

=== Team Real-Time Discussion (RT-Discussion) ===
This team supports real-time discussion between experts. Your messages are routed via files.

**Your Agent ID:** {agent_id}

**Message Polling:** Check every ~10s for inbox at:
  `{{TEAM_BRAIN_ROOT}}/messages/inbox/{agent_id}/`
  (Hub writes messages here for you to read)

**Sending Messages:** Write to:
  `{{TEAM_BRAIN_ROOT}}/messages/outbox/{agent_id}/<msg_id>.json`

**Message Types:**
- question → must answer
- challenge → reply with answer or disagree + evidence
- system:discussion_ended → stop discussion, focus on task
- agree/disagree → vote on a point

**When to Initiate Discussion:**
- When you find a discrepancy between your analysis and another expert's finding
- Challenge format: write challenge to messages/outbox/{agent_id}/ with "to" = target agent_id

**After discussion:** Write findings to {TEAM_BRAIN_ROOT}/findings/{subtask['domain']}/... as usual.
{_debate_section}
{ERROR_HANDLING_GUIDE}
"""
    return prompts

def _get_domain_questions(domain, task, description):
    """Generate key questions for domain and task."""
    base_questions = {
        "宏观": ["当前宏观经济环境如何?", "政策面对行业有何影响?", "利率环境对估值的影响"],
        "行业": ["行业供需格局怎样?", "行业增长驱动因素是什么?", "行业壁垒和竞争态势?"],
        "估值": ["当前估值水平合理吗?", "对比历史和同业如何?", "关键估值指标有哪些?"],
        "技术": ["当前价格趋势和形态?", "关键支撑阻力位在哪?", "量价关系是否健康?"],
        "财务": ["盈利能力如何?", "资产负债状况健康吗?", "现金流状况?"],
        "风险": ["主要风险因素是什么?", "风险敞口有多大?", "应对措施?"],
        "竞争": ["主要竞争对手是谁?", "竞争优势/劣势?"],
        "市场": ["市场情绪如何?", "资金流向?"]
    }
    return base_questions.get(domain, ["核心发现是什么?", "数据支撑?"])

def _build_prompts_from_plan(task, description, plan):
    """Build spawn prompts from plan for each agent."""
    prompts = {}
    total_time = plan["estimated_with_margin_minutes"] * 60
    # P1-FIX: 2026-06-07 — debate-force: 复杂度≥中才强制辩论
    _domain_count = plan.get("complexity", {}).get("domain_count", 0)
    _skip_debate = _domain_count < 3
    _debate_section = "" if _skip_debate else f"""

=== Debate Mandatory Requirement ===
在你完成自己的分析并写出 findings 文件后，请执行以下操作：
1. 读取 findings 目录下至少一个其他 agent 的 findings 文件
2. 如果发现与你的分析存在分歧或不同视角，在 debates/ 目录下创建一个辩论文件，命名格式遵循：team_id-debate-你的agent_id-vs-其他agent_id.md
3. 辩论文件内容包含：分歧点描述、各自的论据、你的回应
4. 如果没有分歧，在 findings 末尾注明"已阅读其他 agent 报告，未发现重大分歧"

注意：这是一个真正的团队协作任务。辩论不是可选的，是必选步骤。
"""
    for subtask in plan["subtasks"]:
        agent_id = subtask["agent_id"]
        timeout_s = subtask["timeout_seconds"]
        key_qs = _get_domain_questions(subtask["domain"], task, description)
        prompts[agent_id] = f"""## Task:{task}
{description}

=== Execution Plan ===
- Domain: {subtask['domain']}
- Role: {subtask['role']}
- Agent ID: {agent_id}
- Team: {plan['optimal_agents']} experts
- Team ID: {{team_id}}

=== Time Budget ===
Complete within {timeout_s} seconds.
Priority: core conclusions > minor details.

=== Key Questions ===
{chr(10).join(f"- {q}" for q in key_qs)}

=== Output Requirements ===
1. Write to:{TEAM_BRAIN_ROOT}/findings/{subtask['domain']}/{{plan['plan_id']}}-{agent_id}.md
2. Update:{TEAM_BRAIN_ROOT}/teams/{{{{team_id}}}}.json with last_heartbeat

=== Team Collaboration ===
- Read other experts' findings in {TEAM_BRAIN_ROOT}/findings/
- Raise debates in {TEAM_BRAIN_ROOT}/debates/ if logical issues found
- Don't wait for coordinator, complete analysis and write files immediately
{_debate_section}
=== Error Handling ===
- PowerShell regex: escape $ as `$`, [ as `[`
- Timeout: skip and continue
- Errors > 3x: notify coordinator
"""
    return prompts

def launch_with_plan(plan_id, team_id=None):
    """Launch team based on plan."""
    plan_file = TEAM_BRAIN_ROOT / "plans" / f"{plan_id}.json"
    if not plan_file.exists():
        return {"error": f"plan {plan_id} not found"}
    with open(plan_file, encoding="utf-8") as f:
        plan = json.load(f)
    root = ensure_dirs()
    team_id = team_id or f"team-{time.strftime('%Y%m%d-%H%M%S')}-{time.time_ns() % 1000000}"
    team_file = root / "teams" / f"{team_id}.json"
    team_data = {
        "team_id": team_id,
        "task": plan["task"],
        "description": plan["description"],
        "plan_id": plan_id,
        "max_agents": plan["optimal_agents"],
        "phase": "launching",
        "agents": []
    }
    for subtask in plan["subtasks"]:
        team_data["agents"].append({
            "id": subtask["agent_id"],
            "role": subtask["role"],
            "domain": subtask["domain"],
            "status": "pending",
            "progress": "0%",
            "last_heartbeat": None,
            "error_message": None
        })
    # P1-FIX: 写独立状态文件 — team JSON 仅作初始快照（_snapshot=true），之后只读
    team_data["_snapshot"] = True
    team_data["_snapshot_at"] = time.strftime("%Y-%m-%dT%H:%M:%S+08:00")
    with open(team_file, "w", encoding="utf-8") as f:
        json.dump(team_data, f, ensure_ascii=False, indent=2)

    # P1-FIX: 写入每个 agent 的独立状态文件
    for agent in team_data["agents"]:
        _write_agent_status_file(team_id, agent["id"], agent)


    # 启动 Hub（后台线程）
    agent_ids = [s["agent_id"] for s in plan["subtasks"]]
    hub = get_or_create_hub(team_id, agent_ids)

    # 广播讨论开始（如果有 full_discussion）
    if plan.get("use_full_discussion"):
        hub.broadcast("system", {"content": "discussion_started", "round": 1})
        team_data["discussion_active"] = True
        with open(team_file, "w", encoding="utf-8") as f:
            json.dump(team_data, f, ensure_ascii=False, indent=2)

    # P1-FIX: 2026-06-07 — 启动 health-monitor 后台守护线程
    _start_health_monitor(team_id)

    # P1-FIX: 2026-06-07 — event-log: launch
    _log_event(team_id, "launch", {
        "agent_count": len(team_data["agents"]),
        "plan_id": plan_id,
    })

    return {"team_id": team_id, "plan": plan, "agents": team_data["agents"], "hub_active": hub.is_active}

def update_agent_status(team_id, agent_id, status_text="in_progress", progress=None, findings_path=None, timed_out=False, error_message=None, heartbeat=None):
    """Update agent status in team file. Thread-safe with file locking.
    
    P1-FIX: 优先写入独立状态文件（{team_id}/status/{agent_id}.json），
    避免多 agent 同时写 team JSON 时的写竞争。
    """
    status_dir = _get_team_status_dir(team_id)
    
    if status_dir.exists():
        # P1-FIX: 新模式 — 写独立文件，不锁 JSON
        # 读当前状态（优先独立文件，其次 snapshot）
        agent = _read_agent_status(team_id, agent_id)
        if agent is None:
            sf = TEAM_BRAIN_ROOT / "teams" / f"{team_id}.json"
            if sf.exists():
                with open(sf, encoding="utf-8") as f:
                    snapshot = json.load(f)
                agent = next((a for a in snapshot.get("agents", []) if a["id"] == agent_id), {"id": agent_id})
            else:
                return {"error": "team not found"}
        
        # 更新字段
        agent["status"] = status_text
        if progress is not None:
            agent["progress"] = progress
        if heartbeat is not None:
            agent["last_heartbeat"] = heartbeat
        if findings_path is not None:
            agent["findings"] = findings_path
        if error_message is not None:
            agent["error_message"] = error_message
            # Auto-decide on error + self-heal repair
            retry_count = 0
            decision = call_auto_decider(error_message, retry_count)
            agent["auto_decision"] = decision
            healer = SelfHeal(team_id, agent_id)
            heal_result = healer.handle_error(error_message)
            agent["self_heal_result"] = {
                "fix_success": heal_result["fix_success"],
                "fix_action": heal_result["fix_action"],
                "should_continue": heal_result["should_continue"]
            }
        if timed_out:
            agent["status"] = "timed_out"
        
        _write_agent_status_file(team_id, agent_id, agent)

        # P1-FIX: 2026-06-07 — event-log: agent 状态事件
        _final_status = agent["status"]
        if _final_status == "done":
            elapsed = 0
            _hb = agent.get("last_heartbeat")
            if _hb:
                try:
                    _hb_str = str(_hb).replace("Z", "+00:00")
                    if "T" in _hb_str and "+" not in _hb_str and "Z" not in _hb_str:
                        _hb_str += "+08:00"
                    elapsed = int(time.time() - datetime.fromisoformat(_hb_str).timestamp())
                except (ValueError, TypeError):
                    pass
            _fh = ""
            _fp = agent.get("findings")
            if _fp:
                _fpath = Path(_fp)
                if _fpath.exists():
                    import hashlib
                    _fh = hashlib.sha256(_fpath.read_bytes()).hexdigest()[:12]
            _log_event(team_id, "agent_done", {
                "agent_id": agent_id,
                "elapsed_sec": elapsed,
                "findings_hash": _fh,
            })
        elif "failed" in _final_status or _final_status == "timed_out":
            _log_event(team_id, "agent_failed", {
                "agent_id": agent_id,
                "error": agent.get("error_message", _final_status),
            })
        elif _final_status not in ("pending",) and status_text not in ("pending",):
            # 首次从 pending 切换到非 pending → 记录 started
            if agent.get("_started_at") is None:
                agent["_started_at"] = datetime.utcnow().isoformat() + "Z"
                _write_agent_status_file(team_id, agent_id, agent)
            _log_event(team_id, "agent_started", {
                "agent_id": agent_id,
            })

        return {"ok": True, "team_id": team_id, "agent_id": agent_id, "status_source": "independent_files"}
    
    # 向后兼容：旧模式 — 使用文件锁写 team JSON
    sf = TEAM_BRAIN_ROOT / "teams" / f"{team_id}.json"
    if not sf.exists():
        return {"error": "team not found"}
    # P0-FIX: 打开 JSON 在 acquire_lock 之后，确保读写都在锁保护下
    lock_file = acquire_lock(str(sf) + '.lock')
    try:
        with open(sf, encoding="utf-8") as f:
            status = json.load(f)
        for agent in status["agents"]:
            if agent["id"] == agent_id:
                agent["status"] = status_text
                if progress is not None:
                    agent["progress"] = progress
                if heartbeat is not None:
                    agent["last_heartbeat"] = heartbeat
                if findings_path is not None:
                    agent["findings"] = findings_path
                if error_message is not None:
                    agent["error_message"] = error_message
                    retry_count = 0
                    decision = call_auto_decider(error_message, retry_count)
                    agent["auto_decision"] = decision
                    healer = SelfHeal(team_id, agent_id)
                    heal_result = healer.handle_error(error_message)
                    agent["self_heal_result"] = {
                        "fix_success": heal_result["fix_success"],
                        "fix_action": heal_result["fix_action"],
                        "should_continue": heal_result["should_continue"]
                    }
                if timed_out:
                    agent["status"] = "timed_out"
                break
        with open(sf, "w", encoding="utf-8") as f:
            json.dump(status, f, ensure_ascii=False, indent=2)

        # P1-FIX: 2026-06-07 — event-log: agent 状态事件（旧模式）
        _final_status = agent["status"] if status_text else ""
        if _final_status == "done":
            _log_event(team_id, "agent_done", {
                "agent_id": agent_id,
                "elapsed_sec": 0,
                "findings_hash": "",
            })
        elif "failed" in _final_status or _final_status == "timed_out":
            _log_event(team_id, "agent_failed", {
                "agent_id": agent_id,
                "error": error_message or _final_status,
            })
        elif _final_status not in ("pending",):
            _log_event(team_id, "agent_started", {
                "agent_id": agent_id,
            })
    finally:
        if lock_file:
            release_lock(lock_file)
    return {"ok": True, "team_id": team_id, "agent_id": agent_id, "status_source": "legacy_json"}

def get_team_status(team_id=None):
    """Get team status. If team_id not provided, return all teams.
    
    P1-FIX: 从独立状态文件（{team_id}/status/*.json）读取最新状态，
    与 team JSON snapshot 合并后返回。
    """
    teams_dir = TEAM_BRAIN_ROOT / "teams"
    if not teams_dir.exists():
        return {}
    if team_id is not None:
        team_file = teams_dir / f"{team_id}.json"
        if not team_file.exists():
            return {"error": f"team {team_id} not found"}
        with open(team_file, encoding="utf-8") as fp:
            team_data = json.load(fp)
        # P1-FIX: 合并独立状态
        return _merge_team_with_status(team_data, team_id)
    teams = {}
    for f in teams_dir.glob("*.json"):
        with open(f, encoding="utf-8") as fp:
            team_data = json.load(fp)
            # P1-FIX: 合并独立状态
            tid = f.stem
            teams[tid] = _merge_team_with_status(team_data, tid)
    return teams

def generate_synthesis(team_id):
    """Generate structured synthesis with conflict detection and consensus/disagreement annotation.

    P1-FIX: 2026-06-07 — structured-synthesis: from simple cat to structured merge
    + conflict detection via debates/ directory scan.
    """
    root = TEAM_BRAIN_ROOT
    team = get_team_status(team_id)
    if not team or "error" in team:
        return {"error": f"team {team_id} not found"}

    # 1. Collect all findings
    findings = []
    for agent in team.get("agents", []):
        if agent.get("findings"):
            fp = Path(agent["findings"])
            if fp.exists():
                findings.append({
                    "agent_id": agent["id"],
                    "domain": agent.get("domain", ""),
                    "role": agent.get("role", ""),
                    "path": fp,
                    "content": fp.read_text(encoding="utf-8")
                })

    # 2. Scan debates/ directory
    debates_dir = root / "debates"
    debate_files = sorted(debates_dir.glob(f"{team_id}-debate-*.md")) if debates_dir.exists() else []
    debate_contents = []
    for df in debate_files:
        debate_contents.append({
            "path": df,
            "content": df.read_text(encoding="utf-8")
        })

    # 3. Build structured report
    synthesis = "# 团队综合分析报告\n\n"
    synthesis += f"**任务**: {team.get('task', '')}\n\n"
    synthesis += f"**团队**: {team_id}\n\n"

    # 3a. Consensus points
    synthesis += "## 共识点\n\n"
    if findings:
        seen_topics = set()
        for f in findings:
            lines = f["content"].strip().split("\n")
            for line in lines:
                clean = line.strip().lstrip("-*# ")
                if not clean or clean.startswith("```"):
                    continue
                topic_key = clean[:60].lower().strip()
                if topic_key not in seen_topics:
                    seen_topics.add(topic_key)
                    trunc = clean[:150] + "..." if len(clean) > 150 else clean
                    synthesis += f"- **{f['agent_id']}** ({f['domain']}): {trunc}\n"
            synthesis += "\n"
    else:
        synthesis += "- 无 findings 文件\n\n"

    # 3b. Disagreement points
    synthesis += "## 分歧点\n\n"
    if debate_contents:
        for d in debate_contents:
            rel_path = d["path"].relative_to(root)
            synthesis += f"- debate 文件: `{rel_path}`\n"
            first_line = d["content"].strip().split("\n")[0][:120]
            synthesis += f"  - 摘要: {first_line}\n\n"
    else:
        synthesis += "- 未发现辩论文件，各 agent 观点一致或未触发辩论\n\n"

    # 3c. Per-agent findings summary
    synthesis += "## 各 agent 发现摘要\n\n"
    for f in findings:
        content_lower = f["content"].lower()
        has_data = any(w in content_lower for w in ["数据", "数据源", "统计", "报告", "研报", "财报", "据"])
        has_analysis = any(w in content_lower for w in ["分析", "评估", "判断", "结论", "建议"])
        if has_data and has_analysis:
            strength = "🟢"
        elif has_data or has_analysis:
            strength = "🟡"
        else:
            strength = "🔴"

        synthesis += f"### {f['agent_id']} ({f['domain']})\n\n"
        synthesis += f"- 证据强度: {strength}\n\n"
        synthesis += f"{f['content']}\n\n"

    # 3d. Uncertainties
    synthesis += "## 未确定事项\n\n"
    uncertainty_found = False
    for f in findings:
        uncertainty_lines = [l for l in f["content"].split("\n")
                           if any(w in l.lower() for w in ["不确定", "风险", "未知", "可能", "或许", "有待验证", "需要进一步"])]
        for ul in uncertainty_lines[:3]:
            clean = ul.strip().lstrip("-* ")
            if clean and len(clean) > 5:
                trunc = clean[:150] + "..." if len(clean) > 150 else clean
                synthesis += f"- ({f['agent_id']}) {trunc}\n"
                uncertainty_found = True
    if not uncertainty_found:
        synthesis += "- 各 agent 未明确列出不确定事项\n"
    synthesis += "\n"

    # 3e. Next steps
    synthesis += "## 下一步建议\n\n"
    suggestion_found = False
    for f in findings:
        suggestion_lines = [l for l in f["content"].split("\n")
                          if any(w in l.lower() for w in ["建议", "推荐", "下一步", "后续", "需要关注", "action", "todo", "TODO"])]
        for sl in suggestion_lines[:2]:
            clean = sl.strip().lstrip("-* ")
            if clean and len(clean) > 5:
                trunc = clean[:150] + "..." if len(clean) > 150 else clean
                synthesis += f"- ({f['agent_id']}) {trunc}\n"
                suggestion_found = True
    if not suggestion_found:
        synthesis += "- 各 agent 未明确列出下一步建议\n"

    # 4. Write file
    out_file = root / "synthesis" / f"{team_id}-final.md"
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(synthesis, encoding="utf-8")

    # P1-FIX: 2026-06-07 — event-log: synthesis
    local_time_sec = 0
    _created = team.get("_snapshot_at", "")
    if _created:
        try:
            _c_ts = datetime.fromisoformat(_created.replace("Z", "+00:00")).timestamp()
            local_time_sec = int(time.time() - _c_ts)
        except (ValueError, TypeError):
            pass
    _agent_count = len(team.get("agents", []))
    _debate_files = [str(d["path"].relative_to(root)) for d in debate_contents]
    _debate_count = len(_debate_files)
    _log_event(team_id, "synthesis", {
        "local_time_sec": local_time_sec,
        "agent_count": _agent_count,
        "debate_count": _debate_count,
    })

    return {
        "synthesis_path": str(out_file),
        "team": team,
        "findings_count": len(findings),
        "debate_files": _debate_files,
        "note": "structured synthesis (P1-FIX: 2026-06-07)"
    }

def launch_team(topic, description, max_agents=DEFAULT_MAX_AGENTS, timeout_per_agent=DEFAULT_TIMEOUT_PER_AGENT, full_discussion=False):
    """Launch team (with intelligent planning).

    Args:
        full_discussion: if True, force-enable Pre-task Discussion + Consensus Check phases.
                        Otherwise auto-detect from complexity.
    """
    root = ensure_dirs()
    complexity = estimate_complexity(topic, description)
    optimal_agents = min(max_agents, max(2, complexity["domain_count"] + 1))
    use_full = full_discussion or complexity.get("use_full_discussion", False)
    plan = {
        "plan_id": f"plan-{time.strftime('%Y%m%d-%H%M%S')}-{time.time_ns() % 1000000}",
        "task": topic,
        "description": description,
        "optimal_agents": optimal_agents,
        "estimated_total_minutes": complexity["estimated_minutes"],
        "estimated_with_margin_minutes": int(complexity["estimated_minutes"] * 1.3),
        "use_full_discussion": use_full,
        "complexity_score": complexity["complexity_score"],
        "subtasks": []
    }
    domains = ["宏观", "行业", "估值", "技术", "风险", "财务", "竞争", "市场"]
    for i in range(optimal_agents):
        domain = domains[i % len(domains)]
        plan["subtasks"].append({
            "agent_id": f"agent-{i+1}",
            "domain": domain,
            "role": f"{domain}分析师",
            "timeout_seconds": min(timeout_per_agent, complexity["estimated_minutes"] * 60 // optimal_agents),
            "key_questions": _get_domain_questions(domain, topic, description)
        })
    plan_file = root / "plans" / f"{plan['plan_id']}.json"
    with open(plan_file, "w", encoding="utf-8") as f:
        json.dump(plan, f, ensure_ascii=False, indent=2)
    result = launch_with_plan(plan["plan_id"])
    result["plan"] = plan
    result["use_full_discussion"] = use_full
    if use_full:
        result["phases"] = ["pre_task_discussion", "analysis", "review", "consensus_check"]
        result["note"] = "Full discussion mode: Pre-task + Consensus Check enabled. Experts will align before and validate after execution."
    else:
        result["phases"] = ["analysis", "review"]
        result["note"] = "Fast mode: no Pre-task Discussion or Consensus Check. Use --full-discussion to enable."
    return result

def run_synthesis_check(team_id, final_report_path, timeout=300):
    """Run expert consensus check before final delivery."""
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("synthesis_check", str(SCRIPT_DIR / "synthesis-check.py"))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.collect_expert_consensus(team_id, final_report_path, timeout)
    except Exception as e:
        return {"error": f"synthesis-check failed: {e}", "team_id": team_id}


# ════════════════════════════════════════════════════════════
# P1-FIX: 2026-06-07 — health-monitor 自动清理兜底
# ════════════════════════════════════════════════════════════

def _health_monitor_loop(team_id: str, interval: int = 30):
    """P1-FIX: 后台监控线程：每 interval 秒检查一次 agent 心跳。
    超时 PERIODIC_CHECK_TIMEOUT_SEC 无心跳的 agent 自动标记为 timed_out。
    所有 agent done/failed/timed_out 后写最终状态报告。
    作为守护线程启动，主进程退出时自动停止。
    """
    from datetime import datetime, timezone

    health_log_dir = TEAM_BRAIN_ROOT / "logs" / team_id
    health_log_dir.mkdir(parents=True, exist_ok=True)
    health_log = health_log_dir / "health.log"

    def _log(msg: str):
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            with open(health_log, "a", encoding="utf-8") as f:
                f.write(f"[{ts}] {msg}\n")
        except Exception:
            pass

    _log(f"health-monitor started (interval={interval}s, timeout={PERIODIC_CHECK_TIMEOUT_SEC}s)")

    while True:
        threading.Event().wait(interval)

        status_dir = _get_team_status_dir(team_id)
        if not status_dir.exists():
            _log(f"status dir not found: {status_dir}, stopping monitor")
            break

        agent_files = list(status_dir.glob("*.json"))
        if not agent_files:
            _log("no agent status files found, stopping monitor")
            # 不 break，等后续 agent 创建
            continue

        now_ts = time.time()
        all_terminal = True

        for af in agent_files:
            try:
                with open(af, encoding="utf-8") as f:
                    agent = json.load(f)
            except Exception as e:
                _log(f"cannot read {af.name}: {e}")
                continue

            agent_id = agent.get("id", af.stem)
            status = agent.get("status", "")
            heartbeat = agent.get("last_heartbeat", None)

            # 已终结的 agent 跳过
            if status in ("done", "failed_with_error", "timed_out"):
                continue

            all_terminal = False

            # 检查心跳超时
            if heartbeat is not None:
                try:
                    if isinstance(heartbeat, str):
                        # 解析 ISO 格式时间戳
                        hb_str = heartbeat.replace("Z", "+00:00")
                        # 兼容旧格式 "2026-05-18T19:28:02" 无时区
                        if "T" in hb_str and "+" not in hb_str and "Z" not in hb_str:
                            hb_str += "+08:00"
                        heartbeat_ts = datetime.fromisoformat(hb_str).timestamp()
                    else:
                        heartbeat_ts = float(heartbeat)
                except (ValueError, TypeError):
                    _log(f"cannot parse heartbeat for {agent_id}: {heartbeat!r}")
                    continue

                elapsed = now_ts - heartbeat_ts
                if elapsed > PERIODIC_CHECK_TIMEOUT_SEC:
                    agent["status"] = "timed_out"
                    _write_agent_status_file(team_id, agent_id, agent)
                    _log(f"AGENT TIMEOUT: {agent_id} — no heartbeat for {elapsed:.0f}s")
                    # P1-FIX: 2026-06-07 — event-log: agent 心跳超时
                    _log_event(team_id, "agent_timed_out", {
                        "agent_id": agent_id,
                        "since_last_heartbeat_sec": int(elapsed),
                    })

        if all_terminal:
            _log("all agents terminal — health monitor stopping")
            break

    _log("health-monitor stopped")


def _start_health_monitor(team_id: str, interval: int = 30):
    """P1-FIX: 以守护线程启动 health-monitor，不阻塞调用方"""
    t = threading.Thread(
        target=_health_monitor_loop,
        args=(team_id, interval),
        daemon=True,
        name=f"health-monitor-{team_id}",
    )
    t.start()


# P1-FIX: 2026-06-07 — event-log: 结构化事件日志工具函数
def _log_event(team_id: str, event_type: str, data: dict):
    """写结构化日志事件到 logs/{team_id}/events.jsonl"""
    log_dir = TEAM_BRAIN_ROOT / "logs" / team_id
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "events.jsonl"
    entry = {
        "ts": datetime.utcnow().isoformat() + "Z",
        "event": event_type,
        "team_id": team_id,
        **data
    }
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


# P2-FIX: 2026-06-07 — metrics: 基于 events.jsonl 生成统计报表
def _compute_metrics(team_id: str = None) -> dict:
    """计算团队统计报表。优先读 events.jsonl，回退到扫 team JSON + status/ 目录。"""
    import hashlib
    from statistics import median

    logs_dir = TEAM_BRAIN_ROOT / "logs"
    teams_dir = TEAM_BRAIN_ROOT / "teams"

    target_teams = []
    if team_id:
        target_teams = [team_id]
    else:
        if logs_dir.exists():
            target_teams = [d.name for d in logs_dir.iterdir() if d.is_dir()]
        if not target_teams:
            # 回退：从 teams/ 目录获取
            if teams_dir.exists():
                target_teams = [f.stem for f in teams_dir.glob("*.json")]

    teams_detail = []
    total_launches = 0
    total_completed = 0
    total_failed = 0
    total_debates = 0
    all_elapsed = []

    for tid in target_teams:
        events_file = logs_dir / tid / "events.jsonl"
        if events_file.exists():
            # 优先：从 events.jsonl 读取
            launches = 0
            completed = 0
            failed = 0
            debates = 0
            agents_total = 0
            agents_done = 0
            agents_failed = 0
            elapsed_list = []

            with open(events_file, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        ev = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    et = ev.get("event", "")
                    if et == "launch":
                        launches += 1
                        agents_total = ev.get("agent_count", 0)
                    elif et == "agent_done":
                        completed += 1
                        agents_done += 1
                        el = ev.get("elapsed_sec", 0)
                        if el > 0:
                            elapsed_list.append(el)
                    elif et == "agent_failed":
                        failed += 1
                        agents_failed += 1
                    elif et == "agent_timed_out":
                        failed += 1
                        agents_failed += 1
                    elif et == "synthesis":
                        debates = ev.get("debate_count", 0)

            # P2-FIX: 2026-06-07 — metrics-fallback-merge
            # 如果 events.jsonl 数据不全（无 launch 事件或无 agents），从 team JSON 补数据
            if launches == 0 or agents_total == 0:
                team_file = teams_dir / f"{tid}.json"
                if team_file.exists():
                    with open(team_file, encoding="utf-8") as f:
                        team_data = json.load(f)
                    if agents_total == 0:
                        agents_total = len(team_data.get("agents", []))
                    # P2-FIX: 2026-06-07 — metrics-fallback-merge: 兼容旧团队 "completed" 状态
                    if agents_done == 0:
                        agents_done = sum(1 for a in team_data.get("agents", []) if a.get("status") in ("done", "completed"))
                    if agents_failed == 0:
                        agents_failed = sum(1 for a in team_data.get("agents", []) if a.get("status") in ("failed_with_error", "timed_out", "failed"))
                    if launches == 0 and agents_total > 0:
                        launches = 1
                    if not elapsed_list:
                        created_str = team_data.get("created_at", team_data.get("_snapshot_at", ""))
                        completed_str = team_data.get("completed_at", "")
                        if created_str and completed_str:
                            try:
                                c_ts = datetime.fromisoformat(created_str.replace("Z", "+00:00")).timestamp()
                                d_ts = datetime.fromisoformat(completed_str.replace("Z", "+00:00")).timestamp()
                                elapsed_list.append(int(d_ts - c_ts))
                            except (ValueError, TypeError):
                                pass

            total_launches += launches
            # P2-FIX: 2026-06-07 — metrics-fallback-merge: 用 agents_done 覆盖 completed（fallback 已补数据）
            total_completed += agents_done
            total_failed += agents_failed
            total_debates += debates
            all_elapsed.extend(elapsed_list)

            # 计算单个团队耗时
            team_elapsed = int(median(elapsed_list)) if elapsed_list else 0

            teams_detail.append({
                "team_id": tid,
                "agents": agents_total,
                "completed": agents_done,
                "failed": agents_failed,
                "elapsed_sec": team_elapsed,
                "debates": debates,
            })
        else:
            # 回退策略：扫 team JSON + status/ 目录
            team_file = teams_dir / f"{tid}.json"
            if not team_file.exists():
                continue
            with open(team_file, encoding="utf-8") as f:
                team_data = json.load(f)

            agents_total = len(team_data.get("agents", []))
            agents_done = 0
            agents_failed = 0
            status_dir = _get_team_status_dir(tid)
            if status_dir.exists():
                for sf in status_dir.glob("*.json"):
                    try:
                        with open(sf, encoding="utf-8") as f:
                            ag = json.load(f)
                        s = ag.get("status", "")
                        if s == "done":
                            agents_done += 1
                        elif s in ("failed_with_error", "timed_out", "failed"):
                            agents_failed += 1
                    except Exception:
                        pass
            else:
                # 从 team JSON 读
                for a in team_data.get("agents", []):
                    s = a.get("status", "")
                    if s == "done":
                        agents_done += 1
                    elif s in ("failed_with_error", "timed_out", "failed"):
                        agents_failed += 1

            total_launches += 1
            total_completed += agents_done
            total_failed += agents_failed

            # created_at / completed_at 时间差
            created_str = team_data.get("created_at", team_data.get("_snapshot_at", ""))
            elapsed_sec = 0
            if created_str:
                completed_str = team_data.get("completed_at", "")
                try:
                    c_ts = datetime.fromisoformat(created_str.replace("Z", "+00:00")).timestamp()
                    if completed_str:
                        d_ts = datetime.fromisoformat(completed_str.replace("Z", "+00:00")).timestamp()
                        elapsed_sec = int(d_ts - c_ts)
                except (ValueError, TypeError):
                    pass

            teams_detail.append({
                "team_id": tid,
                "agents": agents_total,
                "completed": agents_done,
                "failed": agents_failed,
                "elapsed_sec": elapsed_sec,
                "debates": 0,
            })

    total_agents = total_completed + total_failed
    success_rate = "0%"
    if total_agents > 0:
        success_rate = f"{int(total_completed / total_agents * 100)}%"

    avg_time = int(sum(all_elapsed) / len(all_elapsed)) if all_elapsed else 0
    sorted_elapsed = sorted(all_elapsed)
    p50 = median(sorted_elapsed) if sorted_elapsed else 0
    p95 = sorted_elapsed[int(len(sorted_elapsed) * 0.95)] if sorted_elapsed else 0

    return {
        "teams": len(teams_detail),
        "total_launches": total_launches,
        "success_rate": success_rate,
        "avg_completion_time_sec": avg_time,
        "p50": int(p50),
        "p95": int(p95),
        "agent_failures": total_failed,
        "debates_created": total_debates,
        "teams_detail": teams_detail,
    }


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    cmd = sys.argv[1]
    if cmd == "launch":
        topic = sys.argv[2] if len(sys.argv) > 2 else ""
        description = sys.argv[3] if len(sys.argv) > 3 else ""
        full_discussion = "--full-discussion" in sys.argv
        result = launch_team(topic, description, full_discussion=full_discussion)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif cmd == "plan":
        task = sys.argv[2] if len(sys.argv) > 2 else ""
        description = sys.argv[3] if len(sys.argv) > 3 else ""
        result = plan_task(task, description)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif cmd == "status":
        team_id = sys.argv[2] if len(sys.argv) > 2 else None
        result = get_team_status(team_id)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif cmd == "synthesis":
        team_id = sys.argv[2] if len(sys.argv) > 2 else None
        result = generate_synthesis(team_id)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif cmd == "synthesis-check":
        team_id = sys.argv[2] if len(sys.argv) > 2 else None
        final_report_path = sys.argv[3] if len(sys.argv) > 3 else None
        if not team_id or not final_report_path:
            print("Usage: team-brain.py synthesis-check <team_id> <final_report_path> [--timeout=300]")
            sys.exit(1)
        timeout = 300
        for a in sys.argv[4:]:
            if a.startswith("--timeout="):
                timeout = int(a.split("=", 1)[1])
        result = run_synthesis_check(team_id, final_report_path, timeout)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif cmd == "metrics":
        team_id = sys.argv[2] if len(sys.argv) > 2 else None
        result = _compute_metrics(team_id)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif cmd == "debates":
        # P1-FIX: 2026-06-07 — debate-force: 查看团队辩论文件列表
        team_id = sys.argv[2] if len(sys.argv) > 2 else None
        if not team_id:
            print("Usage: team-brain.py debates <team_id>")
            sys.exit(1)
        debates_dir = TEAM_BRAIN_ROOT / "debates"
        if not debates_dir.exists():
            print(json.dumps({"debates": [], "note": "debates directory not found"}, ensure_ascii=False, indent=2))
            sys.exit(0)
        matching = sorted(debates_dir.glob(f"{team_id}-debate-*.md"))
        result = [str(f.relative_to(TEAM_BRAIN_ROOT)) for f in matching]
        print(json.dumps({"team_id": team_id, "debates": result}, ensure_ascii=False, indent=2))
    elif cmd == "health-monitor":
        team_id = sys.argv[2] if len(sys.argv) > 2 else None
        if not team_id:
            print("Usage: team-brain.py health-monitor <team_id> [interval_seconds]")
            sys.exit(1)
        interval = int(sys.argv[3]) if len(sys.argv) > 3 else 30
        print(json.dumps({
            "command": "health-monitor",
            "team_id": team_id,
            "interval": interval,
            "started": True,
        }, ensure_ascii=False, indent=2))
        # 在前端 JSON 输出后启动阻塞循环，保持进程存活
        _health_monitor_loop(team_id, interval)
    else:
        print(f"Unknown command: {cmd}")
        print(__doc__)
        sys.exit(1)

if __name__ == "__main__":
    main()