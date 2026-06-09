# agent-team-orchestration 自学习与事实核查

## 事实核查

每次执行完成、返回结果前必须调用共享事实核查工具。

```python
from fact_check import fact_check

result = fact_check(
    task_description="...",
    execution_summary="...",
    output_claims=["团队已组建", "任务分配完成"],
    skill_context={"skill": "agent-team-orchestration", "complexity": "T4"},
    source_claims=[
        {
            "file": "path/to/file.py",
            "description": "函数foo存在日期边界检查",
            "expected_find": "if date < start_date",
        }
    ],
    base_dir="."
)
```

### 核查标准

| 维度 | 检查内容 |
|:----:|---------|
| 完整性 | 任务全部分配？超时策略设置？checkpoint 配置？ |
| 准确性 | 角色数量/超时等级/agent 数量准确？ |
| 边界 | 是否在技能范围内？有无越界？ |
| 一致性 | 执行是否按 Orchestrator 流程？遵守 P6 超时管理？ |

### T3+ 特殊要求

- checkpoint 是否每 2 分钟写入
- `completed_subtasks` 完整记录
- `can_resume_from` 已配置

### 结果处理

| 结果 | 处理 |
|:----:|------|
| PASS | 直接返回团队状态报告 |
| WARN | 返回 + 标注未完成项 |
| FAIL | 不返回，先修复再返回 |

工具路径：`_shared/fact-checker/fact_check.py`

## 增强层冷数据加载

| 文件 | 触发关键词 | 说明 |
|------|-----------|------|
| `_knowledge/knowledge-team-workflow.md` | 主编/工作流/团队 | 主编角色定义 |
| `_knowledge/multi-agent-architect.md` | 多智能体/架构 | 多智能体架构专家（P1）|
| `_knowledge/tool-integration-specialist.md` | 工具调用/集成 | 工具集成专家（P1）|
| `_knowledge/skill-usage-expert.md` | 技能调用/协作 | 90+ 本机技能检索与调用 |

## 知识库协同

| 目录 | 说明 |
|------|------|
| `references/knowledge/` | 知识文件 |
| `references/expert-knowledge-pool.md` | 专家知识池 |