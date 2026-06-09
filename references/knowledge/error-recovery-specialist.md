# 错误恢复专家知识库

> 错误恢复专家（error-recovery-specialist）的本地知识手册。用于 Agent 系统错误处理、容错降级、状态恢复时的方法论引用。

---

## 1. 错误分类体系（Error Classification）

### 1.1 按可恢复性分类

| 错误类型 | 定义 | 典型场景 | 处理策略 |
|----------|------|---------|---------|
| **可恢复错误（Recoverable）** | 临时性故障，单次重试或降级即可解决 | 网络超时、外部 API 限流、文件锁冲突、资源短暂不可用 | 重试 → 降级 → 告警 |
| **不可恢复错误（Non-Recoverable）** | 持久性故障，重试无意义，需人工介入或任务终止 | 参数校验失败、权限不足、目标资源不存在、逻辑断言失败 | 快速失败 → 记录上下文 → 通知主控 |
| **级联错误（Cascading）** | 子系统故障引发的连锁反应 | 依赖服务超时导致本服务队列积压、OOM 触发健康检查失败 | 熔断 → 隔离 → 降级 |
| **精神错误（Semantic/Hung）** | 进程存活但无法响应（假死） | 死锁、无限循环、同步调用阻塞 | 超时检测 → 强制中断 → 重启 |

### 1.2 按错误来源分类

```
错误来源分层
│
├── L1：基础设施层
│   ├── 网络不可达（DNS 失败 / 路由黑洞 / 防火墙）
│   ├── 存储介质故障（磁盘满 / I/O 延迟飙升）
│   └── 计算资源耗尽（CPU 打满 / 内存 OOM / 连接数耗尽）
│
├── L2：依赖服务层
│   ├── 外部 API 超时（第三方服务响应慢）
│   ├── 数据库连接池耗尽
│   └── 消息队列消费积压
│
├── L3：业务逻辑层
│   ├── 输入参数校验失败
│   ├── 业务规则冲突
│   └── 状态机非法转移
│
└── L4：Agent 系统层
    ├── LLM 调用失败（API 限流 / 模型不可用）
    ├── Tool 执行异常（工具超时 / 参数格式错误）
    └── 上下文超限（Token 溢出 / 内存溢出）
```

### 1.3 错误码命名规范（内部 Agent 使用）

```
ERR-[层级]-[类型]-[序号]
  └─层级：INF（基础设施）/ DEP（依赖服务）/ BIZ（业务）/ SYS（系统）
    └─类型：TMO（超时）/ VAL（校验）/ RES（资源）/ SEQ（顺序）
      └─序号：3位数字，001~999

示例：
ERR-DEP-TMO-001  → 依赖服务超时，第1个错误
ERR-SYS-CTX-002  → 系统上下文超限，第2个错误
ERR-BIZ-VAL-003  → 业务参数校验失败，第3个错误
```

---

## 2. 超时处理（Timeout vs Hang）

### 2.1 Timeout 与 Hang 的本质区分

| 维度 | Timeout（超时） | Hang（假死） |
|------|----------------|-------------|
| **进程状态** | 进程存活，已消耗合理时间 | 进程存活，但无法处理新任务 |
| **根本原因** | 目标响应时间超过预期 | 死锁 / 无限循环 / 同步阻塞 |
| **可预测性** | 可通过统计历史响应时间预设阈值 | 不可预测，发生时进程看似健康 |
| **检测方式** | 被动计时器触发 | 主动心跳检测（Heartbeat Probe） |
| **处理方式** | 等待一段时间后返回错误 | 强制杀死 / 重启进程 |

### 2.2 Timeout 分层配置策略

```
Timeout 分层设计
│
├── L1：操作级超时（Tool / API Call）
│   ├── 读取操作：5~30s（文件 I/O、数据库查询）
│   ├── 写入操作：10~60s（提交数据、写入文件）
│   └── 网络请求：10~30s（LLM API 调用建议 60s+）
│
├── L2：任务级超时（单个 Agent 任务）
│   ├── 简单查询：30s~2min
│   ├── 复杂分析：2~10min
│   └── 批量任务：10~30min
│
└── L3：会话级超时（整个 Agent Session）
    └── 默认 30min，建议上限 2h（防止资源泄漏）
```

### 2.3 Hang 检测：健康检查三板斧

| 检测方法 | 实现方式 | 检测间隔 | 适用场景 |
|---------|---------|---------|---------|
| **心跳检测** | 子进程每 N 秒向主进程发送心跳包 | 5~15s | 长时运行的子任务 |
| **进度轮询** | 主进程轮询子进程状态（如任务进度百分比） | 10~30s | 有明确阶段的任务 |
| **资源监控** | 监控进程 CPU / 内存使用率，0 持续超过阈值 | 1~5min | CPU 密集型任务 |

### 2.4 常见超时配置模板

```python
# Timeout 配置模板
TIMEOUT_CONFIG = {
    # 工具级
    "tool.read_file": 30,       # 秒
    "tool.write_file": 60,
    "tool.http_request": 90,    # LLM API 建议更长
    "tool.browser_action": 60,

    # 任务级
    "task.simple_query": 120,   # 2min
    "task.analysis": 600,       # 10min
    "task.batch_process": 1800, # 30min

    # 全局兜底
    "session_max": 7200,        # 2h
}
```

---

## 3. Graceful Degradation（优雅降级）

### 3.1 降级决策树

```
Agent 收到错误后决策流程：

错误发生
    │
    ├── 是否可恢复？（网络超时 / API 限流）
    │   ├── YES → 重试次数 < 最大重试数？
    │   │       ├── YES → 执行退避重试（Exponential Backoff）
    │   │       └── NO → 进入降级链
    │   └── NO → 快速失败，记录上下文
    │
    进入降级链（Fallback Chain）
        │
        ├── Fallback-1 可用？
        │   ├── YES → 执行 Fallback-1
        │   └── NO → Fallback-2 可用？
        │       ├── YES → 执行 Fallback-2
        │       └── NO → Fallback-3（最终降级，返回兜底响应）
```

### 3.2 降级模式分类

| 降级模式 | 描述 | 示例 | 适用场景 |
|---------|------|------|---------|
| **功能降级（Feature Degradation）** | 保留核心功能，关闭次要功能 | 搜索 Agent：关闭个性推荐，仅返回通用结果 | 非核心功能故障 |
| **精度降级（Precision Degradation）** | 用更快/更轻的方案替代高精度方案 | LLM 不可用时使用关键词匹配；图片识别降级为颜色统计 | LLM 服务不可用 |
| **延迟降级（Latency Degradation）** | 用预计算/缓存结果替代实时计算 | 实时行情不可用时返回最近缓存数据 | 数据源超时 |
| **范围降级（Scope Degradation）** | 缩小处理范围以保证完成度 | 批量处理100条失败时完成前50条 | 资源不足 |
| **完全降级（Full Degradation）** | 无法提供任何有效服务，返回兜底响应 | "服务暂时不可用，请稍后再试" | 系统级故障 |

### 3.3 降级链设计原则

| 原则 | 说明 |
|------|------|
| **幂等优先** | 每个降级方案必须可重复执行，不产生副作用 |
| **降级深度 ≤ 3** | 超过 3 层降级后应直接返回兜底，避免嵌套失败 |
| **降级方案必须预验证** | 上线前通过混沌测试验证降级链可用性 |
| **降级状态可观测** | 每次降级触发时必须记录：原方案、降级方案、降级原因、持续时间 |
| **降级后自动恢复** | 当上游服务恢复时，自动尝试恢复到原始方案 |

### 3.4 降级触发示例场景

```
场景1：LLM API 限流（HTTP 429）
  → Fallback-1：切换到备用模型（GPT-4 → GPT-3.5）
  → Fallback-2：使用本地小模型（Llama-7B）
  → Fallback-3：返回"当前咨询繁忙，请通过邮件联系"

场景2：知识库检索超时
  → Fallback-1：切换到全量索引（降精度）
  → Fallback-2：返回"我暂时无法检索知识库，以下是基于已有信息的回答："
  → Fallback-3：返回"知识库暂时不可用，建议稍后重试"

场景3：外部数据源不可用
  → Fallback-1：使用本地缓存数据（标注 freshness）
  → Fallback-2：返回历史数据（标注时效性）
  → Fallback-3：告知用户数据源不可用，建议手动查询
```

---

## 4. Circuit Breaker（熔断器）模式

### 4.1 熔断器三状态

```
           关闭（Closed）
           ↓ 失败率超阈值
        半开放（Half-Open）
           ↓ 探测成功
        打开（Open）
           ↓ 冷却时间到期
        半开放（Half-Open）
           ↓ 探测失败
        打开（Open）
```

| 状态 | 行为 | 说明 |
|------|------|------|
| **关闭（Closed）** | 正常请求通过，失败计数器记录 | 默认状态，监控失败率 |
| **打开（Open）** | 所有请求直接返回降级响应，不发往目标服务 | 快速失败，保护下游 |
| **半开放（Half-Open）** | 允许少量探测请求通过，测试服务是否恢复 | 试探性恢复 |

### 4.2 熔断器参数配置

| 参数 | 默认值 | 说明 | 调优建议 |
|------|--------|------|---------|
| **失败阈值（Failure Threshold）** | 50% | 触发熔断的最小失败率 | 高流量服务设为 30%，低流量设为 70% |
| **熔断窗口（Window）** | 60s | 统计失败率的时间窗口 | 太短易误触，太长恢复慢 |
| **最小请求数（Min Requests）** | 10 | 窗口内至少需要这么多请求才统计 | 太少统计无意义 |
| **熔断持续时间（Break Duration）** | 30s | 熔断打开后的冷却时间 | 根据服务恢复时间调整 |
| **半开探测请求数（Probe Count）** | 3 | 半开状态下放行的探测请求数 | 太多增加负载，太少误判 |

### 4.3 Circuit Breaker 在 Agent 中的应用

```python
# Agent 熔断器示例
class AgentCircuitBreaker:
    def __init__(self, name, failure_threshold=0.5, break_duration=30):
        self.name = name
        self.failure_threshold = failure_threshold
        self.break_duration = break_duration
        self.state = "CLOSED"  # CLOSED / OPEN / HALF_OPEN
        self.failure_count = 0
        self.total_count = 0
        self.last_failure_time = None

    def call(self, func, *args, **kwargs):
        if self.state == "OPEN":
            if time.time() - self.last_failure_time > self.break_duration:
                self.state = "HALF_OPEN"
            else:
                return self._fallback_response()

        try:
            result = func(*args, **kwargs)
            self._on_success()
            return result
        except Exception as e:
            self._on_failure()
            raise e

    def _on_success(self):
        self.failure_count = max(0, self.failure_count - 1)
        if self.state == "HALF_OPEN":
            self.state = "CLOSED"

    def _on_failure(self):
        self.failure_count += 1
        self.total_count += 1
        self.last_failure_time = time.time()
        failure_rate = self.failure_count / max(1, self.total_count)
        if failure_rate >= self.failure_threshold:
            self.state = "OPEN"

    def _fallback_response(self):
        return {"error": "circuit_breaker_open", "service": self.name}
```

---

## 5. Checkpoint / Resume 策略

### 5.1 Checkpoint 设计原则

| 原则 | 说明 |
|------|------|
| **幂等性** | 同一个 Checkpoint 恢复后重跑，必须产生相同结果 |
| **最小状态** | 只保存恢复所需的最小上下文，避免状态膨胀 |
| **版本化** | Checkpoint 必须带版本号，确保兼容性 |
| **可清理** | 任务完成后必须清理历史 Checkpoint，避免磁盘泄漏 |

### 5.2 Checkpoint 保存时机

```
任务执行流程中的 Checkpoint 触发点：

任务开始
  ↓
阶段1完成 → Checkpoint-1（记录：输入+阶段1输出+元数据）
  ↓
阶段2完成 → Checkpoint-2
  ↓
阶段3完成 → Checkpoint-3
  ↓
任务完成 → 删除所有 Checkpoint

失败恢复流程：
失败 → 加载最近 Checkpoint → 从 Checkpoint 之后的阶段继续执行
```

### 5.3 Checkpoint 数据结构

```python
# Checkpoint 数据结构
Checkpoint = {
    "version": "1.0",
    "task_id": "task-2026-05-24-001",
    "agent_id": "analysis-agent",
    "created_at": "2026-05-24T01:20:00Z",
    "stage": "stage-2",  # 当前完成的阶段
    "input": {...},      # 原始输入
    "state": {
        "stage-1": {"output": {...}, "status": "completed"},
        "stage-2": {"output": {...}, "status": "completed"},
    },
    "metadata": {
        "total_stages": 5,
        "retry_count": 0,
    }
}
```

### 5.4 常见 Checkpoint 失败场景及处理

| 场景 | 原因 | 处理方式 |
|------|------|---------|
| **Checkpoint 损坏** | 写入中断导致 JSON 不完整 | 读取时 try-except，损坏则回退到上一个版本 |
| **无有效 Checkpoint** | 任务未执行到第一个 Checkpoint 就失败 | 从头重试，记录起始状态 |
| **跨版本不兼容** | 任务逻辑更新导致旧 Checkpoint 无法使用 | Checkpoint 带 version，比较版本号，不兼容则从头重试 |
| **磁盘空间不足** | Checkpoint 写入失败 | 预留磁盘空间阈值（如 1GB），不足时告警并拒绝新任务 |

---

## 6. Fallback 链设计（多级降级策略）

### 6.1 Fallback 链优先级原则

```
Fallback 链设计顺序（从高优先级到低）：

Priority-1：同类替代方案
  → 同功能不同实现（如：OpenAI GPT-4 → Anthropic Claude → 本地 Llama）

Priority-2：降精度替代方案
  → 精度不变但更快的方案（如：实时数据 → 缓存数据 → 历史快照）

Priority-3：部分完成替代方案
  → 不求完整但保证核心结果（如：批量处理100条 → 完成前50条）

Priority-4：缓存结果替代方案
  → 之前相同/相似请求的结果（如：5分钟内的相同查询返回缓存）

Priority-5：兜底响应
  → 返回友好提示，不返回错误（如："当前服务繁忙，请稍后再试"）
```

### 6.2 Fallback 链执行规范

| 规范 | 说明 |
|------|------|
| **超时独立计算** | 每个 Fallback 方案有独立的超时计时器，不继承上一层超时 |
| **Fallback 不能抛异常** | Fallback 函数必须 try-catch，返回降级结果而非抛出异常 |
| **Fallback 结果标注来源** | 返回的降级数据必须标注来源（如 `[数据来源：缓存，可能存在延迟]`） |
| **降级链路可配置** | Fallback 链必须可通过配置文件或环境变量修改，无需改代码 |
| **降级触发次数监控** | 每个 Fallback 层触发次数必须记录，用于分析系统脆弱点 |

### 6.3 Fallback 链示例：多级 LLM 降级

```python
# 多级 LLM Fallback 示例
LLM_FALLBACK_CHAIN = [
    {
        "name": "gpt-4",
        "type": "primary",
        "timeout": 60,
        "fallback_on": ["rate_limit", "timeout", "api_error"]
    },
    {
        "name": "gpt-3.5-turbo",
        "type": "fallback-1",
        "timeout": 45,
        "fallback_on": ["rate_limit", "timeout", "api_error"]
    },
    {
        "name": "claude-haiku",
        "type": "fallback-2",
        "timeout": 30,
        "fallback_on": ["rate_limit", "timeout", "api_error"]
    },
    {
        "name": "local-llama",
        "type": "fallback-3",
        "timeout": 120,
        "fallback_on": ["any_error"]
    },
    {
        "name": "keyword-match",
        "type": "final-fallback",
        "description": "无 LLM 可用时使用关键词匹配兜底"
    }
]
```

---

## 7. 日志与错误追踪（可观测性基础）

### 7.1 错误日志规范

| 字段 | 必须 | 说明 | 示例 |
|------|------|------|------|
| **timestamp** | ✅ | ISO 8601 格式时间戳 | `2026-05-24T01:20:00Z` |
| **level** | ✅ | ERROR / WARN / INFO | `ERROR` |
| **error_code** | ✅ | 错误码（如 `ERR-SYS-TMO-001`） | `ERR-DEP-TMO-001` |
| **message** | ✅ | 人类可读描述 | `LLM API 调用超时 60s` |
| **agent_id** | ✅ | 当前 Agent 标识 | `analysis-agent-001` |
| **task_id** | ✅ | 关联的任务 ID | `task-2026-05-24-001` |
| **session_id** | ✅ | 会话 ID | `session-abc123` |
| **context** | △ | 错误上下文（请求参数等） | `{"query": "...", "model": "gpt-4"}` |
| **stack_trace** | △ | 异常堆栈（如有） | `Traceback...` |
| **recovered** | △ | 是否已通过重试/降级恢复 | `true` / `false` |
| **recovery_method** | △ | 恢复方式（如有） | `fallback-2` / `retry-3` |

### 7.2 错误追踪上下文传播

```
错误上下文传播链：

用户请求
  ↓
Session ID 分配
  ↓
Task ID 生成
  ↓
子 Agent  Spawn（携带 parent_task_id）
  ↓
工具调用（携带 trace_id）
  ↓
错误发生 → 收集所有上下文（session_id + task_id + trace_id + agent_id）
  ↓
日志写入 + 错误码分配 + 上报到监控系统
```

### 7.3 关键可观测性指标

| 指标 | 计算方式 | 告警阈值建议 |
|------|---------|------------|
| **错误率（Error Rate）** | `失败请求数 / 总请求数 × 100%` | > 5% 告警 |
| **平均错误恢复时间（MTTR）** | `∑(恢复时间) / 恢复次数` | > 2min 告警 |
| **降级触发率（Degradation Rate）** | `降级触发次数 / 总请求数 × 100%` | > 10% 告警 |
| **熔断打开次数（Circuit Open Count）** | 每小时熔断打开次数 | > 3次/小时 告警 |
| **未恢复错误率（Unrecovered Error Rate）** | `人工介入错误数 / 总错误数 × 100%` | > 1% 告警 |

### 7.4 错误日志存储建议

| 环境 | 存储方式 | 保留时间 | 说明 |
|------|---------|---------|------|
| **开发/测试** | 本地文件（JSON Lines） | 7天 | 方便调试 |
| **预发布** | SQLite / PostgreSQL | 30天 | 可查询分析 |
| **生产** | Elasticsearch / Loki + Grafana | 90天 | 支持聚合查询和告警 |

---

## 8. 错误恢复与其他专家的协作

### 8.1 Handoff Format

```markdown
## Error-Recovery → 其他专家 Handoff

### 触发条件
当错误恢复专家完成以下工作后，向相关专家移交：

1. 完成错误分类和根因分析后 → 移交给对应修复专家
2. 建立了降级链并稳定运行 → 通知工作流编排专家确认
3. Checkpoint 恢复验证通过 → 通知上下文管理专家更新状态

### Handoff 消息格式
```markdown
### [Error-Recovery] → [目标专家]

**任务ID：** `task-xxx`
**错误类型：** 可恢复 / 不可恢复
**根因摘要：** （3句话内）
**已采取措施：** 重试 / 降级 / 熔断 / Checkpoint恢复
**后续建议：** 需要人工修复 / 自动恢复已生效 / 待观察

**交付物：**
- 错误日志：`[链接]`
- 监控告警：`[链接]`

**截止时间：** YYYY-MM-DD HH:MM
```
```

### 8.2 前置条件（接收其他专家的任务时）

| 来源专家 | 接收任务的前置条件 |
|---------|-----------------|
| **工具调用专家** | 提供错误发生的完整堆栈、调用参数、预期行为 |
| **上下文管理专家** | 提供错误发生时的上下文快照（Token 使用量、消息历史） |
| **工作流编排专家** | 提供错误发生的任务阶段、状态机状态 |
| **LLM 专家** | 提供模型返回的完整错误响应、Prompt 模板、调用参数 |

### 8.3 后置交付物

| 任务类型 | 交付物 |
|---------|-------|
| **错误分析与分类** | 错误分类报告（类型、根因、影响范围） |
| **降级链建立** | 降级策略文档（触发条件、降级方案、恢复机制） |
| **Checkpoint 恢复** | 恢复验证报告（恢复点、时间损耗、数据完整性） |
| **熔断器配置** | 熔断器配置清单（阈值、持续时间、监控仪表盘） |
| **可观测性建设** | 错误追踪体系文档（日志规范、告警阈值、仪表盘） |

---

## 9. 注入指引（Trigger & Priority）

### 9.1 触发词映射

| 触发词 | 触发场景 | 优先注入章节 |
|-------|---------|------------|
| "错误恢复" | Agent 报错需要处理策略 | 第1节 + 第3节 |
| "Graceful Degradation" | 需要设计降级策略 | 第3节 |
| "超时" / "Timeout" | 配置超时或处理超时错误 | 第2节 |
| "Hang" / "假死" | 检测到进程不响应 | 第2节（2.1 / 2.3） |
| "Circuit Breaker" | 需要熔断保护 | 第4节 |
| "降级" / "Fallback" | 需要设计降级链 | 第3节 + 第6节 |
| "容错" | 需要整体容错方案设计 | 全文件（优先第1节） |
| "checkpoint" / "状态恢复" | 需要保存/恢复执行状态 | 第5节 |
| "错误追踪" / "可观测性" | 需要错误日志和监控 | 第7节 |
| "重试" / "Retry" | 需要重试策略设计 | 第1节（1.1）+ 第3节（3.1） |

### 9.2 优先级定义

| 优先级 | 场景 | 说明 |
|-------|------|------|
| **P0** | Agent 系统级故障（LLM 不可用 / 系统崩溃） | 需要立即处理，优先注入第3、4、6节 |
| **P1** | 任务级错误（任务超时 / 部分失败） | 小时内处理，优先注入第2、5节 |
| **P2** | 性能降级（非致命，但影响效率） | 计划内处理，全文件按需注入 |
| **P3** | 预防性优化（无错误，但需要加固） | 例行迭代，涉及第7节可观测性建设 |

### 9.3 快速定位索引

```
需要快速查找时的章节顺序：
1. 报错处理 → 第1节（错误分类）→ 第2节（超时）→ 第3节（降级）
2. 系统设计 → 第4节（熔断器）→ 第5节（Checkpoint）→ 第6节（降级链）
3. 故障排查 → 第7节（日志规范）→ 第8节（协作规范）
```

---

## 更新日志

| 日期 | 更新内容 | 来源 | 执行人 |
|------|---------|------|-------|
| 2026-05-24 | 初始版本：error-recovery-specialist 知识库（Graceful Degradation / Circuit Breaker / Checkpoint / Fallback 链 / 可观测性） | ClawTeam 专家知识工程 | subagent:create-error-recovery |