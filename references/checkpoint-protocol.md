# 团队进度保护 — Checkpoint 协议

> 本协议是 `agent-team-orchestration` 的补充，为所有专家小组提供进度保护和自我消灭前的报告机制。
> 无需修改 ClawTeam，纯应用层实现，立即生效。

---

## 触发场景

当专家小组（通过 `agent-team spawn` 创建的子 agent 团队）发生以下情况时：

- 超时退出（timeout）
- 进程异常消失（OOM、崩溃）
- 被系统强制终止
- 主动退出

**问题**：发起 agent 收不到任何结果，进度全部丢失。

**解决方案**：Checkpoint 协议 + 发起 agent 轮询等待。

---

## 核心机制

### 三层保护

| 层级 | 机制 | 谁来做 | 触发时机 |
|------|------|--------|---------|
| **L1: Checkpoint** | 子 agent 每5分钟写 `checkpoints/{id}.json` | 子 agent | 定时，自主 |
| **L2: 共享进度文件** | 每个子 agent 追加到 `shared/{team}/progress.md` | 子 agent | 每次发现/完成时 |
| **L3: 发起 agent 轮询** | 发起 agent 每30秒读一次 checkpoint + progress | 发起 agent | 等待期间持续 |

**关键**：L1 + L2 不需要修改 agent-team，只需要求子 agent 在 prompt 中遵守。

---

## T3+ Checkpoint强制条款（新增）

适用等级：T3（10min）/ T4（20min）/ T5（30min+）任务

| 项目 | 标准协议 | T3+ 强制条款 |
|------|---------|------------|
| checkpoint频率 | 每5分钟 | **每2分钟** |
| progress.md写入 | 每次子步骤完成 | **每次主要步骤完成 + 每次checkpoint时** |
| checkpoint内容 | progress + phase + findings | **额外包含：已完成子任务列表 + 下一步具体行动计划 + 关键数据快照** |
| 续接判断 | 发起agent手动判断 | **自动判断：checkpoint的`can_resume_from`字段** |

### T3+ Checkpoint增强字段

在原有Schema基础上，T3+任务checkpoint额外包含：
```json
{
  "completed_subtasks": ["string"],
  "next_concrete_action": "string",
  "data_snapshot": {
    "key_var": "value",
    "file_refs": ["path"]
  },
  "can_resume_from": {
    "enabled": true,
    "resume_point": "string",
    "required_files": ["path"]
  }
}
```

### 续接流程（T3+专用）

1. **检测崩溃**：`death-report.json` 中 `can_resume_from.can_resume = true`
2. **读取checkpoint**：获取 `completed_subtasks` + `next_concrete_action`
3. **重新spawn**：使用 `--resume-from {checkpoint_id}` 参数（需team-brain.py支持）
4. **传递上下文**：新agent接收原checkpoint的 `data_snapshot` + `required_files`
5. **继续执行**：从 `next_concrete_action` 继续，跳过已完成子任务

---

## 文件结构

```
~/.openclaw/workspace/teams/{team_id}/
├── checkpoints/
│   ├── {agent_1}.json    # 各子 agent 的 checkpoint
│   ├── {agent_2}.json
│   └── ...
├── progress.md           # 共享进度日志（追加模式）
├── death-report.json     # 团队消灭时的最终报告（Watchdog 写）
└── status.json           # 团队当前状态
```

---

## Checkpoint JSON Schema

```json
{
  "team_id": "string",
  "agent_id": "string",
  "role": "string",
  "status": "in_progress | done | failed | dying",
  "progress": 75,
  "phase": "string",
  "findings": ["string"],
  "next_action": "string",
  "last_updated": "ISO8601",
  "dying": false
}
```

**字段说明**:
- `progress`: 0-100，估值的完成百分比
- `phase`: 当前阶段标签，如 `researching` / `building` / `testing`
- `findings`: 关键发现的列表（最后一条是最新）
- `dying`: `true` 时表示团队正在关闭，这是最终 checkpoint
- `completed_subtasks`（T3+强制）: 已完成子任务列表，用于崩溃后续接
- `next_concrete_action`（T3+强制）: 下一步具体行动计划，续接后从此处继续
- `data_snapshot`（T3+强制）: 关键变量和文件引用快照，防止续接后数据不一致
- `can_resume_from`（T3+强制）: 续接标记，`enabled:true` + `resume_point` + `required_files`

---

## Progress.md 格式

每行格式：`[HH:MM] {agent_id} 完成 {X}% — {一句话发现}`

```
[04:28] builder-1 完成 65% — 发现 fyp=0.5/seasonal=0.5 为最优参数
[04:30] reviewer-1 完成 30% — 等待 builder 提交初稿
[04:32] builder-1 完成 72% — 快速对比结果：事件驱动 > 月度调仓
[04:34] builder-1 完成 78% — 修复 max_dd 计算 bug
```

**规则**：
- 追加模式，不覆盖
- 每次 handoff 或完成一个子步骤时写入
- 团队消灭前最后一条即为最终报告

---

## Death Report Schema

```json
{
  "team_id": "string",
  "died_at": "ISO8601",
  "cause": "timeout | exception | manual | unknown",
  "members": [
    {
      "agent_id": "string",
      "role": "string",
      "final_status": "string",
      "last_checkpoint": { ... },
      "completed_pct": 75,
      "final_findings": ["string"]
    }
  ],
  "recommendation": "string",
  "can_resume_from": "string"
}
```

**用途**：
- 发起 agent 超时后读取，了解团队最终状态
- 决定是否可以resume，或需要重新开始
- 保留关键发现，不丢失进度

---

## 发起 agent 等待循环（参考实现）

```
Python 伪代码，发起 agent 等待时使用：

def await_team_with_protection(team_id, timeout=600):
    start = time.time()
    last_seen = {}  # agent_id -> last_progress
    
    while time.time() - start < timeout:
        # L1: 读各 agent checkpoint
        checkpoints = load_all_checkpoints(team_id)
        for agent_id, cp in checkpoints.items():
            if cp['progress'] != last_seen.get(agent_id):
                print(f"[{agent_id}] 进度: {cp['progress']}% — {cp['findings'][-1]}")
                last_seen[agent_id] = cp['progress']
        
        # L2: 读共享进度
        progress = read_progress_log(team_id)
        if progress:
            last_line = progress.strip().split('\n')[-1]
            print(f"  最新: {last_line}")
        
        # 检查团队状态
        status = check_team_status(team_id)
        if status == 'completed':
            return collect_results(team_id)
        elif status in ('stale', 'dead'):
            death_report = load_death_report(team_id)
            return build_partial_report(death_report)
        
        time.sleep(30)  # 每30秒检查一次

    # 超时 → 读取 death report
    death_report = load_death_report(team_id)
    return build_partial_report(death_report, timeout=True)
```

---

## 子 agent spawn 模板（修改版）

在原 spawn 指令基础上加入：

```
## 进度保护要求（必须遵守）

1. 每5分钟写 checkpoint 到 `checkpoints/{your_agent_id}.json`：
   {
     "team_id": "{team_id}",
     "agent_id": "{your_id}",
     "role": "builder|reviewer|...",
     "status": "in_progress",
     "progress": 0-100,
     "phase": "当前阶段",
     "findings": ["发现1", "发现2"],
     "next_action": "下一步做什么",
     "last_updated": "ISO时间",
     "dying": false
   }

2. 每次完成一个子步骤时，追加一行到 `shared/{team_id}/progress.md`：
   [HH:MM] {your_id} 完成 {X}% — {一句话发现}

3. 团队消灭前（收到任何终止信号时）：
   - 将 status 改为 "dying"
   - 设置 dying: true
   - 将最终 findings 写入 checkpoint
   - 这是强制要求，用于保护你的工作成果

4. 产出物路径：使用共享目录 `shared/{team_id}/artifacts/`
```

---

## Watchdog 实现（可选增强）

如果需要 L3 以上的保护（团队消失后主动通知），可以 spawn 一个 watchdog：

```
## Watchdog 角色
每60秒检查一次团队状态（agent-team team status）。
如果所有成员均已消失（status == stale/dead）：
  1. 为每个已消失的成员读最后 checkpoint
  2. 写入 {team_id}/death-report.json
  3. 向发起 agent 的 session 发送通知消息
  4. 退出（自己完成使命）
```

Watchdog 是一个轻量专用 agent，逻辑极简单（约20行核心代码）。

---

## 使用流程

1. **发起 agent** spawn 团队时，在每个子 agent 的 prompt 中加入上面的"进度保护要求"
2. **等待期间** 发起 agent 定期读 `checkpoints/` 和 `progress.md`，实时了解进度
3. **团队正常完成** → 正常收集结果
4. **团队超时/消失** → 发起 agent 读 `death-report.json` 和 `progress.md` 重建进度，发给用户

---

## 效果

| 场景 | 无协议 | 有协议 |
|------|--------|--------|
| 团队5分钟后消失 | 丢失全部进度 | 丢失最后5分钟 |
| 团队消失，但有3个checkpoint | 丢失全部 | 最多丢3个checkpoint间隔 |
| 团队正常完成 | 正常 | 正常（无影响） |

---

## 立即生效的简化版

如果暂时不想实现完整协议，可以先用简化版：

在 spawn prompt 中加入：

```
⚠️ 进度保护（强制）：
- 每完成一个步骤，追加一行到 shared/{team_id}/progress.md
- 格式：[HH:MM] 完成 {X}% — {发现}
- 团队消灭前最后一条即为你的最终工作报告
```

这个简化版不需要 checkpoint JSON，只需要追加文本，0开发成本，立即生效。