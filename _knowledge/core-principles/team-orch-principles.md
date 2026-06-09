# agent-team-orchestration 核心原则

> 基于Karpathy原则框架 + 专家知识整合（2026-05）

---

## P1 角色单一性（Orchestrator优先）

**来源**：Karpathy Surgical Changes + CrewAI Role-Based Agents + OpenAI Supervisor模式

**适用场景**：多Agent任务分配、团队角色定义、新Agent加入

**具体做法**：
- 每个子Agent只有一个主角色，不重叠（Builder/Reviewer/Ops/Researcher）
- Orchestrator专职路由和状态管理，不做执行工作
- 角色定义时同时定义能力边界和工具集
- 新任务到来时，Orchestrator根据角色匹配度分配，不跨角色指派

**反面案例**："这个任务Builder也能做-reviewer的活，让它顺手做了" → 导致职责扩散、质量门失效

---

## P2 交接显式化（Handoff Protocol）

**来源**：Karpathy Goal-Driven Execution + LangChain Explicit Handoff + OpenAI Orchestrator/Worker模式

**适用场景**：任何跨Agent的工作传递（Builder→Reviewer, Researcher→Writer等）

**具体做法**：
- Handoff消息必须包含5要素：已完成的摘要 / 产物路径 / 验收方式 / 已知风险 / 下一步行动
- 禁止模糊交接："Done, check the files."
- 产物写入共享目录，路径在Handoff中明确说明
- Orchestrator负责验证交接完整性，不依赖子Agent自行汇报

**反面案例**：交接时只说"做完了"，导致下游Agent重复猜测上游状态

---

## P3 状态 Owned by Orchestrator

**来源**：Anthropic Claude Agent最佳实践 + Karpathy状态外部化 + OpenAI State Machine模式

**适用场景**：任务状态追踪、进度监控、崩溃恢复

**具体做法**：
- 所有任务状态存储在Orchestrator控制的外部记录（文件/DB/任务板）
- 子Agent不得自行更新状态 → 防止状态不一致
- 每个状态转换记录：who / what / why / timestamp
- 崩溃恢复时，Orchestrator从最后状态重建，不依赖子Agent记忆

**反面案例**：子Agent自行更新"完成"状态但实际未完成 → Orchestrator失去可见性

---

## P4 最小上下文·手术式操作

**来源**：Karpathy Surgical Changes + ACE Framework Aim层定义

**适用场景**：上下文窗口紧张、长任务、复杂多步骤工作

**具体做法**：
- 给每个子Agent只提供必要的上下文，不传整个代码库或历史记录
- 任务描述精确：包含"做什么"+"在哪里"+"如何验证"
- 长任务分批次：每个子Agent处理当前批次，不跨批次依赖
- Orchestrator负责上下文压缩和分发策略

**反面案例**：给Agent传完整代码库让它自己理解 → 消耗大量token + 效果差

---

## P5 短反馈·自纠错·幂等交付

**来源**：Karpathy短反馈周期 + PE Institute幂等性原则 + PE Institute生产级Agent工作流

**适用场景**：质量保证、可恢复性设计、长运行任务

**具体做法**：
- 每个子步骤完成后立即验证（测试命令/检查清单），不等最终交付才检查
- Agent内置self-correction能力：输出时带"我哪里可能有问题"的自我审视
- 所有产物写入支持幂等覆盖（或atomic write），重复执行不产生不一致
- 优雅降级：部分子Agent失败时，系统不整体崩溃，保留已完成的工作

**反面案例**：等全部完成后才测试 → 最后发现早期决策错误，修复成本极高

---

## 补充原则（非核心但重要）

### P5b 人在回路（Human-in-the-Loop）

**来源**：PE Institute 7 Non-negotiables + Anthropic安全边界

- 关键决策节点（交付审批/高风险操作/资源分配）保留人工确认
- Orchestrator有权限暂停任务等待人工输入
- 不等于每步都审批，而是关键门才审批

### P5c 可观测性（Observability）

**来源**：PE Institute Observability + LangChain异步监控

- 每步操作有trace日志（谁/何时/做了什么/消耗多少token）
- 共享监控面板，Orchestrator可实时查看团队健康状态
- 异常时自动告警（Agent静默/超长运行/错误率升高）

---

## P6 超时管理原则

**来源**：Karpathy Goal-Driven Execution + Auditor S2超时策略

**适用场景**：spawn子agent前必须评估

**具体做法**：
- Step 0（Spawn前）：调用时长评估函数，输入任务描述→输出T1-T5等级
- Step 1：根据等级设置timeout参数
- Step 2：超时后执行三级处理（续接/重来/人工介入）
- Step 3：超时记录→LEARNINGS.md自学习闭环

**反面案例**：`先spawn再说，超时再处理` → 无标准超时导致任务失控