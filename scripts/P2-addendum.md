---

## P2 阶段模块（v2.0.0）

| 模块 | 文件 | 功能 | 状态 |
|------|------|------|------|
| Self-Heal 增强 | `scripts/self_heal.py` | 自动修复 PowerShell 错误 | ✅ v2.0.0 |
| Auto-Decider 扩展 | `scripts/auto-decider.py` | 决策引擎扩展至 9 种错误类型 | ✅ v2.0.0 |
| Checkpoint 验证 | `scripts/checkpoint-poller.py` | Agent 卡住检测 | ✅ 已就绪 |

### Self-Heal v2.0.0 使用

```python
from self_heal import SelfHeal

healer = SelfHeal(team_id="my-team", agent_id="expert-1")
result = healer.handle_error(
    error_message="PowerShell regex error: $HOME 非法",
    error_type=None,  # 自动推断
    context={"command": "echo $HOME"}  # 可选上下文
)
print(f"Action: {result['action']}, Fix: {result['fix_action']}")
```

### Auto-Decider v2.0.0 使用

```bash
# 自动推断错误类型并决策
python auto-decider.py auto "文件找不到 test.txt"

# 指定错误类型
python auto-decider.py decide powershell_regex "regex error" 0

# 批量测试
python auto-decider.py batch test_cases.json

# 列出所有错误类型
python auto-decider.py list
```

---

*版本: v2.1 | 更新: 2026-05-24 | P2: v2.0.0*