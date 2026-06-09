# Patterns

Proven multi-agent workflows. Copy and adapt.

## Spec → Review → Build → Test

The full quality loop. Use for any non-trivial feature.

```
1. Orchestrator creates task, assigns to Spec Writer
2. Spec Writer produces spec at /shared/specs/[task]-spec.md
3. Orchestrator assigns spec review to Builder (feasibility check)
4. Builder reviews: "feasible" / "change X because Y"
5. If changes needed → back to Spec Writer → re-review
6. Orchestrator assigns build to Builder
7. Builder produces artifacts at /shared/artifacts/[task]/
8. Orchestrator assigns review to Reviewer
9. Reviewer approves or returns with feedback
10. If returned → Builder fixes → re-review
11. Orchestrator marks Done, reports to stakeholders
```

**Key:** The person who writes the spec doesn't review the build. The person who builds doesn't approve their own work. Cross-role verification is the whole point.

### Minimal version (2 agents):
```
1. Orchestrator writes brief spec
2. Builder implements
3. Orchestrator reviews output
4. Done or return for fixes
```

## Parallel Research

Multiple agents research independently, then merge. Use for broad investigation.

```
1. Orchestrator defines research question + splits into angles
2. Spawn Agent A: "Research [angle 1], write findings to /shared/specs/research-[topic]-a.md"
3. Spawn Agent B: "Research [angle 2], write findings to /shared/specs/research-[topic]-b.md"
4. Wait for both to complete
5. Orchestrator (or designated agent) merges into /shared/specs/research-[topic]-final.md
6. Use merged research to inform next decision
```

**Rules:**
- Define non-overlapping angles to avoid duplicate work
- Set a time/scope limit per agent — research expands to fill available time
- The merge step is mandatory — raw research without synthesis is useless

## Escalation

Agent hits a blocker it can't resolve. Structured escalation prevents stalling.

```
1. Agent comments on task: "Blocked: [specific problem]"
2. Agent continues with other work if possible (don't idle)
3. Orchestrator sees blocker, decides:
   a. Resolve directly (answer the question, provide access)
   b. Reassign to a more capable agent
   c. Escalate to human stakeholder
   d. Deprioritize/defer the task
4. Orchestrator comments decision and unblocks or reassigns
```

**Escalation triggers:**
- Missing access or credentials
- Ambiguous requirements that need product decisions
- Technical blocker outside agent's expertise
- Task exceeds estimated scope by 2x+

**Anti-pattern:** Agent silently struggling for 30 minutes instead of escalating after 10. Set the expectation: escalate early, escalate with context.

## Cron-Based Ops

Scheduled tasks for team health. Assign to the cheapest reliable agent.

### Daily Standup
```
Schedule: Every morning
Agent: Ops

1. Read all open tasks
2. Check for stale tasks (no comment in 24h+)
3. Check for overdue tasks
4. Produce standup summary:
   - What completed yesterday
   - What's in progress
   - What's blocked
   - What's stale
5. Post to orchestrator or team channel
```

### Task Dispatch
```
Schedule: Every few hours (or on trigger)
Agent: Orchestrator

1. Check inbox for new tasks
2. Prioritize by urgency/importance
3. Match to available agents (check capabilities)
4. Assign and spawn
```

### Health Check
```
Schedule: Periodic
Agent: Ops

1. Verify shared directories exist and are writable
2. Check for orphaned tasks (assigned but no agent session)
3. Check for artifact path conflicts
4. Report anomalies to orchestrator
```

## Batch Processing

Multiple similar tasks that can run in parallel.

```
1. Orchestrator creates N tasks from a list
2. Spawn up to M agents in parallel (M ≤ concurrency limit)
3. Each agent picks one task, completes it, writes output
4. Orchestrator collects results as agents finish
5. Spawn next batch if more tasks remain
6. Final aggregation once all tasks complete
```

**Sizing:** Start with 2-3 parallel agents. More isn't always faster — coordination overhead grows.

## Pre-task Discussion (Expert Group Alignment)

Experts discuss before execution to align on approach and分工. Use for high-complexity research/decision tasks.

```
1. Orchestrator judges complexity (auto: ≥2 high-keywords or ≥3 total → full discussion)
   OR user declares `// full-discussion`
2. Orchestrator → Pre-task Discussion state
3. Each expert submits independent opinion (not seeing others' — avoid anchoring)
   → Write to: /shared/team-brain/pre-task/{team_id}/{agent_id}-opinion.md
   → Timeout: based on complexity level (see Time Boxing below)
4. Orchestrator identifies conflicts → initiates debate round (max 2 rounds, 10min each)
5. Orchestrator adjudicates remaining conflicts → writes consensus plan
   → Output: /shared/team-brain/pre-task/{team_id}/{team_id}-consensus.md
6. Orchestrator → Assigned, spawns builder with confirmed execution plan
```

**Complexity auto-judge:**
```python
HIGH_KEYWORDS = ["分析", "研究", "评估", "策略", "规划", "投资", "决策"]
MED_KEYWORDS   = ["对比", "检查", "审核", "讨论"]
def should_use_full_discussion(task_desc):
    h = sum(1 for k in HIGH_KEYWORDS if k in task_desc)
    m = sum(1 for k in MED_KEYWORDS if k in task_desc)
    return h >= 2 or (h >= 1 and m >= 2)
```

**Complexity classification:**
| Level | Trigger | Pre-task Time Box | Mid-task Time Box |
|-------|---------|------------------|------------------|
| Simple | No high-keyword, med<2 | N/A (skipped) | 5 min |
| Medium | high≥1 or med≥2 | 5 min | 15 min |
| Complex | high≥2 or //full-discussion | 10 min | 30 min |
| Ultra | high≥3 or multi-domain | 15 min | 60 min |

**Time boxing rules:**
- Each phase timed separately; timeout forces move to next phase
- Default strategy on timeout: Orchestrator adjudicates, "no objection" passes
- User can declare `// extend [N]min` to extend time box (requires reason ≥10 chars)

**User intervention syntax:**
| Syntax | Meaning | Handling |
|--------|---------|---------|
| `// override` | Skip current phase, proceed to next | Log and continue |
| `// extend [N]min` | Extend current phase by N minutes | Requires reason ≥10 chars |
| `// abort` | Immediately terminate task | Mark as Failed with reason |
| `// reduce-experts` | Reduce participating experts | Specify which experts to keep and why |
| `// full-discussion` | Force all tasks through full flow | Override complexity judgment |

**Anti-formalism rules (apply to all discussions):**
- Every key action requires a reason ≥10 characters
- Reason must reference specific content (file, section, line number)
- Actions must have timestamps; no "retroactive logging"

**Rules:**
- Experts write opinions independently (Orchestrator must not reveal others' views before all submitted)
- Timeout → "no objection" (don't block on stragglers)
- Unresolved conflicts → Orchestrator adjudicates with reasoning logged

## Post-task Synthesis (Expert Consensus Check)

After Reviewer approves, all experts validate before delivery. Prevents Orchestrator from shipping without expert sign-off.

```
1. Reviewer approves → Orchestrator sets state to Consensus Check
2. Orchestrator triggers synthesis-check.py:
   python scripts/synthesis-check.py <team_id> <final_report_path>
3. Each expert receives: "Final report at {path}. Confirm: ✅ / ⚠️ / ❌"
   → Timeout: based on complexity level (5-15 min)
4. synthesis-check.py collects responses, generates report:
   → All ✅ → status="delivered"
   → Any ⚠️ → status="delivered_with_concerns", concerns attached
   → Any ❌ → status="returned_to_builder", objections logged
5. Orchestrator acts on result and reports to user
```

**Three-tier response format requirements:**

| Tier | Symbol | When to Use | Required Fields |
|------|--------|-------------|-----------------|
| **Tier 1** | ✅ | Fully agree with no reservations | Vote only |
| **Tier 2** | ⚠️ | Agree with concerns or suggestions | Vote + concern description (≥10 chars) + reference to specific section |
| **Tier 3** | ❌ | Disagree or object | Vote + objection reason (≥10 chars) + referenced evidence or logic |

**Response examples:**
- ✅ "Approved. Implementation matches spec."
- ⚠️ "Approved with concern: The error handling in §3.2 doesn't cover network timeout cases, may cause silent failures in production."
- ❌ "Objection: The algorithm's time complexity is O(n²), not O(n) as stated in §2.1. This will fail at scale. Reference: consensus.md §2.1 lines 15-20."

**synthesis-check.py output:**
```json
{
  "team_id": "...",
  "status": "delivered | delivered_with_concerns | returned",
  "votes": {
    "agent-1": "✅",
    "agent-2": "⚠️ concerned about X (详见report.md §3.2)",
    "agent-3": "❌ objection: Y，证据见consensus.md §2.1"
  },
  "report_path": "synthesis/{team_id}-final.md"
}
```

**Anti-formalism enforcement:**
- Responses without ≥10 character reason → auto-converted to "参考" tier
- Responses without section reference → marked as incomplete
- Three incomplete responses → review flagged for Orchestrator review

**When to skip Consensus Check:**
- Trivial tasks (single expert, no cross-domain validation needed)
- Time-critical delivery (log the skip reason)

## Review Rotation

Prevent review fatigue and bias by rotating reviewers.

```
Task produced by Agent A → Reviewed by Agent B
Task produced by Agent B → Reviewed by Agent C
Task produced by Agent C → Reviewed by Agent A
```

**Why:** Same reviewer for the same builder creates blind spots. Rotation catches different things.