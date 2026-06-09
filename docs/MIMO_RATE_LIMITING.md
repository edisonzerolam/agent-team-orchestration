# MIMO 大模型限速和限流应对方案

## 概述

本文档为 agent-team-orchestration 技能和其他多线程并行技能提供 MIMO 大模型的限速和限流应对方案。

### 速率限制参数

| 参数 | 值 | 说明 |
|------|-----|------|
| **RPM** | 100 | 每分钟最大请求数 |
| **TPM** | 10,000,000 | 每分钟最大 token 数 |

## 核心组件

### 1. 令牌桶限速器 (`mimo_rate_limiter.py`)

实现令牌桶算法，同时控制 RPM 和 TPM。

**核心功能：**
- RPM 令牌桶：每秒补充 100/60 ≈ 1.67 个令牌
- TPM 令牌桶：每秒补充 10M/60 ≈ 166,667 个令牌
- 优先级队列：支持 5 级优先级（CRITICAL > HIGH > NORMAL > LOW > BACKGROUND）
- 退避策略：指数退避，避免重试风暴

**使用方式：**

```python
from mimo_rate_limiter import MimoRateLimiter, Priority

# 创建限速器
limiter = MimoRateLimiter()

# 同步获取许可
success = limiter.acquire_sync(
    agent_id="agent-1",
    estimated_tokens=5000,
    priority=Priority.NORMAL
)

# 异步获取许可（带等待）
success = await limiter.acquire(
    agent_id="agent-1",
    estimated_tokens=5000,
    priority=Priority.HIGH
)

# 便捷函数
from mimo_rate_limiter import acquire_rate_limit, estimate_tokens

tokens = estimate_tokens("分析 AI 市场趋势")
success = acquire_rate_limit("agent-1", tokens, Priority.NORMAL)
```

### 2. 编排器集成 (`mimo_rate_integration.py`)

将限速器集成到 agent-team-orchestration 的编排流程中。

**核心功能：**
- 预算分配：根据 agent 数量自动分配 RPM/TPM 配额
- 任务优化：根据预算调整 token 预估
- 使用监控：跟踪每个 agent 的使用情况

**使用方式：**

```python
from mimo_rate_integration import MimoAwareOrchestrator

# 创建编排器
orchestrator = MimoAwareOrchestrator()

# 规划团队（自动分配预算）
plan = orchestrator.plan_team_with_budget(
    topic="分析 AI 市场趋势",
    description="深度分析当前 AI 市场的发展趋势和未来方向",
    max_agents=4
)

# 派发 agent（自动限速）
success = orchestrator.spawn_agent_with_rate_limit(
    agent_id="agent-1",
    task="分析宏观趋势",
    estimated_tokens=3000
)

# 获取状态报告
report = orchestrator.generate_rate_limit_report()
```

## Agent 配额分配策略

### 默认分配规则

当有 N 个 agent 时，配额分配如下：

| Agent 角色 | RPM 配额 | TPM 配额 | 优先级 |
|-----------|----------|----------|--------|
| Orchestrator | RPM * 1.2 / N | TPM * 1.2 / N | CRITICAL |
| Builder | RPM / N | TPM / N | NORMAL |
| Reviewer | RPM / N | TPM / N | HIGH |
| Analyst | RPM / N | TPM / N | NORMAL |
| Ops | RPM / N | TPM / N | LOW |

### 示例：4 个 Agent

```
总配额: RPM=100, TPM=10,000,000

Agent-1 (Orchestrator): RPM=30, TPM=3,000,000 (优先级: CRITICAL)
Agent-2 (Builder):      RPM=25, TPM=2,500,000 (优先级: NORMAL)
Agent-3 (Reviewer):     RPM=25, TPM=2,500,000 (优先级: HIGH)
Agent-4 (Analyst):      RPM=20, TPM=2,000,000 (优先级: NORMAL)
```

## 并行技能适配

### 1. agent-team-orchestration

**场景：** 多 agent 协作任务

**适配方案：**
```python
# 在 team-brain.py 中使用
from mimo_rate_integration import MimoAwareOrchestrator

orchestrator = MimoAwareOrchestrator()

# 规划团队
plan = orchestrator.plan_team_with_budget(topic, description, max_agents)

# 派发每个 agent
for agent in plan['agents']:
    success = orchestrator.spawn_agent_with_rate_limit(
        agent_id=agent['agent_id'],
        task=agent['task'],
        estimated_tokens=estimate_tokens(agent['task'])
    )
    
    if not success:
        # 等待后重试
        time.sleep(1)
        success = orchestrator.spawn_agent_with_rate_limit(...)
```

### 2. parallel-executor

**场景：** 并行执行多个独立任务

**适配方案：**
```python
from mimo_rate_limiter import acquire_rate_limit, estimate_tokens
from concurrent.futures import ThreadPoolExecutor

def execute_with_rate_limit(task):
    """带限速的任务执行"""
    tokens = estimate_tokens(task['prompt'])
    
    # 获取限速许可
    if acquire_rate_limit(task['agent_id'], tokens):
        # 执行任务
        return call_mimo_api(task['prompt'])
    else:
        # 加入队列等待
        return queue_and_wait(task)

# 并行执行
with ThreadPoolExecutor(max_workers=5) as executor:
    futures = [executor.submit(execute_with_rate_limit, task) for task in tasks]
```

### 3. colony (multi-agent-orchestration)

**场景：** Colony 多 agent 工作流

**适配方案：**
```javascript
// 在 colony.mjs 中使用
import { MimoRateLimiter } from './mimo_rate_limiter.mjs';

const limiter = new MimoRateLimiter();

// 派发任务时限速
async function dispatchWithRateLimit(agentId, task, estimatedTokens) {
    const success = await limiter.acquire(agentId, estimatedTokens);
    
    if (success) {
        return dispatchTask(agentId, task);
    } else {
        // 等待后重试
        await limiter.waitForSlot();
        return dispatchTask(agentId, task);
    }
}
```

### 4. content-factory

**场景：** 多 agent 内容生产

**适配方案：**
```python
from mimo_rate_integration import MimoAwareOrchestrator

# 为内容生产分配预算
orchestrator = MimoAwareOrchestrator(
    config=RateLimitConfig(
        rpm_limit=100,
        tpm_limit=10_000_000,
        min_rpm_per_agent=10,  # 每个 agent 至少 10 RPM
        min_tpm_per_agent=500_000  # 每个 agent 至少 500K TPM
    )
)

# 内容生产任务
tasks = [
    {"agent_id": "writer", "task": "撰写文章", "tokens": 5000},
    {"agent_id": "editor", "task": "编辑校对", "tokens": 3000},
    {"agent_id": "seo", "task": "SEO 优化", "tokens": 2000},
    {"agent_id": "social", "task": "社交媒体推广", "tokens": 1500}
]

# 优化任务以适应限速
optimized_tasks = orchestrator.optimize_for_rate_limit(tasks)

# 执行
for task in optimized_tasks:
    orchestrator.spawn_agent_with_rate_limit(**task)
```

## 限流应对策略

### 1. 429 错误处理

当收到 429 Too Many Requests 错误时：

```python
from mimo_rate_limiter import MimoRateLimiter

limiter = MimoRateLimiter()

def handle_429_error(agent_id: str, error_type: str):
    """处理 429 错误"""
    # 应用退避策略
    limiter.handle_rate_limit_error(agent_id, error_type)
    
    # 获取退避时间
    backoff_time = limiter.agent_backoff.get(agent_id, 1.0)
    
    # 等待后重试
    time.sleep(backoff_time)
    
    # 重试
    return limiter.acquire_sync(agent_id, estimated_tokens)
```

### 2. Token 预估优化

准确的 token 预估可以避免意外的限速：

```python
from mimo_rate_limiter import estimate_tokens, estimate_prompt_tokens

# 简单预估
tokens = estimate_tokens("分析 AI 市场趋势")

# 完整预估
tokens = estimate_prompt_tokens(
    system_prompt="你是一个 AI 分析师",
    user_message="分析 AI 市场趋势",
    context="当前时间：2026年"
)
```

### 3. 动态调整 Agent 数量

根据当前负载动态调整 agent 数量：

```python
def dynamic_agent_count(limiter: MimoRateLimiter, requested_count: int) -> int:
    """根据当前负载动态调整 agent 数量"""
    metrics = limiter.get_metrics()
    
    # 如果 RPM 利用率 > 80%，减少 agent 数量
    if metrics['rpm_utilization'] > 0.8:
        return max(2, requested_count - 2)
    
    # 如果 TPM 利用率 > 80%，减少 agent 数量
    if metrics['tpm_utilization'] > 0.8:
        return max(2, requested_count - 1)
    
    return requested_count
```

### 4. 优先级调度

确保关键任务优先执行：

```python
from mimo_rate_limiter import Priority

# 关键任务使用高优先级
orchestrator.spawn_agent_with_rate_limit(
    agent_id="orchestrator",
    task="紧急决策",
    estimated_tokens=2000,
    priority=Priority.CRITICAL  # 最高优先级
)

# 普通任务使用普通优先级
orchestrator.spawn_agent_with_rate_limit(
    agent_id="builder",
    task="执行任务",
    estimated_tokens=3000,
    priority=Priority.NORMAL
)
```

## 监控和告警

### 1. 实时监控

```python
from mimo_rate_limiter import MimoRateLimiter

limiter = MimoRateLimiter()

# 获取实时指标
metrics = limiter.get_metrics()

print(f"当前 RPM: {metrics['current_rpm']:.1f}/{limiter.config.rpm_limit}")
print(f"当前 TPM: {metrics['current_tpm']:.0f}/{limiter.config.tpm_limit}")
print(f"队列大小: {metrics['queue_size']}")

# 检查告警
if metrics['alerts']:
    for alert in metrics['alerts']:
        print(f"⚠️ {alert}")
```

### 2. 使用报告

```python
from mimo_rate_integration import MimoAwareOrchestrator

orchestrator = MimoAwareOrchestrator()

# 生成使用报告
report = orchestrator.generate_rate_limit_report()
print(report)

# 获取详细使用情况
usage = orchestrator.get_agent_usage_report()
for agent_id, stats in usage['agents'].items():
    print(f"{agent_id}: {stats['tokens']} tokens, {stats['requests']} requests")
```

### 3. 状态持久化

```python
from mimo_rate_limiter import MimoRateLimiter

limiter = MimoRateLimiter()

# 保存状态
limiter.save_state()

# 加载状态
limiter.load_state()
```

## 最佳实践

### 1. Token 预估

- **始终预估 token 数**：不要发送未知 token 数的请求
- **使用 `estimate_tokens()`**：内置的预估函数考虑了中英文差异
- **预留 buffer**：预估时增加 10-20% 的 buffer

### 2. Agent 派发

- **顺序派发**：避免同时派发多个 agent
- **检查返回值**：`acquire_rate_limit()` 返回 False 时等待重试
- **使用优先级**：关键任务使用 `Priority.CRITICAL` 或 `Priority.HIGH`

### 3. 错误处理

- **捕获 429 错误**：调用 `handle_rate_limit_error()` 应用退避
- **实现重试逻辑**：使用指数退避重试
- **记录失败**：记录失败的请求以便分析

### 4. 监控

- **定期检查指标**：每 30 秒检查一次 RPM/TPM
- **设置告警阈值**：80% 使用率时告警
- **保存状态**：定期保存状态以便恢复

## 配置调优

### 默认配置

```python
from mimo_rate_limiter import RateLimitConfig

config = RateLimitConfig(
    rpm_limit=100,              # RPM 限制
    tpm_limit=10_000_000,       # TPM 限制
    burst_rpm=20,               # 突发 RPM
    burst_tpm=1_000_000,        # 突发 TPM
    min_rpm_per_agent=5,        # 每个 agent 最小 RPM
    min_tpm_per_agent=100_000,  # 每个 agent 最小 TPM
    max_queue_size=100,         # 最大队列长度
    queue_timeout=300,          # 队列超时（秒）
    base_backoff=1.0,           # 基础退避时间（秒）
    max_backoff=60.0,           # 最大退避时间（秒）
    backoff_multiplier=2.0,     # 退避倍数
    metrics_window=60,          # 滑动窗口（秒）
    alert_threshold_rpm=0.8,    # RPM 告警阈值
    alert_threshold_tpm=0.8     # TPM 告警阈值
)
```

### 调优建议

1. **高并发场景**（>5 个 agent）：
   - 增加 `max_queue_size` 到 200
   - 降低 `min_rpm_per_agent` 到 3
   - 增加 `queue_timeout` 到 600

2. **低延迟场景**：
   - 降低 `base_backoff` 到 0.5
   - 降低 `max_backoff` 到 30
   - 增加 `queue_timeout` 到 600

3. **稳定场景**（<3 个 agent）：
   - 增加 `min_rpm_per_agent` 到 10
   - 增加 `min_tpm_per_agent` 到 500_000
   - 降低 `alert_threshold_rpm` 到 0.7

## 故障排除

### 问题 1：频繁 429 错误

**原因：** Agent 数量过多或 token 预估不准确

**解决方案：**
1. 减少 agent 数量
2. 使用 `estimate_tokens()` 准确预估
3. 增加 `base_backoff` 到 2.0

### 问题 2：队列超时

**原因：** 队列积压过多或限速太严格

**解决方案：**
1. 增加 `queue_timeout` 到 600
2. 增加 `rpm_limit`（如果 API 允许）
3. 减少 agent 数量

### 问题 3：Agent 饥饿

**原因：** 低优先级 agent 无法获得配额

**解决方案：**
1. 使用优先级队列
2. 为低优先级 agent 分配最小配额
3. 实现公平调度算法

## 文件结构

```
agent-team-orchestration/
├── scripts/
│   ├── mimo_rate_limiter.py          # 核心限速器
│   ├── mimo_rate_integration.py      # 编排器集成
│   └── team-brain.py                 # 团队管理脚本（已集成）
├── docs/
│   └── MIMO_RATE_LIMITING.md         # 本文档
└── README.md
```

## 更新日志

### v1.0.0 (2026-06-02)
- 初始版本
- 实现令牌桶限速器
- 支持 RPM 和 TPM 双重限制
- 实现优先级队列
- 集成到 agent-team-orchestration
- 添加监控和告警功能
