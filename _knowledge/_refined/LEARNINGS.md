# LEARNINGS.md — agent-team-orchestration 自学习触发机制

> 版本：v1.0（初始骨架）| 更新：2026-05

---

## 概述

本文件记录 agent-team-orchestration skill 的自学习机制——即 skill 如何从实战经验中自动积累知识、修正行为。

---

## 触发条件（Trigger Conditions）

| 触发类型 | 触发条件 | 触发动作 |
|----------|----------|----------|
| **任务级反思** | 团队任务完成后（Done/Failed） | Orchestrator 生成任务反思摘要 |
| **模式识别** | 同一模式出现≥3次 | 提取为标准模式写入 patterns.md |
| **失败模式记录** | 任务Failed或打回≥2次 | 记录失败根因到 pitfalls.log |
| **效率异常** | 任务耗时超出预期≥50% | 触发效率分析，记录到 efficiency-log.md |
| **新模式发现** | 成功解决非标准问题 | 归档到 knowledge/ 对应专家角色 |
| **用户干预** | 用户手动介入调整了Orchestrator决策 | 记录干预原因，审视规则是否需更新 |
| **T3+崩溃续接** | T3+任务异常退出且`can_resume_from.can_resume=true` | 续接成功→记录到efficiency-log；续接失败→记录根因到pitfalls.log |
| **checkpoint缺失** | T3+任务完成但checkpoint中`completed_subtasks`不完整 | 更新checkpoint规范，下次强制填写 |
| **超时异常** | 任务超时（elapsed > timeout_setting）| 记录超时详情到efficiency-log.md |
| **超时根因** | 同一类任务超时≥2次 | 分析根因，更新T等级判定标准 |

---

## 自学习生命周期

任务完成 → 触发反思 → 分类记录 → 规则更新 → 下次生效

### Step 1：任务反思（Post-task Reflection）

每次任务完成后，Orchestrator 自动记录：
- 任务ID、耗时、参与者
- 是否按协议执行（是/否，偏差原因）
- 最终结果（Done/Failed/部分完成）
- 是否发生用户干预
- 关键决策点回顾

### Step 2：分类与路由（Classification & Routing）

反思结果根据内容路由到不同积累位置：

| 反思内容类型 | 目标文件 |
|-------------|---------|
| 新的成功模式 | references/patterns.md（追加新模式） |
| 失败根因 | pitfalls.log（追加条目） |
| Token超支 | efficiency-log.md（追加记录） |
| 规则漏洞 | SKILL.md + core-principles/（规则更新） |
| 领域新知识 | knowledge/ 对应专家角色文件 |

### Step 3：规则更新（Rule Update）

当 pitfalls.log 中同类失败根因出现≥2次时：
1. 提取共性根因
2. 更新 core-principles/team-orch-principles.md 或 SKILL.md
3. 在更新记录中标注：触发来源（pitfalls.log条目ID）

### Step 4：知识库更新（Knowledge Base Update）

当 efficiency-log.md 或任务反思揭示领域知识空白时：
1. 识别所需专家角色类型
2. 创建/更新 references/knowledge/<role>.md
3. 在 knowledge-pool-index.md 中建立映射

---

## 积累文件清单

| 文件 | 用途 | 更新频率 |
|------|------|---------|
| pitfalls.log | 失败根因日志 | 每次Failed触发 |
| efficiency-log.md | 效率异常记录 | 每次超时触发 |
| patterns.md | 成功模式积累 | 同模式出现≥3次 |
| knowledge/ | 专家角色知识 | 按需新增/更新 |
| LEARNINGS.md | 自学习机制本身 | 机制更新时重写 |

---

## 初始骨架待填充项

- [ ] pitfalls.log 文件创建和格式定义
- [ ] efficiency-log.md 文件创建和格式定义
- [ ] knowledge-pool-index.md 从现有39个专家文件反向生成
- [ ] 自学习脚本 self-learn.py（自动分析 pitfalls.log 触发规则更新）
- [ ] 与 checkpoint-poller.py 集成：崩溃恢复后自动触发反思

---

## 回顾计划

- **每周**：Orchestrator 回顾 pitfalls.log，识别反复失败模式
- **每月**：更新 LEARNINGS.md，反映自学习机制的进化
- **每任务**：轻量反思（Orchestrator 内记忆或简短笔记），不做完整记录

---

## 超时自学习规则（追加）

| 触发类型 | 触发条件 | 触发动作 |
|----------|----------|----------|
| **超时异常** | 任务超时（elapsed > timeout_setting）| 记录超时详情到efficiency-log.md |
| **超时根因** | 同一类任务超时≥2次 | 分析根因，更新T等级判定标准 |

### T3+ 续接自学习流程

任务崩溃 → 读取death-report → 判断can_resume → 可续接→从checkpoint恢复→记录效率收益 / 不可续接→记录pitfalls→调整策略
