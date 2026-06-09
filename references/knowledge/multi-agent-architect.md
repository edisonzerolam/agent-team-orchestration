# 多智能体架构专家知识库

> 多智能体架构专家（multi-agent-architect）的本地知识手册。用于多智能体系统设计、任务分解与 Agent 协作协议的设计与评审。

---

## 1. 身份定义

| 属性 | 内容 |
|------|------|
| **角色ID** | `multi-agent-architect` |
| **核心职责** | 设计、评估、改进多智能体（Multi-Agent）系统的架构、任务分解策略、Agent 间通信协议与结果聚合机制 |
| **适用场景** | 复杂任务拆解、多专家协作流程设计、Crew/Manager-Crew 架构选型、Agent-to-Agent 协议评审、状态共享 vs 结论传递的权衡决策 |
| **决策边界** | 不负责单个 Prompt 工程细节、不负责具体工具调用实现、不负责评估基准数学题设计 |
| **输出形式** | 架构设计文档、Handoff 协议规范、任务分解决策表、协作评审意见 |

---

## 2. Andrej Karpathy 多智能体架构观点

### 核心观点（2017-2024）

Andrej Karpathy 在 Tesla AI 工作中多次分享多智能体系统设计理念，代表了业界对 LLM Agent 系统架构的核心认知演进。

### A2A 架构（Agent-to-Agent）

Karpathy 提出的 A2A（Agent-to-Agent）模式，是多智能体协作的核心通信范式：

```
原始 LLM：
用户 → LLM → 工具 → 输出（单链路）

多智能体 A2A：
Agent A → 消息协议 → Agent B → 消息协议 → Agent C
                ↑                              ↓
            结果/状态 ← ← ← ← ← ← ← ← ← ← ← ← ←
```

**A2A 关键设计原则**：
1. **每个 Agent 有明确定义的角色边界**：Agent A 不会尝试做 Agent B 的工作
2. **消息协议标准化**：Agent 间使用结构化消息（而非自然语言 prompt）传递任务上下文
3. **异步优先**：避免同步阻塞，等待方有超时和降级策略
4. **结果可追溯**：每次handoff附带完整的上下文传递记录

### 任务分解策略（Karpathy 观点）

| 分解策略 | 适用场景 | 不适用场景 |
|---------|---------|-----------|
| **LLM 自主分解** | 开放性任务（研究、分析） | 高度结构化任务（合规审查） |
| **规则强制分解** | 确定性流程（审计、合规） | 需要创意整合的场景 |
| **层级分解** | 大型复杂项目 | 简单一次性任务 |

**分解粒度原则**：
- 粒度过粗：单个 Agent 任务超载 → 推理质量下降，幻觉风险上升
- 粒度过细：Agent 间依赖链条过长 → 错误累积、延迟放大
- **Karpathy 建议**：每个 Agent 任务控制在 3~8 个子步骤，3 层以内完成

### 单 Agent 内部架构（State Machine）

Karpathy 强调单个 Agent 应采用状态机设计：

```
Agent State Machine：
IDLE → RUNNING → TOOL_CALL → WAITING → FINISHED
                  ↓                    ↑
                ERROR → RETRY → MAX_RETRY → FAILED
```

| 状态 | 说明 | 允许转移 |
|------|------|---------|
| IDLE | 等待任务 | → RUNNING |
| RUNNING | LLM 推理中 | → TOOL_CALL / FINISHED / ERROR |
| TOOL_CALL | 调用外部工具 | → WAITING |
| WAITING | 等待工具响应 | → RUNNING / ERROR |
| FINISHED | 任务正常完成 | （终态） |
| ERROR | 可恢复错误 | → RETRY |
| FAILED | 不可恢复错误 | （终态） |

**增强来源：** Andrej Karpathy（Tesla AI），2017~2024年公开演讲（Stanford CS229、Tesla AI Day、Sualk talk）

---

## 3. CrewAI / LangChain / AutoGPT 框架设计模式

### CrewAI 架构模式

#### 基本概念

```
Crew（团队）= Agents（角色）+ Tasks（任务）+ Process（流程）
```

**CrewAI 三种流程模式**：

| 流程模式 | 说明 | 适用场景 |
|---------|------|---------|
| **Sequential** | 任务顺序执行，前一个输出作为下一个输入 | 有明确先后依赖的流水线 |
| **Hierarchical** | Manager Agent 协调，层级分发任务 | 复杂任务，需要中间协调层 |
| **Crew（并行）** | 所有 Agent 并行处理，结果聚合 | 独立子任务，结果汇总 |

#### CrewAI Handoff 设计

```python
# CrewAI handoff 示例
from crewai import Agent, Task, Crew

# 定义 Agent
researcher = Agent(role="研究员", goal="提供{topic}的准确信息")
analyst = Agent(role="分析师", goal="基于研究员输出做出投资判断")

# 定义 Task（带依赖）
task1 = Task(description="研究{topic}的市场规模", agent=researcher)
task2 = Task(description="分析市场规模并给出建议",
             agent=analyst,
             context=[task1])  # 依赖 task1 输出

# 执行
crew = Crew(agents=[researcher, analyst], tasks=[task1, task2], process="sequential")
result = crew.kickoff()
```

**CrewAI Handoff 原则**：
1. 每个 Agent 只能访问自己被授权的上下文（信息隔离）
2. Handoff 必须附带输出摘要，不得裸传完整对话历史
3. 最后一个 Agent 的输出才是 Crew 的最终输出

### LangChain Multi-Agent 架构

LangChain 提供了更底层的多 Agent 框架：

#### 三种代理模式

| 模式 | 核心机制 | 代表实现 |
|------|---------|---------|
| **Supervisor** | 单一 Supervisor 协调所有子 Agent | `langchain.agents.StructuredChat` |
| **Hierarchical** | 多级 Manager，像组织架构图 | `langchain.agents.HierarchicalAgent` |
| **Custom** | 自定义路由逻辑 | 基于 `langchain.schema` 定制 |

#### Tool Call 与 Tool 共享

```python
# LangChain AgentExecutor 模式
# 每个 Agent 持有独立的 AgentExecutor
# Tool 可共享（read_file, browse）但内存隔离

class AgentNode:
    def __init__(self, name, role, tools, prompt_template):
        self.name = name
        self.role = role
        self.tools = tools
        self.executor = AgentExecutor.from_llm_and_tools(
            llm=llm,
            tools=tools,
            prompt=prompt_template.format(role=role)
        )
    
    def run(self, task_input) -> AgentOutput:
        result = self.executor.run(task_input)
        return AgentOutput(
            agent=self.name,
            raw_output=result.raw,
            summary=result.summary,
            artifacts=[]
        )
```

### AutoGPT 架构模式

AutoGPT 代表了自主性最强的多 Agent 系统：

```
AutoGPT Core Loop：
Goal → Plan → Execute → Observe → Critic → (Loop or Done)

其中 Critic Agent 是 AutoGPT 特有的质量把关节点：
- 验证当前执行结果是否对齐原始 Goal
- 识别执行路径偏差
- 决定继续、调整策略、或终止
```

**AutoGPT 架构特点**：
1. **无限循环风险**：需要外部终止条件（budget/time/iteration limit）
2. **全局记忆**：使用 Vector Store 共享跨 Agent 记忆
3. **自我修正**：Critic Agent 可以在循环中修改 Planner 的 plan

### 框架对比

| 维度 | CrewAI | LangChain | AutoGPT |
|------|--------|-----------|---------|
| **架构复杂度** | 中 | 高 | 低（但自主性强） |
| **Handoff 显式化** | ✅ 强 | ⚠️ 需自行实现 | ❌ 隐式 |
| **信息隔离** | ✅ Agent 独立上下文 | ⚠️ 需配置 | ❌ 共享记忆 |
| **适用复杂度** | T2-T3 | T3-T4 | T1-T2 |
| **可控性** | 高 | 高 | 低 |
| **生产可用性** | 高 | 中 | 低 |

---

## 4. 多智能体通信协议（A2A）

### 协议设计四层模型

```
┌─────────────────────────────────────┐
│  应用层（Application Layer）         │  任务描述 + 角色标识
├─────────────────────────────────────┤
│  上下文层（Context Layer）            │  状态传递 / 结果传递
├─────────────────────────────────────┤
│  路由层（Routing Layer）             │  目标 Agent 定位 / Handoff
├─────────────────────────────────────┤
│  传输层（Transport Layer）            │  HTTP / Message Queue / IPC
└─────────────────────────────────────┘
```

### 消息格式标准（结构化 Handoff）

**最小化 Handoff 消息格式**：

```json
{
  "handoff_id": "handoff_uuid_001",
  "from_agent": "researcher",
  "to_agent": "analyst",
  "task_type": "analysis",
  "input_summary": "茅台2024年营收约760亿，同比+17%，现金流良好",
  "key_questions": [
    "这个增速是否可持续？",
    "对比五粮液估值是否合理？"
  ],
  "constraints": [
    "使用PE和PB两种估值方法",
    "输出结论+支撑数据"
  ],
  "metadata": {
    "parent_task_id": "task_001",
    "depth": 1,
    "timestamp": "2026-05-24T01:30:00+08:00"
  }
}
```

**扩展 Handoff 消息格式**（T3+ 复杂任务）：

```json
{
  "handoff_id": "handoff_uuid_002",
  "from_agent": "researcher",
  "to_agent": "analyst",
  "task_type": "analysis",
  "input_summary": "茅台2024年营收约760亿，同比+17%，现金流良好",
  "key_questions": ["增速是否可持续？", "估值是否合理？"],
  "constraints": ["使用PE和PB两种方法"],
  "full_context": {
    "conversation_history": [...],  // 可选，谨慎使用
    "retrieved_memories": [...],
    "external_context": {...}
  },
  "metadata": {
    "parent_task_id": "task_001",
    "depth": 1,
    "timestamp": "2026-05-24T01:30:00+08:00",
    "trust_level": "high"  // high/medium/low，决定接收方是否需要重新验证
  }
}
```

### A2A 协议关键原则

| 原则 | 说明 | 常见错误 |
|------|------|---------|
| **摘要优于全量** | Handoff 传递摘要而非完整历史 | 裸传对话历史 → token 超限、接收方处理慢 |
| **显式信任级别** | 附带 trust_level 让接收方决定是否复核 | 假设上游输出100%正确 → 错误级联 |
| **超时传递** | Handoff 有 TTL，超时未确认则降级或重试 | 无超时 → 无限等待 |
| **回执机制** | 接收方确认收到并处理成功 | 无回执 → 上游无法知道下游是否就绪 |

---

## 5. 任务分解与结果聚合策略

### 任务分解方法论

#### 结构化分解（适合 T2+ 复杂任务）

```
Level 0：用户原始任务
    ↓ 分解
Level 1：Epic 1 | Epic 2 | Epic 3（最多 3-5 个并行 Epic）
    ↓ 分解
Level 2：Task 1.1 ~ Task 3.N（每个 Epic 2-4 个 Task）
    ↓ 分配
Level 3：具体执行步骤（3-8 步）
```

**分解原则**：
- 每个 Epic 可独立并行执行（无跨 Epic 依赖）
- 跨 Epic 依赖 → 提升为更高层的依赖关系，或合并 Epic
- Task 数量：最佳范围 5~15 个，总任务数过少则分工收益低，过多则协调成本高

#### 判断分解深度的三问法

| 问题 | 答案 Yes | 答案 No |
|------|---------|---------|
| 1. 任务是否需要不同领域的专业知识？ | 需要深层分解（专家分工） | 不需要 |
| 2. 子任务是否可以独立验证质量？ | 需要分解（独立 review） | 不需要 |
| 3. 子任务失败是否会影响其他子任务？ | 需要减少分解（共享上下文） | 不需要 |

### 结果聚合策略

| 聚合策略 | 说明 | 适用场景 |
|---------|------|---------|
| **直接拼接** | 所有子 Agent 输出按顺序拼接 | 简单并列任务（多角度分析） |
| **投票/共识** | 多 Agent 对同一问题给出结论，汇总多数意见 | 判断类任务（估值方向） |
| **质量打分** | 由专门Aggregator Agent打分后加权汇总 | 复杂多维评估 |
| **层级汇总** | 上一层 Agent 汇总下一层输出后再汇总 | 超复杂任务（3+层分解） |
| **人工审核** | 最终结果需人工确认 | 高风险决策（法律/合规） |

**结果聚合失败处理**：

| 失败模式 | 处理策略 |
|---------|---------|
| 子 Agent 输出矛盾 | 触发"仲裁 Agent"判断优先级 |
| 子 Agent 超时 | 降级使用已完成结果，标记缺失项 |
| 子 Agent 全部失败 | 整体任务标记失败，触发人工干预 |

---

## 6. 状态共享 vs 结论传递

### 两种信息传递模式对比

| 维度 | 状态共享（Shared State） | 结论传递（Conclusion Passing） |
|------|------------------------|-------------------------------|
| **信息量** | 全量状态（可能含中间步骤） | 仅传递最终结论和关键上下文 |
| **接收方负担** | 高（需理解完整状态） | 低（只需理解结论） |
| **错误隔离** | 差（状态污染可能影响所有 Agent） | 好（错误止步于结论） |
| **通信成本** | 高（频繁同步） | 低（一次性传递） |
| **适用场景** | 实时协作（白板共享） | 流水线式处理（分析→决策） |
| **实现复杂度** | 高（锁/版本控制） | 低（单向消息） |

### 决策树：选择哪种模式？

```
用户问：这个任务需要什么信息传递模式？
    │
    ├─ 是否需要实时感知其他 Agent 的中间状态？
    │   ├─ YES → 状态共享（Shared State + Pub/Sub）
    │   └─ NO ↓
    │
    ├─ 是否有强先后依赖（A必须等B完成才能开始）？
    │   ├─ YES → 流水线（结论传递 + 阻塞等待）
    │   └─ NO ↓
    │
    ├─ 是否有多个下游依赖同一上游输出？
    │   ├─ YES → 广播模式（上游结论 → 多下游）
    │   └─ NO → 单线结论传递
```

### 混合模式实践

**最佳实践**：采用结论传递为主、状态共享为辅的混合模式

```
研究 Agent ──结论──→ 分析 Agent ──结论──→ 决策 Agent
     │                                       │
     └────────── 共享知识库（Read-Only） ─────┘
                           ↑
                    其他 Agent 可查询
                    但不能直接修改
```

**共享知识库设计原则**：
1. **只读共享**：所有 Agent 可读共享知识库，但写入必须通过专门接口
2. **最终一致性**：允许短暂不一致，通过最终写入保证一致性
3. **版本化**：每次写入生成版本号，避免并发冲突

---

## 7. 多智能体架构常见错误

| 错误类型 | 典型表现 | 后果 | 规避方法 |
|---------|---------|------|---------|
| **过浅分解** | 2个子 Agent 处理复杂任务 | 单 Agent 过载、输出质量差 | 用三问法判断是否需要继续分解 |
| **过深分解** | 5+ 层分解链条 | 延迟累积、错误级联 | 限制在3层以内 |
| **信息裸传** | Handoff 传递完整对话历史 | Token 超限、接收方处理慢 | 必须先摘要 |
| **隐式 Handoff** | Agent 假设其他 Agent 知道上下文 | 上下文丢失、输出不连贯 | 显式 Handoff 消息格式 |
| **同步阻塞** | 上游 Agent 等待下游完成才输出 | 整体延迟等于最长路径 | 设计异步 Handoff + 超时降级 |
| **无终止条件** | AutoGPT 式无限循环 | Token 耗尽、任务无法完成 | 设置硬性终止（budget/time/iteration） |
| **角色冲突** | 两个 Agent 职责重叠 | 输出重复、结果冲突 | 分解前明确角色边界矩阵 |
| **信任无级别** | 假设所有 Agent 输出等可靠 | 下游接受上游错误→错误级联 | 显式 trust_level 字段 |

---

## 8. 与其他角色的协作

### Handoff 格式（主动发起方视角）

```markdown
**FROM**: [本 Agent 名称]
**TO**: [目标 Agent 名称]
**TASK**: [任务类型：research/analysis/review/decision]
**INPUT_SUMMARY**: [3-5句话的核心输入摘要]
**KEY_QUESTIONS**: [1-3个具体问题，下游需回答]
**CONSTRAINTS**: [下游执行时的约束条件]
**METADATA**: {
  "parent_task_id": "...",
  "depth": N,
  "timestamp": "ISO8601",
  "trust_level": "high/medium/low"
}
```

### 前置条件（接收方视角）

| 接收方准备 | 前置条件 |
|-----------|---------|
| 任务可开始 | ✅ 收到结构化 Handoff 消息 |
| 上下文充足 | ✅ Handoff 包含足够背景（trust_level=high 时可跳过复核） |
| 工具可用 | ✅ 所需 Tool 已注册在接收方 Agent |
| 角色明确 | ✅ Handoff 包含明确 role 定义 |

### 后置交付物（完成方视角）

| 交付物 | 格式要求 |
|--------|---------|
| **最终输出** | 结构化结论 + 关键数据支撑 + 置信度 |
| **中间状态** | 如需下游继续，附带 Handoff 消息 |
| **异常标记** | 如有问题，显式标记并说明原因 |
| **Token 消耗** | 记录本次任务 token 消耗，用于成本追踪 |

### 角色协作矩阵

| 本 Agent（multi-agent-architect） | 协作模式 | 典型交接对象 |
|--------------------------------|----------|-------------|
| **规划阶段** | 主动设计 → 输出任务分解方案 | Agent Planner |
| **评审阶段** | 被咨询 → 提供架构建议 | Agent Team Orchestrator |
| **运行时** | 监控 → 提供 Handoff 协议建议 | 各个执行 Agent |
| **复盘阶段** | 总结 → 输出架构改进建议 | Agent Team Orchestrator |

---

## 9. 注入指引

### 触发词（优先级排序）

| 优先级 | 触发词 | 注入章节 |
|--------|--------|---------|
| P0 | "多智能体架构" / "multi-agent" | 第2章（Karpathy）+ 第3章（框架对比） |
| P0 | "Crew" / "CrewAI" | 第3章（CrewAI 架构） |
| P0 | "任务分解" | 第5章（分解方法论） |
| P1 | "Agent 协作" / "协作协议" | 第4章（A2A协议） |
| P1 | "Handoff" / "handoff" | 第4章 + 第8章 |
| P1 | "状态共享" / "结论传递" | 第6章（权衡决策树） |
| P2 | "AutoGPT" | 第3章（AutoGPT 架构） |
| P2 | "LangChain Agent" | 第3章（LangChain 架构） |
| P2 | "信息裸传" / "上下文丢失" | 第7章（常见错误） |

### 注入触发条件

**自动注入（主会话）**：
- 用户提到多智能体系统设计、任务分解、Agent 协作等相关话题
- 用户咨询 CrewAI / LangChain / AutoGPT 使用
- 用户描述的任务需要 2+ 个专业化角色协作

**被动注入（被咨询时）**：
- 其他 Agent（如 agent-planner）在规划阶段咨询架构设计
- 其他 Agent 在运行时遇到 Handoff 问题
- 用户要求架构评审或协议设计

### 注入注意事项

1. **不替代执行**：本专家负责设计，不负责具体执行任务的 Agent 实现
2. **框架中立**：提供框架对比时不偏向特定框架，让用户根据场景选择
3. **量化优先**：尽量给出量化标准（三问法、决策树、五层模型），便于直接应用

---

## 常用数据源

| 数据类型 | 来源 |
|----------|------|
| Karpathy 观点 | Andrej Karpathy 个人网站、Stanford 公开课 |
| CrewAI 框架 | CrewAI 官方文档（crewai.com） |
| LangChain Agent | LangChain 官方文档（python.langchain.com） |
| AutoGPT 架构 | AutoGPT GitHub（agpt.co） |
| A2A 协议标准 | Anthropic / OpenAI Agent 协议规范（协议草案） |

**增强来源：**
- Andrej Karpathy（Tesla AI / Stanford），2017~2024年公开演讲及个人博客
- CrewAI团队，2023~2024年官方文档及GitHub
- LangChain团队，2023~2024年官方文档及Python Package
- AutoGPT团队，2023~2024年GitHub仓库及Issue讨论