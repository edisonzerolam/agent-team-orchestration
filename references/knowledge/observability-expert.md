# observability-expert（可观测性专家）知识文件

## 1. 身份定义

### 角色ID
`observability-expert`

### 核心职责
为多Agent系统提供全方位可观测性解决方案，负责日志规范设计、追踪链路构建、指标体系搭建、告警规则定义及可视化面板设计。确保系统运行状态透明可见，故障可快速定位，性能可量化评估。

### 适用场景
- 新系统可观测性架构设计与落地
- 现有系统可观测性能力评估与升级
- 故障根因分析（Root Cause Analysis）
- 性能瓶颈诊断与优化
- 跨Agent调用链路追踪
- 告警规则调优与误报治理
- 可视化仪表盘设计与维护

### 不适用场景
- 业务逻辑设计与实现（应由 planner 或 domain-expert 承担）
- 基础设施运维（应由 DevOps 角色承担）
- 实时交易系统的高频监控（时延要求超出通用方案范围）
- 硬件层面的监控（CPU/内存/磁盘应由系统工具而非应用层 Agent 负责）

---

## 2. 专业知识

### 2.1 Agent可观测性三要素

#### Logs（日志）
日志是系统行为的最细粒度记录。在多Agent系统中，日志需要标准化以支持跨Agent关联分析：
- **结构化日志**：所有Agent统一使用JSON格式输出日志
- **关键字段**：`timestamp`、`level`、`agent_id`、`task_id`、`trace_id`、`message`、`metadata`
- **日志级别**：DEBUG（开发调试）、INFO（正常流程）、WARN（异常但可自愈）、ERROR（需要干预）、FATAL（系统不可用）

#### Traces（追踪）
追踪是请求在多Agent系统中的完整路径记录：
- **分布式追踪**：每个任务携带 `trace_id`，在Agent间传递，实现端到端可见
- **Span概念**：每个Agent的处理作为一个Span，父Span与子Span形成树状结构
- **trace_id传播**：通过消息上下文（message context）将 `trace_id` 注入到子任务/子Agent调用中

#### Metrics（指标）
指标是系统状态的聚合量化：
- **Counter（计数器）**：累计值，如任务总数、错误总数
- **Gauge（仪表）**：瞬时值，如当前活跃任务数、队列深度
- **Histogram（直方图）**：分布值，如任务执行时长分布、Token消耗分布

### 2.2 结构化日志规范

```json
{
  "timestamp": "2026-05-24T01:19:00.123Z",
  "level": "INFO",
  "agent_id": "planner-001",
  "task_id": "task-7a3f9c2e",
  "trace_id": "trace-42e8f1a0",
  "span_id": "span-9d2c3b7e",
  "parent_span_id": "span-5f8a1d3c",
  "message": "Task dispatched to domain-expert for analysis",
  "metadata": {
    "component": "task-dispatcher",
    "action": "dispatch",
    "target_agent": "domain-expert",
    "priority": "normal",
    "estimated_duration_ms": 5000
  }
}
```

**关键字段说明：**
| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `timestamp` | ISO8601字符串 | 是 | 精确到毫秒，UTC时区 |
| `level` | 字符串枚举 | 是 | DEBUG/INFO/WARN/ERROR/FATAL |
| `agent_id` | 字符串 | 是 | Agent唯一标识符 |
| `task_id` | 字符串 | 是 | 任务唯一标识符 |
| `trace_id` | 字符串 | 是 | 追踪链ID，用于关联同一请求的所有日志 |
| `span_id` | 字符串 | 是 | 当前Span的唯一标识符 |
| `parent_span_id` | 字符串 | 否 | 父Span ID，形成调用树 |
| `message` | 字符串 | 是 | 人类可读的事件描述 |
| `metadata` | 对象 | 否 | 扩展字段，包含组件特定信息 |

### 2.3 分布式追踪在多Agent系统中的应用

#### trace_id 生命周期
1. **生成**：主Agent在接收用户请求时生成全局唯一的 `trace_id`
2. **传播**：通过消息传递上下文（context propagation）将 `trace_id` 传递给子Agent
3. **记录**：每个Agent在处理过程中将 `trace_id` 记录到所有日志和指标中
4. **汇总**：追踪数据收集后，可视化工具（如Grafana+Jaeger）重建完整调用链

#### 跨Agent追踪实现模式

**模式一：消息传播（Message Propagation）**
```
主Agent → [trace_id注入到消息] → 子Agent
子Agent → [继承父span_id, 生成新span_id] → 孙子Agent
```

**模式二：任务上下文（Task Context）**
```
Task {
  task_id: "task-xxx",
  trace_id: "trace-xxx",
  parent_span_id: "span-xxx",
  payload: {...}
}
```

#### 常见追踪陷阱
- **trace断裂**：子Agent未正确接收/传递 `trace_id`，导致链路断裂
- **span丢失**：Agent内部异常未记录span，追踪不完整
- **时钟偏差**：分布式系统中时间戳不一致，应使用NTP同步
- **过度采样**：高并发系统中全量追踪开销大，应实施采样策略（如p=0.1的随机采样）

### 2.4 关键指标体系

#### 任务级指标
| 指标名称 | 类型 | 计算方式 | 告警阈值建议 |
|----------|------|----------|--------------|
| `task_completed_total` | Counter | 累计完成任务数 | 无 |
| `task_failed_total` | Counter | 累计失败任务数 | 失败率 > 5% 触发WARN |
| `task_duration_seconds` | Histogram | P50/P90/P99执行时长 | P99 > 30s 触发WARN |
| `task_in_progress` | Gauge | 当前执行中任务数 | 超过队列容量80%触发WARN |

#### Token消耗指标
| 指标名称 | 类型 | 说明 |
|----------|------|------|
| `tokens_used_total` | Counter | 累计消耗Token数 |
| `tokens_per_task` | Histogram | 单任务Token消耗分布 |
| `tokens_cost_estimate` | Counter | 预估成本（基于模型定价） |

#### Agent级指标
| 指标名称 | 类型 | 说明 |
|----------|------|------|
| `agent_errors_total` | Counter | Agent错误累计数 |
| `agent_health_score` | Gauge | Agent健康度评分（0-100） |
| `agent_response_time_ms` | Histogram | Agent平均响应时间 |

#### 系统级指标
| 指标名称 | 类型 | 告警阈值建议 |
|----------|------|--------------|
| `system_error_rate` | Gauge | 错误率 > 1% 触发WARN |
| `system_throughput` | Gauge | 吞吐量（Tasks/min）低于基线30%触发WARN |
| `queue_depth` | Gauge | 等待队列 > 100 触发WARN |

### 2.5 健康检查端点设计

#### 分层健康检查模型

**L1：基础存活检查（/health/live）**
- 检查进程是否存活
- 响应时间 < 100ms
- 用于负载均衡器检测

```json
{
  "status": "healthy",
  "timestamp": "2026-05-24T01:19:00Z",
  "checks": {
    "process": "alive"
  }
}
```

**L2：就绪检查（/health/ready）**
- 检查依赖服务是否可用（消息队列、数据库、其他Agent）
- 响应时间 < 500ms
- 用于控制是否接收新任务

```json
{
  "status": "ready",
  "timestamp": "2026-05-24T01:19:00Z",
  "checks": {
    "process": "alive",
    "message_queue": "connected",
    "database": "connected",
    "parent_agent": "available"
  }
}
```

**L3：深度检查（/health/detailed）**
- 检查资源使用率、性能基线
- 响应时间 < 2s
- 用于运维监控和容量规划

```json
{
  "status": "healthy",
  "timestamp": "2026-05-24T01:19:00Z",
  "checks": {
    "process": "alive",
    "message_queue": "connected",
    "database": "connected",
    "memory_usage_percent": 45.2,
    "cpu_usage_percent": 12.8,
    "disk_usage_percent": 23.1
  },
  "metrics": {
    "active_tasks": 3,
    "queue_depth": 12,
    "avg_response_time_ms": 234
  }
}
```

### 2.6 告警阈值设计

#### 阈值设计原则
1. **基于历史数据**：使用过去7-30天的数据建立基线
2. **分级别告警**：WARN（需要关注）→ ERROR（需要处理）→ CRITICAL（立即处理）
3. **避免告警风暴**：同类告警合并，抑制重复告警
4. **动态阈值**：使用统计方法（如IQR、StdDev）自动调整阈值

#### 常见告警规则示例

**规则1：错误率告警**
```yaml
alert: HighTaskErrorRate
expr: rate(task_failed_total[5m]) / rate(task_completed_total[5m]) > 0.05
for: 5m
labels:
  severity: warning
annotations:
  summary: "任务错误率超过5%"
  description: "过去5分钟内任务错误率为 {{ $value | humanizePercentage }}"
```

**规则2：响应时间告警**
```yaml
alert: HighTaskLatency
expr: histogram_quantile(0.99, task_duration_seconds) > 30
for: 10m
labels:
  severity: warning
annotations:
  summary: "任务P99响应时间超过30秒"
  description: "P99响应时间为 {{ $value }}s，已持续10分钟"
```

**规则3：队列积压告警**
```yaml
alert: TaskQueueBackup
expr: queue_depth > 100
for: 5m
labels:
  severity: error
annotations:
  summary: "任务队列积压严重"
  description: "当前队列深度为 {{ $value }}，超过阈值100"
```

**规则4：Token超限告警**
```yaml
alert: HighTokenConsumption
expr: rate(tokens_used_total[1h]) > 10000000
for: 30m
labels:
  severity: warning
annotations:
  summary: "Token消耗速率异常"
  description: "当前小时消耗速率预计达到 {{ $value | humanize }} tokens"
```

### 2.7 可视化面板设计原则

#### 面板设计黄金定律
1. **信息密度适中**：一屏不超过5个核心指标
2. **时间范围可调**：默认展示近1小时，支持拖动选择时间范围
3. **颜色编码一致**：绿色=正常、黄色=警告、红色=异常
4. **下钻路径清晰**：从全局到局部，从概览到细节

#### 推荐面板布局（以Grafana为例）

```
┌─────────────────────────────────────────────────────────┐
│ [全局状态概览]                                            │
│ ┌──────────────┐ ┌──────────────┐ ┌──────────────┐      │
│ │ 任务完成率   │ │ 当前活跃任务 │ │ 错误率趋势   │      │
│ │   98.5%     │ │      12      │ │   [折线图]   │      │
│ └──────────────┘ └──────────────┘ └──────────────┘      │
├─────────────────────────────────────────────────────────┤
│ [Agent健康矩阵]                                           │
│ ┌────────┬────────┬────────┬────────┬────────┐           │
│ │Planner │Domain-1│Domain-2│ Code-1 │Review-1│           │
│ │  ✅OK  │  ✅OK  │  ⚠️WARN│  ✅OK  │  ✅OK  │           │
│ └────────┴────────┴────────┴────────┴────────┘           │
├─────────────────────────────────────────────────────────┤
│ [追踪链路视图]                      [Token消耗趋势]       │
│ [Jaeger/Grafana Trace]           [柱状图趋势]            │
├─────────────────────────────────────────────────────────┤
│ [最新告警列表]                                            │
│ ⚠️ 14:23 HighTaskLatency P99=45s                         │
│ ⚠️ 14:19 HighTokenConsumption Rate=12M/h                 │
└─────────────────────────────────────────────────────────┘
```

#### 关键Dashboard清单
1. **系统总览Dashboard**：展示全局KPI，新人友好型入口
2. **Agent健康Dashboard**：每个Agent一张卡片，展示错误率、响应时间、活跃度
3. **追踪链路Dashboard**：集成Jaeger，支持trace ID查询
4. **告警历史Dashboard**：展示历史告警、告警趋势、告警抑制效果
5. **容量规划Dashboard**：展示Token消耗趋势、资源使用预测

---

## 3. 与其他角色的协作

### 3.1 Handoff Format（交接格式）

#### 交接给 planner
当可观测性数据表明系统存在架构层面问题时（如任务分配不均、Agent协作效率低），向planner发起交接：

```markdown
## [可观测性 → Planner] 系统架构优化建议

### 观察到的现象
- 跨Agent任务平均转发次数为 3.2 次，高于基线 1.5 次
- Agent-A 和 Agent-B 之间存在循环调用（cycle detected）

### 根因初步分析
- 任务分解粒度不够精细，导致子任务嵌套过深
- Agent角色边界模糊，职责有重叠

### 建议的优化方向
1. 重新定义Agent职责边界
2. 优化任务分解策略，减少跨Agent依赖
3. 引入任务路由中间层

### 支持数据
- 追踪数据分析报告（见附件 trace-analysis-20260524.json）
- 调用链路热力图
```

#### 交接给 code-expert
当发现代码层面的问题时（如异常处理不当、资源泄漏），向code-expert发起交接：

```markdown
## [可观测性 → Code-Expert] 代码质量问题

### 观察到的现象
- Agent-C 在处理IO密集任务时内存持续增长
- 错误日志中 "Connection pool exhausted" 出现频率增加

### 根因初步分析
- 疑似连接池未正确释放
- 内存泄漏点可能在 cache_cleanup 逻辑中

### 建议的修复方向
1. 检查连接池使用是否遵循 try-finally 或 context manager 模式
2. 审查 cache_cleanup 是否在所有代码路径都被调用
3. 添加内存监控指标

### 支持数据
- 错误日志样本（last 100 errors）
- 内存使用趋势图
- 疑似泄漏点的代码片段
```

### 3.2 前置条件
- 系统已配置结构化日志输出（JSON格式）
- 每个Agent在启动时分配唯一 `agent_id`
- 消息传递中间件支持 trace_id 注入（如果使用消息队列）
- 已部署指标收集系统（如Prometheus、InfluxDB）
- 有权限访问日志存储和指标数据库

### 3.3 后置交付物
- **可观测性架构设计文档**：包含日志规范、追踪方案、指标定义
- **Dashboard链接列表**：各Dashboard的访问地址和说明
- **告警规则配置**：以YAML/JSON格式提供的告警规则集
- **健康检查接口文档**：各健康端点的说明和使用方式
- **异常检测报告**：定期（如每周）输出系统异常模式分析

---

## 4. 注入指引

### 4.1 触发词（Trigger Words）
以下词汇或场景出现时，应触发 observability-expert 知识注入：
- "日志"、"trace"、"追踪"、"链路"
- "指标"、"监控"、"Dashboard"、"面板"
- "告警"、"告警阈值"、"报警"
- "健康检查"、"health check"、"心跳"
- "故障定位"、"根因分析"、"RCA"
- "性能问题"、"响应慢"、"超时"
- "可观测性"、"observability"

### 4.2 注入章节优先级

**P0（最高优先级，立即注入）：**
- 三要素概述（Logs/Traces/Metrics）
- 结构化日志规范
- 分布式追踪实现

**P1（高优先级，常规注入）：**
- 关键指标体系
- 健康检查端点设计
- 告警阈值设计原则

**P2（中优先级，按需注入）：**
- 可视化面板设计原则
- 与其他角色的协作模式
- handoff格式模板

### 4.3 注入时机示例

| 用户场景 | 建议注入章节 | 优先级 |
|----------|-------------|--------|
| "帮我设计可观测性方案" | 全部（重点2.1-2.5） | P0 |
| "某个Agent报错了怎么查" | 结构化日志规范 + 追踪实现 | P0 |
| "想加个监控面板" | 可视化面板设计原则 | P1 |
| "告警总是误报怎么办" | 告警阈值设计原则 | P1 |
| "需要给新Agent加上日志" | 日志规范 + 健康检查 | P0 |
| "系统变慢了怎么排查" | 指标体系 + 分布式追踪 | P0 |

---

## 附录：常用工具栈推荐

### 日志收集与分析
- **ELK Stack**（Elasticsearch + Logstash + Kibana）：通用日志分析
- **Loki**：轻量级日志存储，Grafana原生集成
- **Splunk**：企业级日志分析（商业化）

### 追踪
- **Jaeger**：CNCF毕业项目，OpenTelemetry原生支持
- **Zipkin**：轻量级追踪工具
- **OpenTelemetry**：跨语言追踪标准

### 指标
- **Prometheus + Grafana**：业界标准开源组合
- **InfluxDB + Grafana**：时序数据存储
- **Datadog**：商业化全栈监控

### 日志规范辅助工具
- **Pino**：Node.js结构化日志库
- **python-json-logger**：Python结构化日志
- **zap**：Go结构化日志库

---

*本知识文件由 observability-expert 生成，最后更新于 2026-05-24*