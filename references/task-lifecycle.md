# Task Lifecycle

Task states, transitions, comment conventions, and decision logging.

## States

```
Inbox → Pre-task Discussion → Assigned → In Progress → Review → Consensus Check → Done | Failed
```

| State | Meaning | Owner |
|-------|---------|-------|
| **Inbox** | New task, unassigned | Orchestrator |
| **Pre-task Discussion** | Experts discuss task understanding + strategy before execution | Orchestrator (facilitator) |
| **Assigned** | Agent selected, not yet started | Orchestrator |
| **In Progress** | Agent actively working | Assigned agent |

> **T3+ Checkpoint强制**：T3/T4/T5任务在"In Progress"状态必须每2分钟写一次checkpoint，且每次状态转换前必须先checkpoint。
> **续接标记**：进入"Review"前如有未完成的子任务，必须在checkpoint中标注`completed_subtasks`，供后续续接使用。

> **超时检测增强**：Orchestrator在分配任务后记录start_time，按`elapsed > timeout_setting × 0.8`预警，`elapsed > timeout_setting`触发超时处理（调用self_heal.py + 更新任务状态）。
| **Review** | Work complete, awaiting verification | Reviewer |
| **Consensus Check** | All experts validate final conclusion before delivery | Orchestrator + All experts |
| **Done** | Verified and shipped | Orchestrator |
| **Failed** | Abandoned with documented reason | Orchestrator |

## Transition Rules

**Orchestrator transitions:**
- Inbox → Pre-task Discussion (spawns experts for pre-task alignment — enabled when complexity threshold met or `// full-discussion` declared)
- Pre-task Discussion → Assigned (consensus reached, spawns builder with confirmed execution plan)
- Assigned → In Progress (spawns the agent or sends the task)
- Review → Consensus Check (reviewer approved, trigger expert consensus)
- Consensus Check → Done (consensus reached, deliver to user)
- Consensus Check → In Progress (unresolved objections, return to builder)
- Any state → Failed (with reason)

**T3+ In Progress 强制规则：**
- 每2分钟写一次checkpoint到 `checkpoints/{agent_id}.json`
- 进入Review前必须满足：checkpoint中 `completed_subtasks` 已完整记录
- 若任务被中断（崩溃/超时），Orchestrator读取 `death-report.json` 的 `can_resume_from`，判断是否可续接
- 可续接：从 `next_concrete_action` 继续，跳过已完成的 `completed_subtasks`
- 不可续接：记录到 `pitfalls.log`，从头开始，标记新的超时策略

**Reviewers transition:**
- Review → In Progress (returns with feedback — agent must address it)
- Review → Done (approves — orchestrator confirms)

**Never skip Review.** The orchestrator may override for trivial tasks, but document it.

## Comment Conventions

Every state change gets a comment. Format:

```
[Agent] [Action]: [Details]
```

### Required comments:

**Pre-task discussion (Orchestrator opening):**
```
[Orchestrator] Pre-task Discussion: Task complexity={HIGH/MEDIUM/LOW}. Spawning {N} experts for alignment.
- Topic: {task}
- Key question: {main question for experts}
- Time budget: 5min per expert opinion, 10min debate round
```

**Expert opinion submission:**
```
[Expert-{id}] Opinion: {domain} perspective on {task}
- View on approach: ...
- Key risks: ...
- Suggested angle: ...
```

**Consensus reached:**
```
[Orchestrator] Consensus: Agreed on {execution plan}. Proceeding to Assigned.
```

**Consensus check (Orchestrator initiating):**
```
[Orchestrator] Consensus Check: Final report ready at {path}. Experts please confirm: ✅ Agree / ⚠️ Concern / ❌ Object.
```

**Expert consensus response:**
```
[Expert-{id}] Consensus: {✅/⚠️/❌} — {reason if concerned/objecting}
```

**Starting work:**
```
[Builder] Starting: Picking up auth module. Questions: Should rate limiting be per-user or per-IP?
```

**Blocker found:**
```
[Builder] Blocked: Need API credentials for the payment gateway. Who has access?
```

**Submitting for review:**
```
[Builder] Handoff: Auth module complete at /shared/artifacts/auth/.
- Added JWT validation middleware
- Tests at /shared/artifacts/auth/tests/
- Run `npm test -- --grep auth` to verify
- Known issue: refresh token rotation not implemented (out of scope per spec)
- Next: Reviewer checks error handling paths
```

**Review feedback:**
```
[Reviewer] Feedback: Two issues found.
1. Missing input validation on email field — SQL injection risk
2. Error messages expose internal paths in production mode
Returning to builder. Fix both, then resubmit.
```

**Completion:**
```
[Reviewer] Approved: All issues addressed. Auth module ready to ship.
```

**Failure:**
```
[Orchestrator] Failed: Deprioritized — superseded by new auth provider integration. Preserving spec at /shared/specs/auth-v1.md for reference.
```

## Decision Logging

Architecture or product decisions made during task execution go in a shared decisions directory.

```markdown
# Decision: [Title]
**Date:** YYYY-MM-DD
**Author:** [Agent]
**Status:** Proposed | Accepted | Rejected
**Task:** [Task ID if applicable]

## Context
Why this decision came up.

## Options Considered
1. Option A — tradeoffs
2. Option B — tradeoffs

## Decision
What was chosen and why.

## Consequences
What changes as a result.
```

**When to log a decision:**
- Choosing between two valid architectural approaches
- Changing a spec during implementation
- Rejecting a requirement as infeasible
- Any choice that future agents will wonder "why did we do it this way?"

## Multi-Step Task Workflows

Complex tasks split into sub-tasks. Track the parent relationship:

```
Task #12: Build user dashboard
  ├── #12a: Write spec (Assigned: Spec writer)
  ├── #12b: Review spec (Assigned: Builder — feasibility check)
  ├── #12c: Build frontend (Assigned: Builder)
  ├── #12d: Build API endpoints (Assigned: Builder)
  └── #12e: Integration test (Assigned: Reviewer)
```

The orchestrator tracks the parent task and only marks it Done when all sub-tasks complete.
