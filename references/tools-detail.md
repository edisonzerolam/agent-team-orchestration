# agent-team-orchestration 工具与增强模块参考

## 团队管理脚本

| 脚本 | 命令 | 用途 |
|------|------|------|
| `team-brain.py` | `python team-brain.py launch "topic" "desc" [max]` | 启动团队 |
| `team-brain.py` | `python team-brain.py status [team_id]` | 检查状态 |
| `team-brain.py` | `python team-brain.py synthesis <team_id>` | 综合报告 |
| `health-monitor.py` | `python health-monitor.py check\|watch\|summary` | 心跳检测 |
| `health-dashboard.py` | `python health-dashboard.py serve\|export` | Web 面板 |
| `auto-decider.py` | `python auto-decider.py decide <type> "<msg>" [retry]` | 错误决策 |
| `self_heal.py` | `python self_heal.py test\|summary <team_id> <agent_id>` | 自愈引擎 |

## 增强模块（v4.0）

| 模块 | 文件 | 功能 | 依赖 |
|------|------|------|:----:|
| 结构化论证 | `conflict_detector.py` (Argument) | CHALLENGE payload 结构化字段 | 无 |
| 冲突检测 | `conflict_detector.py` | 关键词+规则冲突检测（零 NLP） | 无 |
| 时间盒执行器 | `timebox_enforcer.py` | 分层计时+超时+用户干预 | 无 |
| 反形式主义 | `anti_formalism.py` | 长度+引用 2 维检查 | 无 |
| 辩论控制器 | `debate_controller.py` | 嵌入 Hub，管理辩论轮次 | conflict_detector |
| 专家权重 | `expert_weight.py` | 角色×领域×记录 权重系统 | 无 |
| 共识度量 | `consensus_metrics.py` | strong/moderate/weak/failed 四级 | 无 |
| 历史模式库 | `discussion_history.py` | 结果持久化+相似任务推荐 | 无 |
| 专家匹配 | `expert_matcher.py` | 任务→最佳专家组合 | 无 |

### Feature Flags

```json
// enhancement_config.json
{
  "enhancements": {
    "structured_argument": {"enabled": true},
    "conflict_detector": {"enabled": true},
    "timebox_enforcer": {"enabled": true},
    "debate_controller": {"enabled": true},
    "anti_formalism": {"enabled": true},
    "expert_weights": {"enabled": true},
    "consensus_metrics": {"enabled": true},
    "discussion_history": {"enabled": false},
    "expert_matcher": {"enabled": false}
  }
}
```

出问题时设为 false 即回退。

### 运行测试

```bash
python scripts/test_enhancements.py
python scripts/test_enhancements.py --module=conflict_detector
```

## 优化模块

| 模块 | 文件 | 功能 |
|------|------|------|
| 消息批量写入 | `scripts/hub.py` (HubBuffer) | Hub 消息缓冲，I/O 减少 80% |

```python
from hub import HubBuffer
from pathlib import Path
buffer = HubBuffer(batch_size=10, flush_interval=1.0, outbox_root=Path("messages/outbox"))
buffer.add_message(msg_dict, agent_id)
buffer.flush()
buffer.start()
buffer.stop()
```

## 知识库协同

| 目录 | 说明 |
|------|------|
| `references/knowledge/` | 知识文件，团队模板专家知识 |
| `references/expert-knowledge-pool.md` | 专家知识池 |

专家条目格式：
```markdown
## 邱国鹭
- 领域：价值投资护城河
- 详见：knowledge/stock-analyst.md##3（护城河五分类章节）
```