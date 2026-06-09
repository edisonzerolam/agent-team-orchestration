# agent-team-orchestration 多智能体团队编排（中文版）

多 agent 团队协作，包括角色定义、交接协议、检查点机制和质量门禁。包含专家知识池和团队模板。

🌐 **语言**: [English](README.md) | **简体中文**（当前）

## 描述

为 OpenClaw 框架提供多 agent 团队协作能力。

### 核心特性

- **角色定义**：每个 agent 有明确的角色和职责
- **交接协议**：结构化的 What/Where/Verify/Known/Next 五段式交接
- **检查点机制**：每 2 分钟自动写入状态
- **质量门禁**：每个交接点都有验收条件
- **专家知识池**：可复用的专家协作模板
- **团队模板**：常见任务类型（研究、审计、写作）的现成模板

### 适用场景

- 多 agent 协同完成复杂任务
- 专家小组任务（专家路由 + 协调）
- 跨会话任务的状态管理
- 团队协作的质量保证

## 安装

将整个 agent-team-orchestration/ 目录复制到 OpenClaw 技能目录（通常是 ~/.openclaw-skills/agent-team-orchestration/）。

## 目录结构

\agent-team-orchestration/
├── SKILL.md          # 技能主定义（先读这个）
├── references/       # 参考文档
├── scripts/          # 可执行工具
├── _knowledge/       # 知识库
└── _meta.json        # 技能元数据
\
## 许可证

MIT — 详见 [LICENSE](LICENSE)

---

## 🙋 致中国用户

本仓库同时提供英文和简体中文文档。如果你发现任何翻译问题，欢迎提 Issue 或 PR。
