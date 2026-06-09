# Lazy Loading Index（懒加载索引）

> 本文件是 agent-team-orchestration skill 的懒加载策略实现核心。

## 加载策略

| 类型 | 时机 | 策略 |
|------|------|------|
| **热数据** | SKILL.md加载后立即 | 全部加载 |
| **冷数据** | 触发关键词命中时 | 按需从 `_knowledge/` 加载对应文件 |

## 热数据区（首次加载）

| 文件 | 加载时机 | 说明 |
|------|---------|------|
| `_knowledge/_index/keyword-index.md` | 首次 | 关键词→文件映射（25KB） |
| `_knowledge/_index/topic-index.md` | 首次 | 主题→文件映射（10KB） |
| `_knowledge/core-principles/*.md` | 首次 | 核心原则（少量） |

## 冷数据区（按需加载）

以下文件通过关键词触发后从 `_knowledge/` 加载：

### 团队模板（team-templates）
| 触发关键词 | 文件路径 |
|-----------|----------|
| 内容创作/AI创作 | `references/team-templates/ai-content-creator.md` |
| 设计/设计引擎 | `references/team-templates/design-engine.md` |
| 内容分发/分发策略 | `references/team-templates/content-distribution.md` |
| 报告撰写/编译 | `references/team-templates/report-compiler.md` |

### 专家知识（knowledge）
| 触发关键词 | 文件路径 |
|-----------|----------|
| 估值/DCF/CAPM | `references/knowledge/valuation-expert.md` |
| 风险/回撤/Beta | `references/knowledge/risk-assessor.md` |
| 平台/抖音/小红书 | `references/knowledge/platform-analyst.md` |
| 合同/法务/谈判 | `references/knowledge/contract-specialist.md` |
| 并购/尽调 | `references/knowledge/ma-specialist.md` |
| 刑事合规 | `references/knowledge/criminal-compliance.md` |
| AI治理 | `references/knowledge/ai-governance-specialist.md` |

### 外部知识（external）
| 触发关键词 | 文件路径 |
|-----------|----------|
| A2A协议/CrewAI | `references/external/team-orch-expert-knowledge.md` |
| 多智能体架构 | `references/external/team-orch-expert-knowledge.md` |

### 核心原则（core-principles）
| 触发关键词 | 文件路径 |
|-----------|----------|
| 团队编排原则 | `core-principles/team-orch-principles.md` |
| P4最小上下文 | `core-principles/team-orch-principles.md` |

## 加载实现

```python
def load_knowledge_lazily(keyword, knowledge_root):
    """根据关键词懒加载知识文件"""
    index = load_index(knowledge_root + "/_index/keyword-index.md")
    
    if keyword in index:
        file_path = knowledge_root + "/" + index[keyword]
        return load_file(file_path)
    
    return None  # 未找到

def on_trigger(keyword):
    """触发词命中时的回调"""
    content = load_knowledge_lazily(keyword, KNOWLEDGE_ROOT)
    if content:
        inject_context(content)
```

## 完整文件列表

详见 `_knowledge/_index/file-manifest.md`（所有文件的完整清单）

---

*版本: v1.0*  
*更新: 2026-05-24*