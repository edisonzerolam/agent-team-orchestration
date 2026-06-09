# 专家小组协作改善协议 v2.0

> 本协议定义了多专家小组在执行任务时的完整协作流程，涵盖三阶段、时间盒、Token预算、动态调整和质量门。

---

## 1. 三阶段协议（Three-Phase Protocol）

### 1.1 Pre-task Phase（任务前对齐阶段）

**触发条件：**
- 复杂度 ≥ 中等（见第2节）
- 用户声明 `// full-discussion`

**流程：**
1. Orchestrator 判断复杂度等级
2. 设置状态为 `Pre-task Discussion`
3. 每位专家独立提交意见（互相不可见，防止锚定）
   - 输出路径：`/shared/team-brain/pre-task/{team_id}/{agent_id}-opinion.md`
   - 超时时间：5分钟 / 专家，超时视为"无异议"
4. Orchestrator 识别冲突 → 发起辩论轮（最多2轮，每轮10分钟）
5. Orchestrator 裁定剩余冲突 → 输出共识计划
   - 输出路径：`/shared/team-brain/pre-task/{team_id}/{team_id}-consensus.md`
6. Orchestrator → `Assigned`，向 Builder 传递确认的执行计划

**输出物：**
- 各专家意见文件（opinion）
- 共识计划文件（consensus）

---

### 1.2 Mid-task Phase（任务执行阶段）

**状态：** `In Progress`

**规则：**
- Builder 按计划执行，定时输出进度注释
- 遇到阻塞立即升级（见第6节）
- 每完成关键节点写 checkpoint（见 checkpoint-protocol.md）
- 严禁闲聊（见第9节）

**动态调整：**
- 每15分钟检查一次复杂度是否升级
- Token消耗达到预算50%时触发预警
- 详见第5节动态调整触发条件

---

### 1.3 Post-task Phase（任务后综合阶段）

**触发条件：** Reviewer 批准后

**流程：**
1. Orchestrator 设置状态为 `Consensus Check`
2. 调用 `synthesis-check.py`：
   ```bash
   python scripts/synthesis-check.py <team_id> <final_report_path>
   ```
3. 每位专家接收确认请求："Final report at {path}. Confirm: ✅ / ⚠️ / ❌"
   - 超时时间：5分钟 / 专家，超时视为"无异议"
4. `synthesis-check.py` 收集响应并生成报告：
   - 全部 ✅ → `status="delivered"`
   - 任何 ⚠️ → `status="delivered_with_concerns"`，附上关注点
   - 任何 ❌ → `status="returned_to_builder"`，附上异议
5. Orchestrator 根据结果采取行动，向用户报告

**输出格式：**
```json
{
  "team_id": "...",
  "status": "delivered | delivered_with_concerns | returned",
  "votes": {
    "agent-1": "✅",
    "agent-2": "⚠️ concerned about X",
    "agent-3": "❌ objection: Y"
  },
  "report_path": "synthesis/{team_id}-final.md"
}
```

**跳过条件：**
- 简单任务（单一专家，无跨域验证需求）
- 时间紧迫交付（记录跳过原因）

---

## 2. 复杂度分级（Complexity Classification）

| 等级 | 触发条件 | 时间盒 | Token预算（估算） | 适用场景 |
|------|---------|--------|-----------------|---------|
| **简单（Simple）** | 无高关键词，且中关键词<2 | 5 min | ~5K tokens | 纯执行类、单一答案查询 |
| **中等（Medium）** | 高关键词≥1 且 <2，或中关键词≥2 | 15 min | ~20K tokens | 分析报告、多步骤操作 |
| **复杂（Complex）** | 高关键词≥2，或用户声明 `// full-discussion` | 30 min | ~50K tokens | 策略规划、多专家研判 |
| **超复杂（Ultra）** | 高关键词≥3，或涉及多个领域专家 | 60 min | ~100K tokens | 投资决策、跨学科研究 |

**高关键词：** `分析`、`研究`、`评估`、`策略`、`规划`、`投资`、`决策`
**中关键词：** `对比`、`检查`、`审核`、`讨论`

**自动判定算法：**
```python
HIGH_KEYWORDS = ["分析", "研究", "评估", "策略", "规划", "投资", "决策"]
MED_KEYWORDS   = ["对比", "检查", "审核", "讨论"]

def classify_complexity(task_desc):
    h = sum(1 for k in HIGH_KEYWORDS if k in task_desc)
    m = sum(1 for k in MED_KEYWORDS if k in task_desc)
    if h >= 3:
        return "ultra"
    elif h >= 2:
        return "complex"
    elif h >= 1 or m >= 2:
        return "medium"
    else:
        return "simple"
```

---

## 3. 时间盒机制（Time Boxing）

### 3.1 时间盒分级

| 复杂度 | Pre-task讨论 | Mid-task执行 | Post-task确认 | 总时间上限 |
|--------|------------|-------------|--------------|-----------|
| Simple | 禁用 | 5 min | 禁用 | 5 min |
| Medium | 5 min | 15 min | 5 min | 25 min |
| Complex | 10 min | 30 min | 10 min | 50 min |
| Ultra | 15 min | 60 min | 15 min | 90 min |

### 3.2 时间盒规则

- 每个阶段单独计时，超时强制进入下一阶段
- 超时后默认策略：无共识则 Orchestrator 裁定，"no objection" 视为通过
- 用户可声明 `// extend [N]min` 延长时间盒（需说明理由）

### 3.3 硬截止（Hard Deadline）

- 单任务最大总时长：**2小时**（从 `Inbox` 状态开始计算）
- 达到硬截止时，无论完成度如何，立即终止并报告当前状态
- 超时未完成任务标记为 `Failed`，附带原因说明

---

## 4. Token预算框架（Token Budget）

### 4.1 预算分配

| 阶段 | Simple | Medium | Complex | Ultra |
|------|--------|--------|---------|-------|
| Pre-task | 0 | 5K | 10K | 15K |
| Mid-task | 5K | 20K | 40K | 80K |
| Post-task | 0 | 5K | 10K | 15K |
| **合计** | **5K** | **30K** | **60K** | **110K** |

### 4.2 预算监控

- Token消耗达到 **50%** 时触发预警，Orchestrator 重新评估是否继续
- Token消耗达到 **80%** 时触发强制检查点，任务必须产出中间产物
- Token消耗达到 **100%** 时立即终止，进入 Post-task 阶段（无论状态）

### 4.3 预算节省策略

- 简单任务跳过 Pre-task 和 Post-task 阶段
- 中等任务简化辩论轮（1轮代替2轮）
- 专家超时视为无异议，不占用辩论时间

---

## 5. 动态调整触发条件（Dynamic Adjustment）

### 5.1 触发类型

| 触发类型 | 条件 | 动作 |
|---------|------|------|
| **复杂度升级** | Pre-task 发现任务比预想更复杂 | 重新分类，提升时间盒和Token预算 |
| **范围蔓延** | Mid-task 发现额外需求或子任务 | 记录蔓延，评估是否拆分任务 |
| **共识失败** | 辩论轮2轮后仍有未解决冲突 | Orchestrator 强制裁定，记录异议 |
| **资源不足** | Token预算消耗过快或超时频繁 | 降级复杂度或减少专家数量 |

### 5.2 调整流程

1. 触发调整时，Orchestrator 立即记录调整原因（≥10字符）
2. 向相关专家广播调整内容（包含触发条件和影响评估）
3. 专家有5分钟时间确认收到并提出异议（否则默认接受）
4. 调整完成后继续执行，记录调整日志

### 5.3 用户干预语法

用户可通过以下语法主动干预协作流程：

| 语法 | 含义 | 处理方式 |
|------|------|---------|
| `// override` | 跳过当前阶段，直接进入下一阶段 | 记录并继续 |
| `// extend [N]min` | 延长当前阶段 N 分钟 | 需要说明理由（≥10字符） |
| `// abort` | 立即终止任务 | 任务标记为 Failed，附原因 |
| `// reduce-experts` | 减少参与专家数量 | 说明保留哪些专家及理由 |
| `// full-discussion` | 强制所有任务走完整流程 | 覆盖复杂度判定结果 |

---

## 6. 文件原子操作规范（Atomic File Operations）

### 6.1 写入规范

- 所有团队协作文件必须通过 `atomic-write.py` 写入（防止并发写入损坏）
- 文件命名格式：`{type}-{team_id}-{timestamp}.md`
  - 例：`opinion-expert-a-20240521_143022.md`
- 写入前先创建 `.tmp` 文件，完成后 rename（原子性保证）

### 6.2 checkpoint 写入

- Mid-task 每15分钟自动写入 checkpoint
- checkpoint 包含：当前状态、已消耗Token、已完成步骤、下一步计划
- checkpoint 路径：`/shared/team-brain/checkpoints/{team_id}/{task_id}-{timestamp}.md`

### 6.3 禁止操作

- ❌ 禁止直接覆盖已发布的共识文件
- ❌ 禁止在 checkpoint 之间删除任何团队产物
- ❌ 禁止修改已广播给专家的文件版本

---

## 7. 状态流（State Flow）

```
Inbox → Pre-task Discussion → Assigned → In Progress → Review → Consensus Check → Done
                              ↓
                          [跳过Pre-task]
                              ↓
                         (直接到Assigned)
```

**状态说明：**

| 状态 | 说明 | 可选/必选 |
|------|------|---------|
| `Inbox` | 任务已接收，待复杂度判定 | 必选 |
| `Pre-task Discussion` | 专家对齐中 | 简单任务跳过 |
| `Assigned` | 已分配给 Builder | 必选 |
| `In Progress` | Builder 执行中 | 必选 |
| `Review` | Reviewer 审核中 | 必选 |
| `Consensus Check` | 专家共识确认中 | 简单任务跳过 |
| `Done` | 任务完成，已交付 | 终止状态 |
| `Failed` | 任务失败（含超时/ abort/ 共识无法达成） | 终止状态 |

**状态转换规则：**
- 每个转换必须记录：转换时间、触发原因、操作者
- 转换时向所有相关专家广播
- 跳过某个可选阶段时，必须记录跳过原因

---

## 8. 防闲聊机制（Anti-Chat Protocol）

### 8.1 定义

闲聊：指与当前任务执行无直接关联的讨论、感想、寒暄或非必要沟通。

### 8.2 判定标准

以下情况**不属于**闲聊：
- ✅ 任务相关的技术讨论和方案辩论
- ✅ 进度状态更新和问题升级
- ✅ 对其他专家意见的正式回应（针对任务）
- ✅ checkpoint 写入和确认

以下情况**属于**闲聊：
- ❌ "这个任务挺有意思的"
- ❌ "我觉得可以这样做"（无具体方案）
- ❌ 与任务无关的感叹或评论
- ❌ 重复确认已达成共识的内容

### 8.3 处理方式

- 发现闲聊，Orchestrator 发送提醒："请专注任务执行"
- 再次发现闲聊，Orchestrator 要求暂停非必要讨论
- 持续闲聊的专家标记为低优先级（后续任务分配减少）

---

## 9. 防形式主义机制（Anti-Formalism Protocol）

### 9.1 问题定义

形式主义：指为满足流程形式而进行无实质内容的操作，例如：
- 理由不足的讨论延长
- 无实质内容的确认轮次
- 为通过共识检查而发表无关意见

### 9.2 形式主义检测规则

**发言/操作必须满足以下条件：**

| 要求 | 说明 |
|------|------|
| **理由 ≥10 字符** | 每个关键操作必须有≥10个字符的理由说明 |
| **段落引用** | 理由必须引用具体内容（文件、章节、行号等），不能泛泛而谈 |
| **时间戳要求** | 操作必须有明确的时间戳，不得"事后补录" |

**示例：**
- ✅ 有效发言："我认为方案A更好，因为其时间复杂度 O(n) 优于方案B的 O(n²)，详见 consensus.md §3.2"
- ❌ 无效发言："我觉得A更好"
- ❌ 无效发言："方案A不错"（不足10字符）

### 9.3 检测与处理

- Orchestrator 实时检测所有发言和操作
- 发现形式主义，标记为 `warning`，要求补充实质内容
- 3次警告后，相关专家的意见降级为"参考"而非"正式意见"
- 确保每轮讨论都有实质内容推进

---

## 10. 成功标准（Success Criteria）

| 指标 | 目标值 | 测量方式 |
|------|--------|---------|
| Pre-task 讨论触发率 | ≥ 90%（Complex+任务） | 记录触发/未触发及原因 |
| 共识覆盖率 | ≥ 80%（完成任务中达共识的比例） | Post-task 统计 |
| 效率影响 | < 10%（相比无协议执行的时间增加） | 对比同类任务耗时 |
| 形式主义发生率 | < 5%（形式主义操作次数/总操作次数） | 自动检测标记 |
| 用户干预满意度 | ≥ 85%（用户对干预结果的认可度） | 用户反馈收集 |

---

## 11. 新增组件清单

| 组件 | 路径 | 说明 |
|------|------|------|
| `atomic-write.py` | `scripts/atomic-write.py` | 原子文件写入，防止并发损坏 |
| `token-budget-tracker.py` | `scripts/token-budget-tracker.py` | Token预算实时监控和预警 |
| `checkpoint-poller.py` | `scripts/checkpoint-poller.py` | 自动checkpoint轮询和恢复 |
| `synthesis-check.py` | `scripts/synthesis-check.py` | Post-task 专家共识检查 |

---

## 12. Phase 1/2/3 实施计划摘要

| Phase | 内容 | 完成标准 |
|-------|------|---------|
| **Phase 1（当前）** | 协议文档化 | 本文档已创建并归档 |
| **Phase 2** | 工具实现 | atomic-write.py、token-budget-tracker.py、checkpoint-poller.py 部署完成 |
| **Phase 3** | 流程集成 | 所有团队任务通过本协议执行，达到成功标准指标 |

---

*本文档为专家小组协作改善方案 v2.0 的核心协议文件。*