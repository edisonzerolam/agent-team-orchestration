---
name: agent-team-orchestration
description: "Orchestrate multi-agent teams with defined roles, task lifecycles, handoff protocols, and review workflows. 触发词：「组成专家小组」「团队协作」「子代理协作」「team」。不适用：单 agent 任务、一次性 sessions_spawn、简单 Q&A 转发。"
---

## 需求路由

```python
def route_demand(demand: str) -> str:
    d = demand.lower()
    if any(kw in d for kw in ["PowerShell 错误", "self_heal"]): return "local"
    if any(kw in d for kw in ["retry", "skip"]): return "local"
    if any(kw in d for kw in ["规划团队", "团队设置"]): return "llm"
    if any(kw in d for kw in ["spawn", "派发"]): return "local"
    if any(kw in d for kw in ["健康检查", "评估"]): return "hybrid"
    if any(kw in d for kw in ["协作结果", "汇总"]): return "hybrid"
    return "llm"
```

## Core Concepts

### Roles
| Role | Purpose | Model guidance |
|------|---------|---------------|
| **Orchestrator** | Route work, track state, priority calls | High-reasoning |
| **Builder** | Produce artifacts (code, docs, configs) | Cost-effective |
| **Reviewer** | Verify quality, push back on gaps | High-reasoning |
| **Ops** | Cron, health checks, dispatching | Cheapest reliable |

### Task States
```
Inbox → Pre-task Discussion → Assigned → In Progress → Review → Consensus Check → Done | Failed
```
Orchestrator owns state transitions. Every transition gets a comment.

### Handoffs
Handoff messages must include: What was done / Where artifacts are / How to verify / Known issues / What's next.

### Reviews
Cross-role reviews prevent quality drift. Every artifact gets at least one set of eyes that didn't produce it.

## Quick Start: Minimal 2-Agent Team

```
1. Define roles: Orchestrator (you) + Builder
2. Spawn builder with: Task ID, description, output path, handoff instructions
3. On completion: review artifacts, mark done, report
4. Add a reviewer: Builder → Reviewer checks → Orchestrator ships or returns
```

## 触发器路由矩阵

| 场景 | 工具 | 理由 |
|------|------|------|
| 2-3 Agent 长期协同，有交接 | `team-brain.py launch` | 生命周期管理 + checkpoint |
| ≤5 Agent 一次性任务 | `sessions_spawn` | 轻量 |
| 并行同优先级子任务 | `sessions_spawn × N` | 并行分发 |
| 临时单次指令 | 直接 `sessions_spawn` | 最简路径 |
| cron 周期任务 | `sessions_spawn` + cron | 定时触发 |

### 与 agents-config.md 协同
```
用户说"组成专家小组"
  → agents-config.md 判断复杂度
    → T1-T2（≤2 子代理）→ 直接 sessions_spawn
    → T3-T5（3+ 子代理，需交接）→ team-brain.py
```

## Computer Pitfalls

- **无输出路径**：Agent 干活了你找不到结果 → 每次 spawn 指定精确路径
- **跳过 review**：连续 3 次"小改动不审" = 质量崩塌
- **Agent 不汇报**：静默 = 卡住，强制进度注释
- **能力不匹配**：给无浏览器权限的 Agent 派浏览器任务
- **Orchestrator 自己干活**：一旦动手干就失去了对整个团队的监督

## 参考文件

| 文件 | 读... |
|------|-------|
| `references/team-setup.md` | 定义角色/模型/workspace |
| `references/task-lifecycle.md` | 任务状态/转换/注释 |
| `references/communication.md` | 通信/artifacts 路径 |
| `references/patterns.md` | spec→build→test 等工作流 |
| `references/tools-detail.md` | team-brain.py 等脚本详细参考 |
| `references/enhancements.md` | v4.0 增强模块详情 |
| `references/self-learning.md` | 自学习 + 事实核查 |

## Windows+WSL 环境说明

| 操作 | 状态 |
|------|:----:|
| `sessions_spawn` | ✅ 100% 稳定（默认方案）|
| `team-brain.py launch` | ✅ 可用 |
| `agent-team spawn subprocess` | ❌ 0% 成功率（已废弃）|

## 增强层索引

| 层级 | 文件 | 加载时机 |
|:----:|------|:--------:|
| **L1** | SKILL.md（核心流程） | 首次加载 |
| **L2** | `references/expert-knowledge-pool.md` | SKILL.md 后 |
| **L3** | `references/knowledge/` (47 知识文件) | 专家模式 |
| **L3** | `scripts/*.py`（工具脚本） | 按需调用 |
| **L4** | `references/enhancements.md`（增强模块） | 专家模式 |

## 故障与降级

| 场景 | 处理 |
|------|------|
| 子代理全部超时 → 0% 成功率 | 强制降级主会话执行 |
| fact_check.py 不可达 | 回退到 exec 验证 |
| team-brain.py 执行异常 | 回退到 sessions_spawn 直接派发 |
| 增强模块 feature flag false | 跳过，不使用该模块 |