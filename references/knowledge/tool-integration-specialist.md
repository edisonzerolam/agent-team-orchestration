# 工具集成专家知识库

> 工具集成专家（tool-integration-specialist）的本地知识手册。用于 Agent 工具调用架构设计、API 集成模式与错误处理策略。

---

## 1. LangChain Tool Calling 最佳实践

### 1.1 Tool 定义结构

LangChain 中工具定义应遵循标准 schema，包含清晰描述与精确参数：

```python
from langchain_core.tools import tool

@tool
def get_weather(location: str, unit: str = "celsius") -> str:
    """获取指定位置的当前天气信息。

    Args:
        location: 城市名称，必须包含国家/地区，例如 "Beijing, CN" 或 "Tokyo, JP"
        unit: 温度单位，"celsius"（默认）或 "fahrenheit"
    
    Returns:
        格式化的天气描述，包含温度、天气状况、湿度等
    """
    # 实现逻辑
    pass
```

**核心原则**：
- `description` 是 LLM 理解何时调用工具的唯一依据，必须完整描述功能与用途
- 参数描述应说明期望格式与约束条件（如单位、格式）
- 使用 `Annotated` 添加参数验证与类型约束

### 1.2 Tool Choice 策略

LangChain 支持多种 tool choice 模式：

| 模式 | 适用场景 | 行为描述 |
|------|---------|---------|
| `tool_choice="auto"` | 默认推荐 | LLM 自行决定是否调用工具（无工具时直接回复） |
| `tool_choice="required"` | 必须使用工具 | 强制 LLM 始终调用工具（适用于严格工具驱动场景） |
| `tool_choice=ToolNode(...)` | 精确控制 | 指定特定工具被调用 |

### 1.3 Tool Binding 策略

```python
from langchain_core.language_models import BaseChatModel
from langchain_core.tools import tool
from langgraph.prebuilt import ToolNode

# 多工具绑定
tools = [get_weather, get_stock_price, search_news]
model_with_tools = model.bind_tools(tools)

# 强制工具调用（forced tool calling）
forced_model = model.bind_tools(tools, tool_choice="required")
```

### 1.4 避免 Tool Schema 膨胀

**问题**：工具过多导致 LLM 调用成本上升且准确率下降。

**解决策略**：

| 策略 | 说明 | 适用场景 |
|------|------|---------|
| **工具分组（Tool Grouping）** | 将相关工具合并为单一工具，内部路由 | 工具家族（如多个数据库查询） |
| **分层抽象（Hierarchical）** | 提供 selector 工具选择子工具 | 工具集庞大（>20） |
| **上下文过滤** | 根据对话状态动态注册工具 | 多轮对话中工具集变化 |

---

## 2. OpenAI Function Calling / Tool Use 模式

### 2.1 function calling 请求结构

```json
{
  "model": "gpt-4o",
  "messages": [
    {"role": "user", "content": "北京今天的天气怎么样？"}
  ],
  "tools": [
    {
      "type": "function",
      "function": {
        "name": "get_weather",
        "description": "获取指定位置的当前天气信息。",
        "parameters": {
          "type": "object",
          "properties": {
            "location": {
              "type": "string",
              "description": "城市名称，包含国家/地区，如 'Beijing, CN'"
            },
            "unit": {
              "type": "string",
              "enum": ["celsius", "fahrenheit"],
              "description": "温度单位"
            }
          },
          "required": ["location"]
        }
      }
    }
  ],
  "tool_choice": "auto"
}
```

### 2.2 Tool Choice 模式

OpenAI 提供三种 tool_choice 策略：

| 模式 | 值 | 行为 |
|------|-----|------|
| `auto` | `"auto"` | LLM 自行判断（推荐默认） |
| `none` | `"none"` | 强制不调用工具，直接回复 |
| `指定工具` | `{ "type": "function", "function": { "name": "get_weather" }}` | 强制调用特定工具 |

### 2.3 工具调用响应处理

```python
import json

def process_tool_calls(response):
    """解析 OpenAI tool_calls 响应"""
    tool_calls = response.usage.completion
    # 结构化响应解析
    for tool_call in response.tool_calls:
        tool_name = tool_call.function.name
        arguments = json.loads(tool_call.function.arguments)
        # 处理工具调用
```

**注意**：必须将 `function.arguments`（JSON 字符串）显式解析为 Python 对象。

### 2.4 Parallel Tool Calls

OpenAI 支持并行工具调用（同一轮回复中触发多个工具）：

```json
{
  "tool_calls": [
    {
      "id": "call_1",
      "type": "function",
      "function": {
        "name": "get_weather",
        "arguments": "{\"location\": \"Beijing\"}"
      }
    },
    {
      "id": "call_2",
      "type": "function",
      "function": {
        "name": "get_stock_price",
        "arguments": "{\"symbol\": \"AAPL\"}"
      }
    }
  ]
}
```

**何时使用并行调用**：
- 工具间无数据依赖
- 需要聚合多个独立数据源
- 降低延迟（总耗时 = max(工具耗时)，而非 sum）

---

## 3. Tool Description 设计原则

### 3.1 描述 vs 精确的权衡

| 场景 | 策略 | 示例 |
|------|------|------|
| **通用工具（模糊描述）** | 允许 LLM 自主判断 | `search_web(query)` → "搜索互联网获取信息" |
| **精确工具（精确描述）** | 明确边界 | `convert_currency(amount, from, to)` → "将金额从一种货币换算为另一种，支持 USD/EUR/CNY..." |
| **安全关键工具** | 精确描述 + 约束 | `delete_file(path)` → "删除指定路径文件，仅支持用户目录下的文件删除" |

### 3.2 优秀 Tool Description 的要素

```
[工具名称]：一句话描述功能

[使用场景]：何时应该调用此工具
[输入参数]：
  - param1: 类型 + 描述 + 约束
  - param2: ...
[返回值]：返回数据的格式与含义
[注意事项]：边界条件、错误场景、限制
```

### 3.3 避免的常见错误

| 错误类型 | 问题描述 | 修正方案 |
|---------|---------|---------|
| **过度简洁** | `"搜索信息"` — LLM 无法判断何时调用 | 补充场景描述与参数约束 |
| **过度复杂** | 500字的描述 → LLM 无法有效解析 | 保持描述在 50-200 字符 |
| **缺少示例** | 参数格式不明确 | 提供参数格式示例 |
| **隐藏约束** | 某些值不支持但未说明 | 明确列出枚举值与范围 |
| **歧义描述** | `"获取数据"` 可对应多个工具 | 区分具体数据源与用途 |

### 3.4 参数 Schema 设计

```python
# 推荐：明确参数边界
parameters = {
    "type": "object",
    "properties": {
        "symbol": {
            "type": "string",
            "description": "股票代码，如 'AAPL'、'600519.SS'",
            "pattern": "^[A-Z]{1,5}(\\.[A-Z]{2})?$"
        },
        "period": {
            "type": "string",
            "enum": ["1d", "1w", "1m", "3m", "1y"],
            "description": "时间周期"
        }
    },
    "required": ["symbol"]
}

# 避免：参数无约束
parameters = {
    "type": "object",
    "properties": {
        "symbol": {"type": "string"},
        "period": {"type": "string"}
    }
}
```

---

## 4. Tool Error Handling 与重试策略

### 4.1 错误分类与处理

| 错误类型 | 示例 | 处理策略 |
|---------|------|---------|
| **瞬时错误（Transient）** | 网络超时、API 限流 | 指数退避重试 |
| **持久错误（Permanent）** | 参数错误、权限不足 | 立即返回错误，不重试 |
| **服务器错误（Server）** | 500 Internal Error | 重试 2-3 次后返回 |
| **超时错误（Timeout）** | 响应超过 30s | 重试或降级 |

### 4.2 重试策略实现

```python
import time
from functools import wraps

def retry_with_backoff(max_retries=3, base_delay=1.0, max_delay=60.0):
    """指数退避重试装饰器"""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except TransientError as e:
                    if attempt == max_retries - 1:
                        raise
                    delay = min(base_delay * (2 ** attempt), max_delay)
                    time.sleep(delay)
        return wrapper
    return decorator
```

### 4.3 错误响应格式

工具应返回结构化错误而非原始异常：

```python
{
    "success": False,
    "error": {
        "code": "RATE_LIMIT_EXCEEDED",
        "message": "API 请求频率超限，请稍后重试",
        "retry_after": 5,  # 秒
        "details": {}  # 可选调试信息
    }
}
```

### 4.4 Tool Error 与 LLM 对齐

当工具返回错误时，LLM 应理解并生成用户友好的错误消息：

| 工具错误 | LLM 应生成的消息 |
|---------|-----------------|
| `INVALID_PARAMETER` | "参数格式有误，请检查输入" |
| `RATE_LIMIT_EXCEEDED` | "请求过于频繁，请稍后重试" |
| `PERMISSION_DENIED` | "没有权限执行此操作" |
| `TOOL_UNAVAILABLE` | "当前服务不可用，请稍后重试" |

---

## 5. Parallel vs Sequential Tool Calls

### 5.1 决策矩阵

| 条件 | 推荐策略 | 原因 |
|------|---------|------|
| 工具间无数据依赖 | Parallel | 降低延迟 |
| 工具B 需要工具A 的结果 | Sequential | 依赖关系 |
| 工具调用超过 5 个 | 分批 Parallel | 控制 token 消耗 |
| 工具执行时间 > 5s | Parallel | 避免超时 |
| 工具结果需聚合后再次调用 | Sequential + Loop | 中间结果参与下一轮 |

### 5.2 Parallel Tool Calls 模式

```python
# 同时获取多个独立数据源
async def fetch_market_data(symbols: list[str]):
    tasks = [get_stock_price(symbol) for symbol in symbols]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    return results
```

### 5.3 Sequential Tool Calls 模式

```python
# 第一步：获取用户持仓
portfolio = await get_portfolio(user_id)

# 第二步：获取持仓股票实时价格（依赖持仓数据）
stock_prices = await asyncio.gather(*[
    get_stock_price(symbol) for symbol in portfolio["symbols"]
])
```

### 5.4 并行调用限制

| 平台 | 并行限制 | 说明 |
|------|---------|------|
| OpenAI | 无硬性限制 | 受 token 窗口与 rate limit 约束 |
| Anthropic | 建议 ≤5 | 超过可能影响准确性 |
| Azure OpenAI | 取决于部署配置 | 需配置 MAX_CONCURRENT_REQUESTS |

---

## 6. Tool Output 格式设计

### 6.1 JSON vs 自由文本

| 格式 | 适用场景 | 优势 | 劣势 |
|------|---------|------|------|
| **JSON** | 结构化数据、API 响应 | 易于解析、LLM 可预测格式 | Schema 设计成本高 |
| **自由文本** | 非结构化内容、摘要 | 灵活、适合人类阅读 | 解析困难、LLM 容易遗漏关键信息 |
| **混合** | 复杂场景 | 兼顾结构与灵活 | 复杂度高 |

### 6.2 JSON Output 规范

```json
{
  "success": true,
  "data": {
    "key": "value"
  },
  "metadata": {
    "timestamp": "2026-05-24T01:16:00Z",
    "tool_version": "1.0.0",
    "request_id": "xxx"
  }
}
```

**核心字段**：
- `success`：布尔值，标识操作是否成功
- `data`：实际返回数据（结构化）
- `metadata`：元数据（时间戳、版本、请求ID）
- `error`：错误信息（仅在 success=false 时存在）

### 6.3 截断与大小限制

| 场景 | 处理策略 |
|------|---------|
| 输出超长（>10KB） | 返回前 N 条 + `"truncated": true` |
| 输出超长（>100KB） | 返回摘要 + `"summary": true` |
| LLM token 限制 | 工具层截断并提示 `"output_truncated"` |

```python
MAX_OUTPUT_LENGTH = 8000  # 字符

def truncate_output(result: str, max_length=MAX_OUTPUT_LENGTH):
    if len(result) > max_length:
        return {
            "success": True,
            "truncated": True,
            "data": result[:max_length],
            "message": f"输出已截断，完整长度 {len(result)} 字符"
        }
    return {"success": True, "data": result}
```

### 6.4 Tool Output 与 Tool Call Response 对齐

```python
# 工具实现
def get_stock_price(symbol: str) -> dict:
    try:
        price = fetch_price(symbol)
        return {
            "success": True,
            "data": {
                "symbol": symbol,
                "price": price,
                "currency": "USD",
                "timestamp": datetime.now().isoformat()
            }
        }
    except Exception as e:
        return {
            "success": False,
            "error": {
                "code": "FETCH_FAILED",
                "message": str(e)
            }
        }
```

---

## 7. 多工具协同与工具链（Tool Chain）

### 7.1 工具链设计模式

```python
# 工具链：搜索 → 提取 → 格式化
async def research_topic(topic: str):
    # Step 1: 搜索
    search_results = await search_web(query=topic, max_results=10)
    
    # Step 2: 提取（并行）
    articles = await asyncio.gather(*[
        extract_content(url=url) for url in search_results["urls"]
    ])
    
    # Step 3: 格式化
    summary = await summarize(text="\n".join(articles))
    return summary
```

### 7.2 工具链错误传播

工具链中任何一步失败应导致整体失败，同时保留已成功步骤的信息：

```python
{
    "success": False,
    "error": {
        "code": "CHAIN_FAILED",
        "failed_at": "extract_content",
        "reason": "URL unreachable"
    },
    "partial_results": {
        "search": {"completed": True, "data": {...}}
    }
}
```

### 7.3 工具选择器（Tool Selector）

当工具集过大（>20）时，使用选择器动态路由：

```python
@tool
def route_request(query: str, context: str) -> str:
    """根据查询内容选择合适的处理工具。
    
    Args:
        query: 用户查询
        context: 当前对话上下文（可选）
    
    Returns:
        工具名称与参数
    """
    if "天气" in query:
        return {"tool": "get_weather", "params": {...}}
    elif "股票" in query:
        return {"tool": "get_stock_price", "params": {...}}
    # ...
```

---

## 8. 工具集成的安全与权限控制

### 8.1 敏感操作确认

```python
def delete_file(path: str, require_confirmation: bool = True) -> dict:
    """删除文件（需用户确认）。
    
    安全约束：
    - 仅允许删除用户目录下的文件
    - 不允许删除系统文件、配置文件
    - 高危操作需二次确认
    """
    # 验证路径安全性
    if not path.startswith(ALLOWED_DIR):
        return {
            "success": False,
            "error": {"code": "PATH_FORBIDDEN", "message": "路径不允许访问"}
        }
    
    # 危险操作二次确认
    if require_confirmation and is_dangerous_operation(path):
        return {
            "success": False,
            "error": {
                "code": "CONFIRMATION_REQUIRED",
                "message": "此操作需要用户确认",
                "require_confirm": True
            }
        }
```

### 8.2 工具调用审计

```python
import logging

def audit_tool_call(tool_name: str, params: dict, user_id: str):
    """记录工具调用审计日志"""
    logging.info({
        "event": "tool_call",
        "tool": tool_name,
        "params": sanitize_params(params),  # 脱敏敏感信息
        "user_id": user_id,
        "timestamp": datetime.now().isoformat()
    })
```

---

## 9. 工具集成的测试策略

### 9.1 工具调用覆盖率测试

| 测试场景 | 测试目标 | 覆盖率指标 |
|---------|---------|-----------|
| 正常调用 | 工具功能正确性 | 100% |
| 参数边界 | 参数校验 | 参数边界值 100% |
| 错误处理 | 错误响应格式 | 错误类型全覆盖 |
| 并行调用 | 资源竞争、竞态条件 | 并发度覆盖 |

### 9.2 LLM Tool Use 行为测试

```python
def test_llm_tool_selection():
    """测试 LLM 是否能正确选择工具"""
    test_cases = [
        {"input": "北京天气怎么样？", "expected_tool": "get_weather"},
        {"input": "苹果股价多少？", "expected_tool": "get_stock_price"},
        {"input": "你好", "expected_tool": None}  # 无需工具
    ]
    for case in test_cases:
        response = llm.invoke(case["input"])
        actual_tool = extract_tool_name(response)
        assert actual_tool == case["expected_tool"]
```

---

## 常用工具集成框架

| 框架 | 适用场景 | 工具调用特性 |
|------|---------|------------|
| LangChain | 通用 LLM 应用 | 内置 Tool 抽象，支持多模型 |
| LlamaIndex | 知识检索增强 | 专用 Tool 集成，数据源丰富 |
| AutoGen | 多代理协作 | 工具共享与代理间调用 |
| CrewAI | 多代理团队 | 角色化工具分配 |

---

## 常见错误与解决方案

| 错误 | 原因 | 解决方案 |
|------|------|---------|
| 工具调用死循环 | LLM 重复调用同一工具 | 添加调用计数，超限返回停止 |
| 工具返回格式不匹配 | 工具描述与实际返回不一致 | 标准化返回格式，严格 Schema |
| 并行调用超限 | 工具数超过模型限制 | 分批调用或使用选择器 |
| 工具超时未处理 | 网络不稳定 | 实现超时检测与重试 |
| 参数类型推断错误 | 参数描述不精确 | 使用 JSON Schema 精确约束 |