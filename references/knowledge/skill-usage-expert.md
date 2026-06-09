# 技能运用专家知识库（Skill Usage Expert）

> 来源：本机技能库蒸馏 · 2026-05-24
> 主编经验：90+技能覆盖，涉及量化/内容/效率/平台集成

---

## 1. 身份定义

### 角色ID
`skill-usage-expert`

### 核心职责
当专家角色需要使用本机技能时，提供技能检索、调用和协作支持。

### 适用场景
- 专家判断"这个任务需要XXX技能介入"
- 任务超出当前专家的知识范围，需要技能补充
- 用户明确提到技能名称（如"用xlsx处理"）
- 跨技能协作需求

### 不适用场景
- 纯对话/闲聊无需技能
- 任务已被专家独立完成
- 用户明确拒绝技能介入

---

## 2. 核心方法论：技能路由决策树

```
任务输入
    │
    ▼
是否涉及文件操作（读写/处理）？
    ├─ YES → 文件类型是什么？
    │         ├─ .xlsx/.csv/.tsv → xlsx skill 或 pandas
    │         ├── .docx/.doc → docx skill
    │         ├── .pdf → pdf skill
    │         ├── .pptx → pptx-generator skill
    │         └── 其他 → qclaw-text-file skill
    │
    └─ NO → 任务类型是什么？
              ├─ 联网搜索 → multi-search-engine 或 online-search
              ├─ 深度研究 → deep-research
              ├─ 浏览器操作 → xbrowser
              ├─ 量化分析 → stock-analysis 或 quant-system-5steps
              ├─ 写作/文档 → writing-beats 或 docx
              ├─ 代码优化 → agent-planner 或 capability-evolver
              ├─ 定时任务 → qclaw-cron-skill
              ├─ 云文档 → tencent-docs
              ├─ 知识库 → ima 或 knowledge-base
              └─ 其他 → find-skills（检索技能）
```

---

## 3. 关键技能速查表

### 📊 量化金融方向

| 技能名 | 触发词 | 核心能力 |
|--------|--------|---------|
| `stock-analysis` | "股票分析" "个股" "虚拟组合" | 个股分析、虚拟组合、8维评分 |
| `quant-system-5steps` | "量化系统" "5步量化" | 5步量化框架、多源数据 |
| `market-overview` | "市场综述" "行情" | 全球市场联动、盘前盘后 |
| `backtest-expert` | "回测" "回测引擎" | 回测框架、策略验证 |
| `pylib` | "Python优化" "加速" | Python性能优化、量化库 |
| `fund-analyzer` | "基金分析" | 基金筛选、绩效归因 |

### 📝 文档写作方向

| 技能名 | 触发词 | 核心能力 |
|--------|--------|---------|
| `docx` | "Word文档" ".docx" | 创建/编辑Word文档 |
| `pdf` | "PDF处理" ".pdf" | 提取/创建/合并PDF |
| `xlsx` | "Excel" ".xlsx" | 读写Excel、处理表格数据 |
| `pptx-generator` | "PPT" "幻灯片" | 创建专业PPT |

### 🔍 搜索研究方向

| 技能名 | 触发词 | 核心能力 |
|--------|--------|---------|
| `multi-search-engine` | "搜索" "联网检索" | 16引擎搜索（7中文+9英文） |
| `deep-research` | "深度研究" "调研报告" | 多源研究、引用追踪 |
| `xbrowser` | "浏览器" "网页操作" | 浏览器自动化、网页抓取 |
| `online-search` | "元宝搜索" | 腾讯元宝联网搜索 |

### ⚙️ 系统效率方向

| 技能名 | 触发词 | 核心能力 |
|--------|--------|---------|
| `tencent-docs` | "腾讯文档" "云文档" | 创建/管理腾讯文档 |
| `ima` | "知识库" "笔记" | 知识库管理、笔记搜索 |
| `qclaw-cron-skill` | "定时" "提醒" "cron" | 定时任务、周期执行 |
| `cloud-upload-backup` | "上传" "备份" | 云端文件上传 |
| `find-skills` | "找技能" "安装技能" | 技能库检索与安装 |

### 🎨 内容创意方向

| 技能名 | 触发词 | 核心能力 |
|--------|--------|---------|
| `writing-beats` | "写作" "文章结构" | 结构化写作、风格指导 |
| `market-overview` | "市场分析" | 市场情绪解读 |
| `content-factory` | "内容创作" | 内容批量生产 |

### 🛠️ 开发调试方向

| 技能名 | 触发词 | 核心能力 |
|--------|--------|---------|
| `agent-planner` | "规划" "方案设计" | Agent规划、子任务分解 |
| `capability-evolver` | "能力提升" "自我改进" | 自我改进、能力进化 |
| `debug` | "调试" "排错" | 日志追踪、错误定位 |
| `auditor` | "审计" "合规检查" | 系统诊断、合规审计 |

---

## 4. 技能调用协议

### 标准调用流程
```
1. 识别需求 → 判断是否需要技能介入
2. 检索技能 → 使用 find-skills 或直接匹配触发词
3. 加载SKILL.md → 读取技能定义文件
4. 执行任务 → 按技能规范调用工具
5. 返回结果 → 结构化输出给专家
```

### 技能参数传递规范
```python
# 标准技能调用示例（sessions_spawn）
sessions_spawn(
    task='...',           # 任务描述
    label='xxx-expert',   # 专家标签
    mode='run'
)

# 技能内工具调用示例
qclaw_tdoc_mcp_call(tool_name="create_smartcanvas_by_mdx", arguments={...})
```

### 技能间协作格式
```
[技能A → 技能B]
- 技能A完成任务A
- 生成中间产物：{描述}
- 传递给技能B时需说明：
  1. 输入文件路径
  2. 预期输出格式
  3. 特殊约束条件
```

---

## 5. 常见陷阱

### 陷阱1：技能冲突
```
❌ 错误场景：
同时使用 xlsx 和 pandas 处理同一文件，导致格式冲突

✅ 正确做法：
按文件类型选择单一技能，避免重复处理
```

### 陷阱2：技能版本不匹配
```
❌ 错误场景：
直接调用技能旧版本，导致功能缺失

✅ 正确做法：
先检查技能版本，必要时使用 find-skills 更新
```

### 陷阱3：过度依赖技能
```
❌ 错误场景：
简单任务也调用技能，增加复杂度

✅ 正确做法：
纯对话/简单计算直接回答，技能留给复杂场景
```

### 陷阱4：技能返回值未验证
```
❌ 错误场景：
调用技能后直接使用输出，未做格式校验

✅ 正确做法：
检查返回值格式是否符合预期，必要时降级处理
```

---

## 6. 关键技能详解

### 6.1 find-skills（技能检索专家）
```markdown
触发词："找技能" "安装技能" "有没有XX技能"
能力：SkillHub + ClawHub 双源检索

调用方式：
skillhub_install install_skill <技能名>

示例：
- 安装 quant-system-5steps：skillhub_install install_skill quant-system-5steps
- 检索相关技能：skillhub_install check_env
```

### 6.2 xbrowser（浏览器自动化）
```markdown
触发词："打开网页" "浏览器操作" "抓取网页"
能力：CDP协议控制Chrome/Edge/QQ浏览器

核心操作：
- browser(action="open", url="...")
- browser(action="snapshot")
- browser(action="screenshot")

注意事项：
- 需要浏览器已在运行
- 登录状态可复用
- 避免在同一标签页混合操作
```

### 6.3 qclaw-cron-skill（定时任务）
```markdown
触发词："定时" "提醒" "周期执行" "cron"
能力：创建/管理定时任务

使用规范：
- 必须先读取 qclaw-cron-skill/SKILL.md
- 精确时间用 cron 类型，非精确用 every
- 警惕时区差异（默认UTC）

注意事项：
- 不使用 exec sleep 模拟定时
- 周期任务优先用 isolated session
```

### 6.4 ima（知识库管理）
```markdown
触发词："知识库" "笔记" "上传文件"
能力：知识库CRUD、文件上传、内容检索

使用规范：
- 先读取 ima SKILL.md
- 上传文件使用 qclaw_read_ima_content 读取
- 知识搜索使用 ima 工具
```

### 6.5 tencent-docs（腾讯文档）
```markdown
触发词："腾讯文档" "云文档" "docs.qq.com"
能力：创建/编辑在线文档、表格、思维导图

使用规范：
- 使用 qclaw_tdoc_mcp_call 直接调用
- 智能文档：create_smartcanvas_by_mdx
- 表格：sheet.set_range_value（需先获取sheet_id）
```

---

## 7. 协作handoff格式

### handoff模板
```
[技能协作请求]
- 请求技能：{skill_name}
- 任务描述：{detailed_task}
- 输入文件：{file_path_if_any}
- 输出格式：{expected_format}
- 特殊约束：{constraints_if_any}

[状态]
- 当前阶段：{stage}
- 完成度：{percentage}%

[交接说明]
- 需方专家：{who_needs_result}
- 供方技能：{skill_name}
- 传递方式：{file_path / direct_output / session_key}
```

### 前置条件
- 技能已安装且可用
- 输入文件格式已知
- 输出格式已约定

### 后置交付物
- 结构化输出或文件路径
- 执行状态（成功/失败/部分成功）
- 失败原因（如有）

---

## 7.5 动态技能扫描（新增）

### 调用方式
```bash
python scripts/skill-scanner.py scan              # 扫描所有技能
python scripts/skill-scanner.py find <任务描述>   # TF-IDF语义匹配
python scripts/skill-scanner.py feedback <技能> <任务> <yes|no>  # 记录人工校正
python scripts/skill-scanner.py clear-cache      # 清除缓存
```

### 工作流程
```
专家角色执行任务
    ↓
检测到技能需求（静态触发词 或 "有哪些技能可用"）
    ↓
scripts/skill-scanner.py scan（首次调用时全量扫描并缓存，24h TTL）
    ↓
find子命令：TF-IDF语义匹配（中文bigram + 英文单词）
    ↓
置信度阈值：≥0.85自动调用 / 0.60-0.84建议确认 / <0.60低置信度
    ↓
返回Top-5匹配技能（含relevance/score/confidence标签）
    ↓
专家决定是否调用
```

### 技术实现
- **分词**：jieba语义分词（中文）+ 英文单词2+字符（例"审计代码质量"→审计/代码/质量/审计代码质量）
- **匹配**：TF-IDF余弦相似度，无ML依赖
- **缓存**：~/.qclaw/.skill-perception-cache.json（24h TTL）
- **阈值**：CONF_AUTO=0.50（自动），CONF_SUGGEST=0.30（建议确认）
- **反馈闭环**：~/.qclaw/.skill-perception-feedback.json（+0.2采纳/-0.1拒绝boost）
| 维度 | 静态速查表 | 动态扫描 |
|------|-----------|---------|
| 速度 | 快（O(1)） | 首次慢（~2s），后续快 |
| 准确性 | 高（人工维护） | 中（算法匹配） |
| 覆盖率 | 90+技能 | 全部已装技能 |
| 适用场景 | 高频/关键技能 | 新技能/探索场景 |

**推荐策略**：静态速查表保留用于高频场景；动态扫描用于按需发现

---

## 8. 注入指引

### 触发词清单
| 触发词 | 优先级 | 说明 |
|--------|--------|------|
| "用技能" "调用技能" | P0 | 直接触发 |
| "有没有XX技能" | P0 | 触发技能检索 |
| "用xlsx处理" "用docx写" | P0 | 触发文件处理技能 |
| "定时任务" "cron" | P1 | 触发定时技能 |
| "知识库" "上传知识库" | P1 | 触发ima |
| "腾讯文档" "云文档" | P1 | 触发tencent-docs |
| "浏览器" "打开网页" | P1 | 触发xbrowser |
| "联网搜索" "深度研究" | P2 | 触发搜索技能 |

### 注入章节优先级
| 场景 | 推荐章节 |
|------|---------|
| 检索合适技能 | §3（速查表）→ §2（决策树） |
| 协作交接 | §7（Handoff）→ §4（调用协议） |
| 陷阱排查 | §5（常见陷阱）→ §6（关键技能详解） |
| 学习技能使用 | §6（关键技能详解）→ §4（调用协议） |

### 注入强度
| 强度 | 触发条件 | 输出内容 |
|------|---------|---------|
| 完整注入 | 提到"技能协作"或"调用协议" | 全部8节 |
| 部分注入 | 提到具体技能名 | 相关技能详解（§6） |
| 快速提示 | 其他场景 | 仅触发词表（§8） |