#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
launch-and-spawn.py - team-brain.py launch + 自动 spawn 子代理 包装器

P0 修复：team-brain.py launch 后没有 spawn 子代理，agent 永远 pending。
本包装器职责：
  1. 调 team-brain.py launch 准备数据（plan + team 文件）
  2. 读 plan.json 拿各 agent 角色/domain
  3. DOMAIN_AGENT_MAP 把 team-brain 硬编码金融角色映射到真实 OpenClaw agent
  4. TASK_KEYWORD_AGENT 用任务标题做二次 override
  5. 生成结构化 spawn plan（prompt + target_agent + findings_path）
  6. 更新 team-{id}.json 把 agents 状态从 pending 改为 running
  7. 返回 JSON 给调用方，调用方（持有 sessions_spawn 工具的 agent）按 plan 派活

调用方式：
    python launch-and-spawn.py "<topic>" "<description>" [max_agents] [--dry-run] [--auto-monitor] [--full-discussion]

输出：JSON to stdout，含 spawn_plan 数组（每条含 target_agent / prompt / findings_path）
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# Force UTF-8 stdout/stderr on Windows (avoid GBK 乱码)
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:  # pragma: no cover
        pass

SCRIPT_DIR = Path(__file__).parent.resolve()
TEAM_BRAIN_PY = SCRIPT_DIR / "team-brain.py"
TEAM_BRAIN_ROOT = (SCRIPT_DIR.parent.parent / "shared" / "team-brain").resolve()

# === 关键映射表 ===

# domain → 真实 OpenClaw agent（team-brain 硬编码金融角色 → 真实可用 agent）
DOMAIN_AGENT_MAP: dict[str, str] = {
    "宏观": "q",       # 量化小Q 处理宏观分析
    "行业": "q",
    "估值": "q",
    "技术": "pycoder", # 全栈开发者
    "风险": "q",
    "财务": "caiwu",   # 财眼
    "竞争": "pycoder",
    "市场": "q",
    # 兼容旧版（hospital-mall 等用了品类/配送/营销/竞争等自定义 domain）
    "品类策略": "pycoder",
    "配送竞争力": "pycoder",
    "营销策略": "wepub",
    "竞争策略": "pycoder",
}

# 任务关键词 → agent 的兜底映射（标题/描述里出现关键词时强制 override）
# 用 re.search 匹配，所以支持 | 分隔的多关键词
TASK_KEYWORD_AGENT: dict[str, str] = {
    r"代码|脚本|实现|debug|调试|编程|开发|封装|重构|爬虫|测试|函数|接口|API": "pycoder",
    r"改写|润色|公众号|标题|文章|推文|文案|撰写|内容编辑|营销文案|写作": "wepub",
    r"回测|因子|策略|量化|选股|择时|动量|仓位|基金|股票分析|投资分析|估值模型|金融": "q",
    r"对账|算账|税务|报税|发票|凭证|汇算|会计|记账|做账|工资|社保|破产清算|财务": "caiwu",
    r"合同|法律意见|合规|FCPA|诉讼|仲裁|破产申请|劳动仲裁|数据出境|法律|法务": "legal",
}

DEFAULT_AGENT = "pycoder"

# P1-FIX: 2026-06-07 — event-log: 写入 events.jsonl 的辅助函数
def _log_events_jsonl(team_id: str, event_type: str, data: dict):
    """写结构化日志事件到共享 logs/{team_id}/events.jsonl"""
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


# P1-FIX: 2026-06-07 — health-monitor
PERIODIC_CHECK_TIMEOUT_SEC = 120
STUCK_TEAM_CUTOFF_HOURS = 24

# 监控相关常量
PERIODIC_CHECK_TIMEOUT_SEC = 120  # team-brain-protocol 规定的超时阈值
SPAWN_PERIODIC_CHECK_LOOP_SLEEP = 5

# P0-FIX: 2026-06-07 — --run 模式常量
SPAWN_RUNS_DIR = TEAM_BRAIN_ROOT / "runs"


# P0-FIX: 新增 — spawn 执行记录数据结构
def _create_spawn_manifest(
    team_id: str,
    plan_id: str,
    spawn_plan: list[dict],
) -> dict:
    """创建 spawn execution manifest"""
    items = []
    for sp in spawn_plan:
        items.append({
            "agent_id": sp["agent_id"],
            "target_agent": sp["target_agent"],
            "domain": sp["domain"],
            "role": sp["role"],
            "timeout_seconds": sp["timeout_seconds"],
            "findings_path": sp["findings_path"],
            "spawn_label": sp["spawn_label"],
            "prompt": sp["prompt"],
            "status": "pending",
            "result": None,
            "error": None,
            "started_at": None,
            "completed_at": None,
        })
    return {
        "manifest_version": 1,
        "team_id": team_id,
        "plan_id": plan_id,
        "status": "pending",
        "created_at": datetime.now().isoformat(),
        "completed_at": None,
        "total_items": len(items),
        "completed_items": 0,
        "failed_items": 0,
        "items": items,
    }


def _write_spawn_manifest(team_id: str, manifest: dict) -> str:
    """写入 spawn manifest 文件，返回路径"""
    manifest_dir = SPAWN_RUNS_DIR / team_id
    manifest_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = manifest_dir / "manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    return str(manifest_path)


def _write_spawn_request(team_id: str, item: dict) -> str:
    """写入单个 spawn request 文件（主 agent 可读取并执行）"""
    request_dir = SPAWN_RUNS_DIR / team_id / "requests"
    request_dir.mkdir(parents=True, exist_ok=True)
    request_path = request_dir / f"{item['agent_id']}.json"
    with open(request_path, "w", encoding="utf-8") as f:
        json.dump({
            "request_type": "sessions_spawn",
            "team_id": team_id,
            "agent_id": item["agent_id"],
            "target_agent": item["target_agent"],
            "spawn_label": item["spawn_label"],
            "prompt": item["prompt"],
            "findings_path": item["findings_path"],
            "timeout_seconds": item["timeout_seconds"],
            "status": "pending",
        }, f, ensure_ascii=False, indent=2)
    return str(request_path)


def _write_final_spawn_report(team_id: str, manifest: dict) -> str:
    """写入最终 spawn 执行报告"""
    report_dir = SPAWN_RUNS_DIR / team_id
    report_dir.mkdir(parents=True, exist_ok=True)
    
    # 更新 manifest 状态
    manifest["completed_at"] = datetime.now().isoformat()
    
    report = {
        "team_id": team_id,
        "plan_id": manifest["plan_id"],
        "status": manifest["status"],
        "created_at": manifest["created_at"],
        "completed_at": manifest["completed_at"],
        "total_items": manifest["total_items"],
        "completed_items": manifest["completed_items"],
        "failed_items": manifest["failed_items"],
        "results": [],
    }
    for item in manifest["items"]:
        report["results"].append({
            "agent_id": item["agent_id"],
            "target_agent": item["target_agent"],
            "status": item["status"],
            "error": item["error"],
            "started_at": item["started_at"],
            "completed_at": item["completed_at"],
        })
    
    report_path = report_dir / "final_report.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    
    # 同步更新 manifest
    with open(report_dir / "manifest.json", "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    
    return str(report_path)


# ════════════════════════════════════════════════════════════
# P1-FIX: 2026-06-07 — health-monitor + clean-stuck
# ════════════════════════════════════════════════════════════

def _start_health_monitor_process(team_id: str) -> dict:
    """P1-FIX: 以守护线程启动 health-monitor（不阻塞 CLI 返回）"""
    import threading
    
    def _run():
        team_brain_py = SCRIPT_DIR / "team-brain.py"
        if not team_brain_py.exists():
            return
        try:
            proc = subprocess.Popen(
                [sys.executable, str(team_brain_py), "health-monitor", team_id, "30"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                cwd=str(SCRIPT_DIR),
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
            )
            proc.wait()  # 等待子进程退出（健康监控进程退出时才返回）
        except Exception:
            pass
    
    t = threading.Thread(target=_run, daemon=True, name=f"health-monitor-spawn-{team_id}")
    t.start()
    return {"ok": True, "team_id": team_id}


def _clean_stuck_teams() -> dict:
    """P1-FIX: 扫描 teams/ 目录，标记超过 24h 的 stuck team 为 dormant

    判断条件：
    1. phase=launching 或处于非终结状态（非 completed/dormant/failed）
    2. 超过 24h 无变化（检查文件 mtime）

    操作：
    - 只标记 phase 为 dormant
    - 不删除 findings/状态文件
    """
    teams_dir = TEAM_BRAIN_ROOT / "teams"
    if not teams_dir.exists():
        return {"ok": True, "teams_checked": 0, "stuck_found": 0, "marked_dormant": 0}

    now = time.time()
    cutoff_seconds = STUCK_TEAM_CUTOFF_HOURS * 3600

    stuck_found = 0
    marked_dormant = 0
    teams_checked = 0

    for tf in teams_dir.glob("*.json"):
        teams_checked += 1
        mtime = tf.stat().st_mtime
        age = now - mtime
        if age < cutoff_seconds:
            continue  # 不够 24h

        try:
            with open(tf, encoding="utf-8") as f:
                team_data = json.load(f)
        except Exception:
            continue

        # 检查阶段/状态
        phase = team_data.get("phase", team_data.get("status", ""))
        if phase in ("completed", "dormant", "failed"):
            continue  # 已是终结状态

        stuck_found += 1

        # 标记为 dormant
        team_data["phase"] = "dormant"
        team_data["_dormant_at"] = datetime.now().isoformat()
        team_data["_dormant_reason"] = f"stuck in '{phase}' for >{STUCK_TEAM_CUTOFF_HOURS}h"

        with open(tf, "w", encoding="utf-8") as f:
            json.dump(team_data, f, ensure_ascii=False, indent=2)

        marked_dormant += 1
        print(f"[clean-stuck] marked {tf.stem} as dormant (was '{phase}', age={age/3600:.1f}h)")

    return {
        "ok": True,
        "teams_checked": teams_checked,
        "stuck_found": stuck_found,
        "marked_dormant": marked_dormant,
    }


# ---------------------------------------------------------------------------
# 纯函数：agent 选派
# ---------------------------------------------------------------------------

def select_agent_for_subtask(
    domain: str,
    task_title: str,
    description: str,
) -> tuple[str, str]:
    """根据 domain + 任务标题 选 agent

    优先级：
      1. TASK_KEYWORD_AGENT（任务标题/描述里出现关键词 → 强制 override）
      2. DOMAIN_AGENT_MAP（domain 落在已知金融角色上）
      3. DEFAULT_AGENT（兜底）

    Returns: (agent_id, reason)
    """
    text = f"{task_title} {description}"

    # Step 1: 关键词 override
    for pattern, agent_id in TASK_KEYWORD_AGENT.items():
        if re.search(pattern, text, flags=re.IGNORECASE):
            return agent_id, f"keyword_match:{pattern}"

    # Step 2: domain 映射
    if domain in DOMAIN_AGENT_MAP:
        return DOMAIN_AGENT_MAP[domain], f"domain_match:{domain}"

    # Step 3: 兜底
    return DEFAULT_AGENT, "fallback"


# ---------------------------------------------------------------------------
# 调 team-brain.py launch
# ---------------------------------------------------------------------------

def call_team_brain_launch(
    topic: str,
    description: str,
    max_agents: int = 5,
    full_discussion: bool = False,
) -> dict:
    """调 team-brain.py launch 准备数据。返回解析后的 JSON。"""
    if not TEAM_BRAIN_PY.exists():
        return {"error": f"team-brain.py not found at {TEAM_BRAIN_PY}"}

    args = [
        sys.executable,
        str(TEAM_BRAIN_PY),
        "launch",
        topic,
        description,
        str(max_agents),
    ]
    if full_discussion:
        args.append("--full-discussion")

    try:
        proc = subprocess.run(
            args,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
            cwd=str(SCRIPT_DIR),
        )
    except subprocess.TimeoutExpired:
        return {"error": "team-brain.py launch timeout (>60s)"}
    except Exception as e:
        return {"error": f"failed to run team-brain.py: {e}"}

    if proc.returncode != 0:
        return {
            "error": f"team-brain.py launch failed (rc={proc.returncode})",
            "stderr": proc.stderr[:2000] if proc.stderr else "",
        }

    stdout = proc.stdout or ""
    # 尝试整体 parse
    try:
        return json.loads(stdout)
    except json.JSONDecodeError:
        pass

    # 退化：抠第一个完整 JSON object
    match = re.search(r"\{[\s\S]*\}", stdout)
    if match:
        try:
            return json.loads(match.group(0))
        except Exception:
            pass

    return {
        "error": "failed to parse team-brain.py output as JSON",
        "stdout_head": stdout[:500],
        "stderr_head": (proc.stderr or "")[:500],
    }


# ---------------------------------------------------------------------------
# Prompt 构造（修复 team-brain.py 模板里 {{team_id}} 未替换的 bug）
# ---------------------------------------------------------------------------

def build_spawn_prompt(
    *,
    team_id: str,
    plan_id: str,
    agent_id: str,
    role: str,
    domain: str,
    task: str,
    description: str,
    timeout_s: int,
    key_questions: list[str],
) -> str:
    """构造子代理 prompt 模板（f-string 化，不再有 {{team_id}} 字面量）"""
    findings_path = f"{TEAM_BRAIN_ROOT}/findings/{domain}/{plan_id}-{agent_id}.md"
    team_file = f"{TEAM_BRAIN_ROOT}/teams/{team_id}.json"
    inbox_dir = f"{TEAM_BRAIN_ROOT}/messages/inbox/{agent_id}"
    outbox_dir = f"{TEAM_BRAIN_ROOT}/messages/outbox/{agent_id}"
    debates_dir = f"{TEAM_BRAIN_ROOT}/debates/{team_id}"

    key_qs_text = (
        "\n".join(f"- {q}" for q in key_questions)
        if key_questions
        else f"- 在 {domain} 维度上，针对任务的核心发现是什么？\n- 支撑结论的关键数据/事实是什么？"
    )

    return f"""你是团队脑子代理：{role}
- Team ID: {team_id}
- Plan ID: {plan_id}
- 你的 Agent ID: {agent_id}
- 你的 Domain: {domain}
- Timeout: {timeout_s} 秒（{timeout_s // 60} 分钟）

=== 任务 ===
{task}
{description}

=== 关键问题 ===
{key_qs_text}

=== 团队状态文件 ===
{team_file}
- 启动时先读，了解团队任务、成员、最新状态
- 执行中定期更新你自己的 status / progress / last_heartbeat
- 完成后：status=done, progress=100%, findings={findings_path}

=== 状态更新方法（重要） ===
1. 读 {team_file}（用 UTF-8 编码）
2. 找到 id={agent_id} 的 agent 条目
3. 修改 status / progress / last_heartbeat / findings 字段
4. 写回文件（用 ensure_ascii=False, indent=2）
5. 写不进去时（文件锁冲突）→ sleep 0.3s 重试 ≤3 次

=== 输出要求 ===
完成后写 findings 到：{findings_path}

=== 协议提醒 ===
- 心跳：每分钟更新一次 last_heartbeat
- 与同伴通讯：
  - 读 inbox: {inbox_dir}/
  - 写 outbox: {outbox_dir}/<msg_id>.json
- 发现问题时（与其他 agent 结论冲突）→ 在 {debates_dir}/ 写挑战文件
- 状态机：pending → running → done / failed_with_error

=== 错误处理 ===
- 状态更新写不进去（文件锁）→ sleep 0.3s 重试 ≤3 次
- 编码问题 → 统一用 UTF-8
- 超时 → 优先完成核心结论，丢弃细节
- 同一错误 >3 次 → status=failed_with_error 并写入 error_message，继续

=== 心跳判定 ===
超过 120 秒无心跳视为已挂。专注执行，不要等待协调人指令。

请开始。"""


# ---------------------------------------------------------------------------
# 状态更新
# ---------------------------------------------------------------------------

def update_team_agents_status(team_id: str, agent_updates: list[dict]) -> dict:
    """更新 team-{id}.json 把 agents 状态从 pending 改为 running

    agent_updates: [{"agent_id": "agent-1", "status": "running"}, ...]
    """
    team_file = TEAM_BRAIN_ROOT / "teams" / f"{team_id}.json"
    if not team_file.exists():
        return {"ok": False, "error": f"team file not found: {team_file}"}

    try:
        with open(team_file, encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        return {"ok": False, "error": f"failed to read team file: {e}"}

    now_iso = datetime.now().isoformat()
    update_map = {u["agent_id"]: u.get("status", "running") for u in agent_updates}
    updated = []
    for agent in data.get("agents", []):
        if agent["id"] in update_map:
            agent["status"] = update_map[agent["id"]]
            agent["last_heartbeat"] = now_iso
            updated.append(agent["id"])

    try:
        with open(team_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        return {"ok": False, "error": f"failed to write team file: {e}"}

    return {"ok": True, "updated": updated, "team_file": str(team_file)}


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------

def launch_and_spawn(
    topic: str,
    description: str,
    max_agents: int = 5,
    *,
    dry_run: bool = False,
    auto_monitor: bool = False,
    full_discussion: bool = False,
) -> dict:
    """主入口：launch + 准备 spawn plan

    Returns: dict
      {
        "ok": True,
        "team_id": "team-...",
        "plan_id": "plan-...",
        "spawn_count": N,
        "spawn_plan": [
            {
              "agent_id": "agent-1",
              "role": "...",
              "domain": "...",
              "target_agent": "pycoder",   # ← 真正要 spawn 的 agent
              "selection_reason": "domain_match:技术",
              "timeout_seconds": 600,
              "findings_path": "...",
              "spawn_label": "team-brain/<team_id>/agent-1",
              "prompt": "...",             # ← 通用 prompt 模板
              "ready_to_spawn": True,
            },
            ...
        ],
        "next_action": "iterate spawn_plan and call sessions_spawn for each",
        "team_file": "...",
      }
    """
    # 1. 调 team-brain.py launch
    if dry_run:
        # dry-run 不实际 launch，但需要 plan 数据；为测试方便，构造 mock plan
        plan = _mock_plan(topic, description, max_agents)
        launch_result = {
            "team_id": f"team-dryrun-{int(time.time())}",
            "plan": plan,
        }
    else:
        launch_result = call_team_brain_launch(topic, description, max_agents, full_discussion)
        if "error" in launch_result:
            return {
                "ok": False,
                "stage": "launch",
                "error": launch_result["error"],
                "detail": launch_result,
            }

    team_id = launch_result.get("team_id")
    plan = launch_result.get("plan")
    if not team_id or not isinstance(plan, dict):
        return {
            "ok": False,
            "stage": "parse",
            "error": "missing team_id or plan in launch result",
            "detail": launch_result,
        }

    plan_id = plan.get("plan_id")
    if not plan_id:
        return {"ok": False, "stage": "parse", "error": "missing plan_id in plan"}

    # 2. 验证 plan 文件存在（非 dry-run 模式下）
    if not dry_run:
        plan_file = TEAM_BRAIN_ROOT / "plans" / f"{plan_id}.json"
        if not plan_file.exists():
            return {
                "ok": False,
                "stage": "verify_plan",
                "error": f"plan file not found: {plan_file}",
            }

    # 3. 为每个 subtask 准备 spawn plan
    spawn_plan: list[dict] = []
    for subtask in plan.get("subtasks", []):
        agent_id = subtask.get("agent_id", "")
        domain = subtask.get("domain", "")
        role = subtask.get("role", "")
        timeout_s = int(subtask.get("timeout_seconds", 600))
        key_qs = subtask.get("key_questions", [])

        target_agent, reason = select_agent_for_subtask(domain, topic, description)

        prompt = build_spawn_prompt(
            team_id=team_id,
            plan_id=plan_id,
            agent_id=agent_id,
            role=role,
            domain=domain,
            task=topic,
            description=description,
            timeout_s=timeout_s,
            key_questions=key_qs,
        )

        findings_path = f"{TEAM_BRAIN_ROOT}/findings/{domain}/{plan_id}-{agent_id}.md"

        spawn_plan.append({
            "agent_id": agent_id,
            "role": role,
            "domain": domain,
            "target_agent": target_agent,
            "selection_reason": reason,
            "timeout_seconds": timeout_s,
            "findings_path": findings_path,
            "spawn_label": f"team-brain/{team_id}/{agent_id}",
            "prompt": prompt,
            "ready_to_spawn": True,
        })

    # 4. 更新 team-{id}.json 状态
    status_update_result = None
    if not dry_run:
        agent_updates = [
            {"agent_id": s["agent_id"], "status": "running"}
            for s in spawn_plan
        ]
        status_update_result = update_team_agents_status(team_id, agent_updates)

    # P0-FIX: --run 模式 — 生成 spawn 执行 manifest + 请求文件
    run_mode = False
    # 检查调用时的参数（从 main() 传入的 kwargs 或 CLI 参数）
    spawn_manifest_path = None
    spawn_report_path = None
    
    result = {
        "ok": True,
        "team_id": team_id,
        "plan_id": plan_id,
        "topic": topic,
        "description": description,
        "max_agents": max_agents,
        "dry_run": dry_run,
        "auto_monitor": auto_monitor,
        "full_discussion": full_discussion,
        "spawn_count": len(spawn_plan),
        "spawn_plan": spawn_plan,
        "status_update": status_update_result,
        "team_file": str(TEAM_BRAIN_ROOT / "teams" / f"{team_id}.json"),
        "plan_file": str(TEAM_BRAIN_ROOT / "plans" / f"{plan_id}.json"),
        "next_action": (
            "iterate spawn_plan; for each item, call sessions_spawn with "
            "task=<prompt>, agentId=<target_agent>, label=<spawn_label>"
        ),
        "monitor_hint": (
            "auto_monitor enabled: 建议每 30s 调 health-monitor.py check <team_id>，"
            "超过 120s 无心跳的 agent 视为已挂"
        ) if auto_monitor else None,
    }
    
    return result


def launch_and_spawn_run(
    topic: str,
    description: str,
    max_agents: int = 5,
    *,
    dry_run: bool = False,
    auto_monitor: bool = False,
    full_discussion: bool = False,
) -> dict:
    """P0-FIX: --run 模式入口 — 生成 spawn plan + 写入 execution manifest
    
    --run 模式相较于普通模式新增：
    1. 写入 spawn manifest（runs/{team_id}/manifest.json）
    2. 为每个 agent 写入独立 spawn request（runs/{team_id}/requests/{agent_id}.json）
    3. 输出 auto_execute=true 及 manifest_path，供主 agent 读取并执行
    4. 支持最终状态报告（final_report.json）
    """
    # 1. 生成 spawn plan（复用已有逻辑）
    result = launch_and_spawn(
        topic=topic,
        description=description,
        max_agents=max_agents,
        dry_run=dry_run,
        auto_monitor=auto_monitor,
        full_discussion=full_discussion,
    )
    
    if not result.get("ok"):
        return {
            **result,
            "run_error": "spawn plan generation failed, cannot execute run mode",
        }
    
    team_id = result["team_id"]
    plan_id = result["plan_id"]
    spawn_plan = result.get("spawn_plan", [])
    
    # 2. 创建并写入 spawn manifest
    manifest = _create_spawn_manifest(team_id, plan_id, spawn_plan)
    manifest["status"] = "running"
    manifest_path = _write_spawn_manifest(team_id, manifest)
    
    # 3. 为每个 agent 写入 spawn request（供主 agent 的 sessions_spawn 读取）
    request_paths = []
    for sp in spawn_plan:
        item = manifest["items"][spawn_plan.index(sp)]
        req_path = _write_spawn_request(team_id, item)
        request_paths.append(req_path)
    
    # 4. 设置主 agent 可以直接执行的指令
    result["auto_execute"] = True
    result["manifest_path"] = manifest_path
    result["request_count"] = len(request_paths)
    result["request_paths"] = request_paths
    result["spawn_runs_dir"] = str(SPAWN_RUNS_DIR / team_id)
    # P1-FIX: 2026-06-07 — 启动 health-monitor 后台进程（dry-run 模式不启动）
    health_monitor = None
    if not dry_run:
        health_monitor = _start_health_monitor_process(team_id)
    
    result["health_monitor"] = health_monitor
    result["next_action"] = (
        f"auto_execute: {len(spawn_plan)} spawn requests ready at {SPAWN_RUNS_DIR / team_id / 'requests/'}\n"
        f"1. Read {manifest_path} for full manifest\n"
        f"2. For each request, call sessions_spawn(task=<prompt>, agentId=<target_agent>, label=<spawn_label>)\n"
        f"3. After completion, update manifest via _write_spawn_manifest() or re-run with --finalize\n"
        f"4. Read final report at {SPAWN_RUNS_DIR / team_id / 'final_report.json'}\n"
        f"5. Health-monitor running: team-brain.py health-monitor {team_id}"
    )

    # P1-FIX: 2026-06-07 — event-log: --run 模式启动摘要
    if not dry_run:
        _log_events_jsonl(team_id, "run_started", {
            "agents": len(spawn_plan),
            "plan_id": plan_id,
            "manifest_path": manifest_path,
        })
        print(f"[launch-and-spawn] {team_id}: {len(spawn_plan)} agents queued, run started")
    
    return result


def finalize_spawn_run(team_id: str) -> dict:
    """P0-FIX: 最终化 spawn run — 扫描每个 agent 的状态文件，写最终报告
    
    在 spawns 全部完成后调用，从独立状态文件读取结果。
    """
    manifest_dir = SPAWN_RUNS_DIR / team_id
    manifest_path = manifest_dir / "manifest.json"
    
    if not manifest_path.exists():
        return {"ok": False, "error": f"spawn manifest not found: {manifest_path}"}
    
    with open(manifest_path, encoding="utf-8") as f:
        manifest = json.load(f)
    
    # 扫描 agent 状态文件，更新 manifest
    status_dir = TEAM_BRAIN_ROOT / "teams" / team_id / "status"
    completed = 0
    failed = 0
    for item in manifest.get("items", []):
        agent_id = item["agent_id"]
        agent_status_file = status_dir / f"{agent_id}.json" if status_dir.exists() else None
        if agent_status_file and agent_status_file.exists():
            with open(agent_status_file, encoding="utf-8") as f:
                agent_status = json.load(f)
            s = agent_status.get("status", "")
            if s == "done":
                item["status"] = "done"
                completed += 1
            elif s in ("failed_with_error", "timed_out"):
                item["status"] = "failed"
                item["error"] = agent_status.get("error_message", s)
                failed += 1
            else:
                item["status"] = agent_status.get("status", "running")
        else:
            # 没有独立状态文件 → 从 team snapshot 读
            team_file = TEAM_BRAIN_ROOT / "teams" / f"{team_id}.json"
            if team_file.exists():
                with open(team_file, encoding="utf-8") as f:
                    team_data = json.load(f)
                for a in team_data.get("agents", []):
                    if a["id"] == agent_id:
                        s = a.get("status", "")
                        if s == "done":
                            item["status"] = "done"
                            completed += 1
                        elif s in ("failed_with_error", "timed_out"):
                            item["status"] = "failed"
                            failed += 1
                        break
    
    # 更新 manifest
    manifest["completed_items"] = completed
    manifest["failed_items"] = failed
    manifest["status"] = "completed" if completed + failed == manifest["total_items"] else "partial"
    
    # 写最终报告
    _write_final_spawn_report(team_id, manifest)

    # P1-FIX: 2026-06-07 — event-log: 执行摘要写入 events.jsonl
    elapsed_sec = 0
    try:
        _created = manifest.get("created_at", "")
        if _created:
            _c_ts = datetime.fromisoformat(_created.replace("Z", "+00:00")).timestamp()
            elapsed_sec = int(time.time() - _c_ts)
    except (ValueError, TypeError):
        pass
    exec_summary = {
        "agents": manifest["total_items"],
        "completed": completed,
        "failed": failed,
        "elapsed_sec": elapsed_sec,
        "status": manifest["status"],
    }
    _log_events_jsonl(team_id, "spawn_completed", exec_summary)
    print(f"[launch-and-spawn] {team_id}: {completed}/{manifest['total_items']} agents done"
          f" ({failed} failed) in {elapsed_sec}s")

    return {
        "ok": True,
        "team_id": team_id,
        "total_items": manifest["total_items"],
        "completed_items": completed,
        "failed_items": failed,
        "status": manifest["status"],
        "report_path": str(manifest_dir / "final_report.json"),
        "exec_summary": exec_summary,
    }


# ---------------------------------------------------------------------------
# Mock 工具（仅 dry-run 和单元测试用）
# ---------------------------------------------------------------------------

def _mock_plan(topic: str, description: str, max_agents: int) -> dict:
    """构造 mock plan（用于 dry-run 和单元测试）"""
    domains = ["宏观", "行业", "估值", "技术", "风险", "财务", "竞争", "市场"]
    subtasks = []
    for i in range(max_agents):
        domain = domains[i % len(domains)]
        subtasks.append({
            "agent_id": f"agent-{i+1}",
            "domain": domain,
            "role": f"{domain}分析师",
            "timeout_seconds": 300,
            "key_questions": [f"{domain} 维度的核心问题是什么？"],
        })
    return {
        "plan_id": f"plan-mock-{int(time.time())}",
        "task": topic,
        "description": description,
        "optimal_agents": max_agents,
        "estimated_total_minutes": 15,
        "estimated_with_margin_minutes": 20,
        "use_full_discussion": False,
        "complexity_score": 2,
        "subtasks": subtasks,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="P0-FIX: team-brain launch + spawn 包装器（支持 --run 自动执行）",
    )
    parser.add_argument("topic", help="任务主题")
    parser.add_argument("description", help="任务描述")
    parser.add_argument("max_agents", nargs="?", type=int, default=5, help="最大 agent 数（默认 5）")
    parser.add_argument("--dry-run", action="store_true", help="只准备 spawn 计划，不调 launch、不写状态")
    parser.add_argument("--auto-monitor", action="store_true", help="在输出里附带监控提示")
    parser.add_argument("--full-discussion", action="store_true", help="启用完整团队脑讨论（pre-task + consensus check）")
    parser.add_argument("--pretty", action="store_true", help="pretty-print JSON（默认就是 pretty）")
    # P0-FIX: 新增 --run 参数
    parser.add_argument(
        "--run",
        action="store_true",
        help="P0-FIX: 执行模式 — 生成 spawn plan 后写入 execution manifest + spawn requests，"
             "供主 agent 的 sessions_spawn 读取并执行。不传此参数时保持原有行为。",
    )
    # P0-FIX: 新增 --finalize 子命令
    parser.add_argument(
        "--finalize",
        metavar="TEAM_ID",
        default=None,
        help="P0-FIX: 最终化指定 team 的 spawn run — 扫描状态文件，写最终报告。"
             "使用方式: python launch-and-spawn.py --finalize team-xxx",
    )
    # P1-FIX: 2026-06-07 — 新增 --clean-stuck 参数
    parser.add_argument(
        "--clean-stuck",
        action="store_true",
        help="P1-FIX: 扫描 teams/ 目录，标记超过 24h 的 stuck team 为 dormant。"
             "不删除 findings，只标记状态。",
    )
    # P1-FIX: --clean-stuck 模式（在 argparse 前检查，避免 position arg 报错）
    if "--clean-stuck" in sys.argv:
        result = _clean_stuck_teams()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get("ok") else 1

    args = parser.parse_args()

    # P0-FIX: --finalize 模式（只要传了 --finalize，忽略其他参数）
    if args.finalize:
        result = finalize_spawn_run(args.finalize)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get("ok") else 1

    # P0-FIX: --run 模式
    if args.run:
        result = launch_and_spawn_run(
            topic=args.topic,
            description=args.description,
            max_agents=args.max_agents,
            dry_run=args.dry_run,
            auto_monitor=args.auto_monitor,
            full_discussion=args.full_discussion,
        )
    else:
        result = launch_and_spawn(
            topic=args.topic,
            description=args.description,
            max_agents=args.max_agents,
            dry_run=args.dry_run,
            auto_monitor=args.auto_monitor,
            full_discussion=args.full_discussion,
        )
    
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
