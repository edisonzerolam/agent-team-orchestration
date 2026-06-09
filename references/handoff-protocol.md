# 交接协议（Handoff Protocol）

> 所有 ClawTeam 团队模板的交接协议标准定义。规范 agent 之间的交接格式和验收条件。

---

## 通用产出物格式

每个 agent 完成后应产出标准 artifact 文件，格式如下：

```yaml
---
team_id: {team_id}
agent_id: {agent_id}
role: {角色名}
phase: {当前阶段}
status: done|in_progress|failed
progress: {百分比}
created_at: {ISO时间戳}
findings: |
  ## 核心发现
  - 发现1
  - 发现2
---
```

---

## Handoff Timing字段（追加）

| 字段 | 内容 |
|------|------|
| estimated_duration | 预估时长（T1-T5等级 + 估算分钟）|
| timeout_setting | 设置的超时秒数 |
| escalation_path | 超时后的处理路径（续接/重来/人工）|

---

## ai-content-creator（AI内容创作）

### 交接矩阵

| 上游agent | 下游agent | 交接产物 | 验收字段 |
|-----------|-----------|----------|----------|
| content-director | scriptwriter | content-plan.md | phase=planning, status=done |
| scriptwriter | visual-artist | script.md + narrative.md | phase=scripting, status=done |
| visual-artist | video-editor | image-assets/*.png | phase=visual, status=done |
| video-editor | platform-adapter | rough-cut.mp4 | phase=editing, status=done |
| platform-adapter | — | final-content/*.mp4 | phase=adaptation, status=done |

### 验收规则
- 交付物必须包含完整内容，不得有占位符
- 视觉素材分辨率≥1080p
- 视频时长误差±10秒以内

---

## ai-data-copilot（数据分析）

### 交接矩阵

| 上游agent | 下游agent | 交接产物 | 验收字段 |
|-----------|-----------|----------|----------|
| data-architect | sql-developer | data-plan.md | phase=planning, status=done |
| sql-developer | model-engineer | sql-results.md | phase=sql, status=done |
| model-engineer | visualization-expert | model-results.md | phase=modeling, status=done |
| visualization-expert | knowledge-synthesizer | dashboard.html | phase=visualization, status=done |
| knowledge-synthesizer | report-writer | knowledge-findings.md | phase=synthesis, status=done |

### 验收规则
- SQL 结果条数≥10条
- Dashboard 必须包含≥3个图表
- 报告必须包含业务建议

---

## a-share-analysis（A股研究）

### 交接矩阵

| 上游agent | 下游agent | 交接产物 | 验收字段 |
|-----------|-----------|----------|----------|
| macro-analyst | market-strategist | macro-analysis.md | phase=macro, status=done |
| market-strategist | industry-researcher | market-analysis.md | phase=market, status=done |
| industry-researcher | stock-analyst | industry-analysis.md | phase=industry, status=done |
| stock-analyst | valuation-expert | stock-analysis.md | phase=stock, status=done |
| valuation-expert | money-flow-tracker | valuation-analysis.md | phase=valuation, status=done |
| money-flow-tracker | risk-assessor | money-analysis.md | phase=money, status=done |
| risk-assessor | synthesis-writer | risk-analysis.md | phase=risk, status=done |

### 验收规则
- 每份报告必须有数据支撑（至少3个具体数据点）
- 估值区间必须给出上下限
- 风险评估必须覆盖≥5项风险因素

---

## chatlaw（法律咨询）

### 交接矩阵

| 上游agent | 下游agent | 交接产物 | 验收字段 |
|-----------|-----------|----------|----------|
| intake-specialist | legal-researcher | case-facts.md | phase=intake, status=done |
| legal-researcher | precedent-analyst | legal-research.md | phase=research, status=done |
| precedent-analyst | litigation-strategist | precedent-analysis.md | phase=precedent, status=done |
| litigation-strategist | report-compiler | legal-advice.md | phase=strategy, status=done |

### 验收规则
- 案情要素必须包含当事人、时间、地点、事件经过
- 判例分析至少引用2个真实案例
- 法律建议必须具体可操作

---

## content-distribution（内容分发）

### 交接矩阵

| 上游agent | 下游agent | 交接产物 | 验收字段 |
|-----------|-----------|----------|----------|
| strategy-director | platform-analyst | distribution-plan.md | phase=strategy, status=done |
| platform-analyst | domestic-strategist | platform-analytics.md | phase=analysis, status=done |
| platform-analyst | international-strategist | platform-analytics.md | phase=analysis, status=done |
| domestic-strategist | calendar-manager | domestic-strategy.md | phase=domestic, status=done |
| international-strategist | calendar-manager | international-strategy.md | phase=international, status=done |

### 验收规则
- 每个平台必须提供至少1个适配版本
- 排期表必须覆盖整个发布周期
- 发布时间必须精确到小时

---

## content-monetization（内容变现）

（待补充）

## design-engine（设计引擎）

（待补充）

## engineering-assurance（工程保障）

（待补充）

## enterprise-legal（企业法务）

（待补充）