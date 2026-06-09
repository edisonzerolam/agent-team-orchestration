# ClawTeam 团队脑协作增强方案 — v2.0

> 通用方案：所有 ClawTeam 形成的专家组都适用
> 默认最多 5 名专家并发（可配置）

## 核心升级：团队脑（Team Brain）

### 设计原则

1. **通用性**：不局限于投资团队，适用于所有专家组的并行分析场景
2. **效率优先**：默认最多 5 名专家并发，避免过大团队造成的协调开销
3. **去中心化**：Agent 之间通过共享目录直接通讯，不依赖协调人中转
4. **可选增强**：仅在明确声明时启用完整团队脑功能（团队规模、讨论深度等）

---

## 目录结构

```
/shared/team-brain/
├── findings/           # 各Agent发现（按domain分类）
│   ├── marco/
│   ├── sector/
│   ├── valuation/
│   └── ...
├── debates/           # 观点挑战区
│   └── {team_id}/
├── synthesis/         # 综合报告
│   └── {team_id}-final.md
└── teams/             # 各团队状态文件
    └── {team_id}.json
```

---

## 团队状态文件（team-status.json）

```json
{
  "team_id": "team-20260515-abc123",
  "task": "分析茅台投资价值",
  "max_agents": 5,
  "total_pool": 21,
  "phase": "analysis",
  "agents": [
    {"id": "valuation-wang", "role": "估值分析师", "domain": "valuation", "status": "done", "progress": "100%", "findings": "findings/valuation/team-xxx-wang.md"},
    {"id": "technical-chen", "role": "技术分析师", "domain": "technical", "status": "in_progress", "progress": "60%", "findings": null},
    ...
  ],
  "debates": [
    {"from": "technical-chen", "to": "valuation-wang", "issue": "PE太高不合理", "status": "open"}
  ]
}
```

---

## 团队脑协议

### Agent 启动时
1. 读 `/shared/team-brain/teams/{team_id}.json` 了解团队任务和成员状态
2. 确认自己的角色和负责的 domain
3. 开始分析，不等待协调人指令

### Agent 分析时
- 每完成一个子模块，写入：`/shared/team-brain/findings/{domain}/{team_id}-{agent_id}-[模块].md`
- 定期更新 `status.json` 中的进度（每 5 分钟或关键节点）

### Agent 发现问题时
- 读其他 Agent 的发现，有异议则在 `/shared/team-brain/debates/{team_id}/` 下创建挑战文件
- 挑战格式：`{from_agent}-{to_agent}-challenge-{N}.md`
- 被挑战的 Agent 须在 1 小时内回复，或由协调人直接裁决

### Agent 完成后
1. 写完所有发现文件
2. 更新 `status.json` 中自己的状态为 `done`
3. 向协调人报告完成（可选，status.json 已同步）

---

## 三阶段协作协议（v3.0 新增）

在原有 team-brain 基础上，增加完整的讨论生命周期：

### 阶段一：Pre-task Discussion（任务开始前）

**触发条件：** 任务复杂度 ≥ 阈值（`should_use_full_discussion` 返回 True）或用户显式声明 `// full-discussion`

**目录结构：**
```
/shared/team-brain/pre-task/{team_id}/
├── {agent_id}-opinion.md   # 各专家独立意见（不公开看）
└── {team_id}-consensus.md  # 专家共识+执行方案
```

**Orchestrator 执行流程：**
1. 判断复杂度 → 启用 Pre-task Discussion
2. 向每位专家发送独立意见请求（各自独立撰写，不看他人）
3. 收集所有意见（超时 5min/人，超时视为"无异议"）
4. 识别分歧点 → 发起辩论轮次（最多2轮，每轮10min）
5. 裁决未决争议 → 写入 `{team_id}-consensus.md`
6. 基于共识方案 → 启动 Builder

**超时策略（审计发现F2修复）：**
- 专家意见提交：每人 5min，超时 → "无异议"
- 辩论轮次：每轮 10min，最多2轮，超时 → Orchestrator 裁决

### 阶段二：In-task Expert Support（执行中）

**原有 debates/ 机制增强：**
- Builder 每完成一个子模块 → 通知专家阅读
- 专家可主动发起挑战 → 写入 `/shared/team-brain/debates/{team_id}/`
- 被挑战方须在 1 小时内回复，或由 Orchestrator 裁决

**主动发问协议（可选）：**
- Builder 遇到不确定问题 → 写入 `/shared/team-brain/questions/{team_id}/`
- 相关专家在 1 小时内回复建议
- Builder 综合建议后继续（不等所有人回复）

### 阶段三：Post-task Consensus Check（输出前）

**触发时机：** Reviewer 通过之后、Orchestrator 交付用户之前

**目录结构：**
```
/shared/team-brain/synthesis/{team_id}/
├── {team_id}-consensus-check.md   # 共识确认记录
└── {team_id}-final.md              # 最终报告
```

**执行流程：**
1. Reviewer 通过 → Orchestrator 设置状态为 `Consensus Check`
2. 调用 `synthesis-check.py`：
   ```bash
   python scripts/synthesis-check.py <team_id> <final_report_path>
   ```
3. 每位专家收到确认请求 → 填 `{✅同意 / ⚠️有保留 / ❌反对+理由}`
   - 超时 5min → 视为"无异议"
4. synthesis-check.py 统计并输出结果：
   - 全员 ✅ → 直接交付
   - 有 ⚠️ → 附保留意见交付
   - 有 ❌ → 打回 Builder，说明反对理由
5. Orchestrator 根据结果决定交付或打回

**向后兼容（F3修复）：**
- 不使用 `--full-discussion` 时，整个三阶段协议不启用
- 原有的 `launch/status/report/debates/resolve` 命令行为不变

---

## 协调人职责（v3.0 更新）

| 阶段 | 职责 |
|------|------|
| **启动** | 解析任务 → 判断复杂度 → 决定是否启用三阶段 |
| **Pre-task** | 主持专家讨论 → 收集意见 → 裁决分歧 → 输出共识方案 |
| **监控** | 每 5 分钟检查 status.json（用 health-monitor.py）→ 识别落后/问题 → 协调交叉验证 |
| **讨论** | 处理 debates/ 中的观点冲突 → 必要时裁决 |
| **Consensus Check** | 触发 synthesis-check.py → 收集专家确认 → 决定交付/打回 |
| **综合** | 收集所有发现 → 生成 final-report.md → 向用户汇报 |
| **错误恢复** | Agent 失败时决定：重试 / 跳过 / 重新分配 / 终止任务 |

---

## 错误处理与自我修复（新增 v3）

### 错误分类

| 错误类型 | 严重性 | 可恢复 | 处理方式 |
|----------|--------|--------|----------|
| `powershell_regex` | 中 | ✓ | 转义特殊字符（`` `$ ``、`[`→`` `[`` 等），重试 ≤2次 |
| `subprocess_timeout` | 低 | ✓ | 增加超时时间或跳过 |
| `file_not_found` | 中 | ✓ | 检查路径、创建目录或跳过 |
| `syntax_error` | 高 | ✗ | 记录日志，状态设为 `failed_with_error` |
| `permission_denied` | 中 | ✗ | 记录日志，跳过该任务 |

### PowerShell Regex 错误修复指南

常见错误：变量未转义（如 `$price` 被解析为变量）

修复方法：
- `` `$ `` 转义美元符
- `` `[ `` `` `] `` 转义方括号
- `` `| `` 转义管道符
- 在双引号字符串中使用单引号包裹或转义

### Agent 错误处理流程

```
遇到错误
    ↓
分类（powershell_regex / timeout / syntax等）
    ↓
[可恢复] → 尝试修复 → 重试（≤2次）→ 成功则继续
    ↓
[不可恢复或重试耗尽] → 记录到 /shared/team-brain/errors/{team_id}/{agent_id}/
    ↓
状态更新为 `failed_with_error` → 不要卡住 → 继续下一个子任务
```

### 心跳机制

Agent 在执行过程中定期更新心跳（每分钟）：
```python
# Python 示例
import json
from datetime import datetime
status_file = "/shared/team-brain/teams/{team_id}.json"
with open(status_file) as f:
    s = json.load(f)
for a in s["agents"]:
    if a["id"] == "{agent_id}":
        a["last_heartbeat"] = datetime.now().isoformat()
        a["status"] = "in_progress"
        a["progress"] = "60%"
with open(status_file, "w") as f:
    json.dump(s, f)
```

### 健康检查命令

协调人使用 health-monitor.py 检测 Agent 存活状态：

```bash
# 检查单个团队
python health-monitor.py check <team_id>

# 持续监控（每秒刷新）
python health-monitor.py watch <team_id>

# 所有团队汇总
python health-monitor.py summary
```

超时阈值：120 秒无心跳视为已挂（`is_stale=True`）

---

## team-brain.py 命令

```bash
# 启动团队（默认5个专家，最多5并发）
python team-brain.py launch "<topic>" "<description>" [max_agents]

# 查看团队状态
python team-brain.py status [team_id]

# 查看所有发现
python team-brain.py findings <team_id>

# 查看辩论
python team-brain.py debates <team_id>

# 发起挑战
python team-brain.py challenge <team_id> <from_agent> <to_agent> "<issue>"

# 裁决辩论（协调人）
python team-brain.py resolve <team_id> <debate_id> "<resolution>"

# 生成最终报告
python team-brain.py report <team_id>
```

---

## Agent rules.md 模板

```markdown
# rules.md — {role} Agent

## 团队脑协议（默认启用）
1. 读 /shared/team-brain/teams/{team_id}.json 了解任务和团队状态
2. 分析结果写入 /shared/team-brain/findings/{domain}/ 目录
3. 定期更新 /shared/team-brain/teams/{team_id}.json 中的进度和心跳
4. 发现其他Agent有逻辑问题时，在 /shared/team-brain/debates/{team_id}/ 下发起挑战

## 错误处理（默认启用）
- 遇到 PowerShell regex 错误：转义特殊字符后重试（≤2次）
- 遇到不可恢复错误：记录到 /shared/team-brain/errors/{team_id}/{agent_id}/
- 状态更新为 `failed_with_error`，不要卡住，继续下一个子任务
- 同一错误出现 3 次以上 → 必须通知协调人

## 协作边界
- 专注自己的专业领域，不越界分析
- 发现跨专业关联时，通知协调人
- 置信度低时明确标注，不假装精确

## 团队规模
- 默认：最多 5 名专家并发
- 可选：通过 team-brain.py launch 的 max_agents 参数调整
```

### 心跳更新频率

- 正常执行：每分钟更新一次 `last_heartbeat`
- 遇到错误：立即更新（包含错误信息）
- 完成后：更新为 `done` 并写入 findings 路径

---

## 团队规模配置建议

| 任务复杂度 | 推荐专家数 | 说明 |
|-----------|------------|------|
| 简单问题 | 2-3 | 快速响应，协调开销低 |
| 标准任务 | 4-5 | 默认配置，平衡效率和覆盖 |
| 复杂问题 | 6-8 | 需要更多视角，可选启用 |
| 全面研究 | >8 | 仅在明确声明时使用 |

---

## 实施文件

| 文件 | 说明 |
|------|------|
| `agent-team-orchestration/scripts/team-brain.py` | 核心引擎（v3.4，智能规划+错误处理） |
| `agent-team-orchestration/scripts/self-heal.py` | 自我修复引擎（错误分类+修复策略） |
| `agent-team-orchestration/scripts/health-monitor.py` | 健康检查系统（心跳检测+超时告警） |
| `agent-team-orchestration/scripts/health-dashboard.py` | Web 监控面板（Phase3） |
| `agent-team-orchestration/scripts/auto-decider.py` | 自动决策引擎（Phase3） |
| `agent-team-orchestration/references/team-brain-protocol.md` | 协议参考（本文档） |
| `shared/team-brain/` | 运行时目录（自动创建） |

---

## 与原 agent-team-orchestration 的关系

| 原功能 | 升级后 |
|--------|--------|
| 协调人追踪状态 | 团队脑 status.json（去中心化读写） |
| Agent仅向协调人汇报 | Agent直接写 findings/（同伴可见） |
| Reviewer只检查最终产出 | Agent可主动发起 debates/（相互监督） |
| 星形通讯（全部经协调人） | 网状通讯（通过共享目录直接交互） |

**向后兼容**：不使用 team-brain 协议时，降级为原有的星形辐射模式