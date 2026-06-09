# 专家知识增强专家池（Expert Knowledge Pool）

> 来源：ClawTeam 知识库建设经验蒸馏 · 2026-05-17
> 主编经验：12位金融方向 + 10位法律方向 + 5位内容创作 + 2位行业研究 + **8位AI Agent工程方向**

---

## 1. 知识工程专家池架构

```
专家池（Expert Pool）
│
├── 📈 金融方向专家（12位）
│   ├── 价值投资：巴菲特（Berkshire Hathaway）、芒格（Daily Journal）、邱国鹭（高毅资产）
│   ├── 宏观策略：Ray Dalio（Bridgewater）、Howard Marks（Oaktree）、任泽平（恒大研究院）、
│   │           李迅雷（中泰证券）、伍戈（红塔证券）
│   ├── 量化因子：Fama（ Fama-French 三因子）、French、Fama-French五因子、Asness（AQR Capital）、
│   │            John Lakomosh（Better System）、李斌（香港量化）、David Shaw（D.E. Shaw）
│   ├── DCF估值：Damodaran（NYU Stern）
│   ├── 港股研究：刘昌源（港股专家）、Ronald Yu（港股金融）、黄咏衫（高盛香港）
│   └── A股策略：陈光明（睿远基金）、张磊（高瓴资本）
│
├── ⚖️ 法律方向专家（10位）
│   ├── 民商法：王利明（中国人民大学）、梁慧星（中国社科院）
│   ├── 企业合规：刘艳（金杜律师事务所）
│   ├── FCPA合规：James M. Peck（Cleary Gottlieb Steen & Hamilton）
│   ├── DOJ指引：Henry J. Liu（Kirkland & Ellis）
│   ├── 刑事合规：FCPA专家团（Kirkland & Ellis等）
│   └── 税务：李俭（税务专家）
│
├── 🎬 内容创作方向（5位）
│   ├── 抖音：陈次（字节跳动，流量池算法）
│   ├── 小红书：林默（KFS组合）、陈雪频（算法分析）
│   ├── B站：苏琪（B站运营）
│   └── 平台算法：魏美（多平台算法机制）
│
└── 🏭 行业研究专家（2位）
    ├── 医药：未完成（超时）
    └── 其他：待扩展
│
└── 🤖 AI Agent工程方向（9位）⚡新增
    ├── 多智能体架构：Andrej Karpathy（Tesla AI）、Sasha Rush（晨星）
    ├── Prompt工程：Ian Goodfellow（推测）
    ├── 工具调用：LangChain团队（LangChain）、OpenAI tool use团队
    ├── 错误恢复：生产级Agent容错专家
    ├── 可观测性：Agent监控与日志专家
    ├── 上下文管理：Memory/HISTORY管理专家
    ├── 工作流编排：DAG/状态机专家
    ├── 评估基准：GAIA/BIG-bench评估专家
    └── **技能运用：90+本机技能检索与调用专家** ← 新增
```

---

## 2. 专家知识注入匹配表

| 知识文件 | 增强需求 | 匹配专家 | 注入优先级 | 状态 |
|---------|---------|---------|-----------|------|
| stock-analyst.md | 护城河五分类+PEG+GARP+渗透率拐点 | 邱国鹭+陈光明+张磊 | P0→P2 | ✅已完成 |
| macro-forecasting-model.md | 产能周期+美林时钟A股+信用脉冲 | 任泽平+李迅雷+伍戈 | P0→P1 | ✅已完成 |
| hk-stock-analysis.md | 做空狙击+金融股PB+管线估值 | 刘昌源+Ronald Yu+黄咏衫 | P0→P2 | ✅已完成 |
| alternative-data-guide.md | 因子IC-IR+A股因子库+信号衰减 | John Lakomosh+李斌+David Shaw | P0→P2 | ✅已完成 |
| content-director.md | 抖音流量池+KFS组合 | 陈次+林默 | P0→P1 | ✅已完成 |
| platform-adapter.md | 各平台算法评分公式 | 魏美+陈雪频 | P1 | ✅已完成 |
| criminal-compliance.md | FCPA自愿披露+不起诉+DOJ罚款 | James M. Peck+刘艳+Henry J. Liu | P1→P2 | ✅已完成 |
| dc-stock-analysis.md | DCF估值+ROE模型 | Damodaran+陈光明 | P0→P2 | 🔄待完成 |
| risk-management.md | VaR/CVaR+压力测试 | Asness+Ray Dalio | P1→P2 | 🔄待完成 |
| esg-investing.md | ESG评分+责任投资 | Howard Marks+ESG评级机构 | P2 | 🔄待完成 |

---

## 3. 专家知识来源可信度评估

### 可信度等级定义

| 等级 | 来源类型 | 可信度 | 使用建议 |
|------|---------|--------|---------|
| ★★★★★ | 专家本人公开论文/专著/官方演讲 | 最高 | 直接引用，标注作者+年份+场合 |
| ★★★★ | 权威媒体（FT/WSJ/Bloomberg/金融时报）采访 | 高 | 引用，标注媒体+日期+记者 |
| ★★★ | 行业权威报告（高盛/摩根士丹利/中金/国泰君安） | 中高 | 引用，标注机构+报告名+日期 |
| ★★ | 二手分析引用（同业分析师引用） | 中 | 需追溯原来源，增加二次引用标注 |
| ★ | 无来源/网络博客/社交媒体 | 低 | 谨慎使用，尽量不标注为权威来源 |

### 来源标注规范

```markdown
**增强来源：** [专家姓名]（[机构/身份]），[年份]年[具体场合/发布物]
- 例1：**增强来源：** 黄咏衫（高盛香港），2023~2024年港股18A估值方法（《ubs医药研报》系列）
- 例2：**增强来源：** Damodaran（NYU Stern），2024年《Damodaran估值讲义》第12章
- 例3：**增强来源：** Ray Dalio（Bridgewater），2023年《原则：应对变化的世界》演讲
```

### 可信度检索优先级

```
当需要引用某专家观点时，按以下优先级检索：
1. 专家本人公开论文/专著（★★★★★）
   → Google Scholar / 专家官网 / 官方公众号
2. 权威媒体专访（★★★★）
   → FT中文网 / WSJ / Bloomberg / 36氪/虎嗅
3. 权威机构研报（★★★）
   → 高盛/摩根士丹利/中金/国泰君安研报数据库
4. 二手分析（★★）
   → 追溯原始来源
5. 网络资源（★）
   → 谨慎使用，注明"网络资源，待考证"
```

---

## 4. 金融方向专家详解

### 4.1 价值投资派

| 专家 | 机构 | 核心贡献 | 适用知识文件 |
|------|------|---------|------------|
| 巴菲特 | Berkshire Hathaway | 护城河理论（moat）、内在价值 | stock-analyst.md |
| 芒格 | Daily Journal | 多学科思维模型、长期复合增长 | stock-analyst.md |
| 邱国鹭 | 高毅资产 | 护城河五分类、估值三因子 | stock-analyst.md |

### 4.2 宏观策略派

| 专家 | 机构 | 核心贡献 | 适用知识文件 |
|------|------|---------|------------|
| Ray Dalio | Bridgewater | 全天候策略、债务周期、经济机器 | macro-forecasting-model.md |
| Howard Marks | Oaktree | 周期判断、风险规避、信贷周期 | macro-forecasting-model.md |
| 任泽平 | 恒大研究院 | 产能周期、新基建、货币政策 | macro-forecasting-model.md |
| 李迅雷 | 中泰证券 | 信用脉冲、资产配置、人口周期 | macro-forecasting-model.md |
| 伍戈 | 红塔证券 | 货币政策传导、信用周期 | macro-forecasting-model.md |

### 4.3 量化因子派

| 专家 | 机构 | 核心贡献 | 适用知识文件 |
|------|------|---------|------------|
| Fama | Chicago Booth | Fama-French三因子/五因子 | alternative-data-guide.md |
| French | Dartmouth | Fama-French因子实证 | alternative-data-guide.md |
| Asness | AQR Capital | 动量因子、价值因子、量化策略 | quant-risk-dashboard.md |
| John Lakomosh | Better System | A股因子库、信号衰减 | alternative-data-guide.md |
| 李斌 | 香港量化 | A股Alpha因子、IC-IR评估 | alternative-data-guide.md |
| David Shaw | D.E. Shaw | 统计套利、量化策略系统 | stock-strategy-backtester.md |

### 4.4 港股研究派

| 专家 | 机构 | 核心贡献 | 适用知识文件 |
|------|------|---------|------------|
| 刘昌源 | 港股专家 | 港股做空机制、老千股识别 | hk-stock-analysis.md |
| Ronald Yu | 港股金融 | 港股金融股PB、ROE模型 | hk-stock-analysis.md |
| 黄咏衫 | 高盛香港 | 港股18A管线估值、概率树模型 | hk-stock-analysis.md |

---

## 5. 法律方向专家详解

### 5.1 FCPA合规专家链

```
举报人 → 企业内部合规部门 → 外部律师（James M. Peck/Henry J. Liu）
                                              ↓
                        DOJ决定：不起诉协议（NPA）/ 认罪协议（DPA）
                                              ↓
                        民事罚款计算：基于非法所得×倍数
```

| 专家 | 机构 | 核心贡献 | 适用知识文件 |
|------|------|---------|------------|
| James M. Peck | Cleary Gottlieb | FCPA自愿披露框架、反垄断调查应对 | criminal-compliance.md |
| Henry J. Liu | Kirkland & Ellis | DOJ不起诉协议谈判、FCPA罚款计算 | criminal-compliance.md |
| 刘艳 | 金杜律师事务所 | 中国企业合规体系搭建、数据安全 | criminal-compliance.md |

### 5.2 民商法专家

| 专家 | 机构 | 核心贡献 | 适用知识文件 |
|------|------|---------|------------|
| 王利明 | 中国人民大学 | 民法典解读、公司法修订 | 公司治理/合规基础 |
| 梁慧星 | 中国社科院法学所 | 合同法、物权法、民法总则 | 合同管理/合规基础 |

---

## 6. 内容创作方向专家详解

### 6.1 平台算法专家

| 专家 | 平台 | 核心贡献 | 适用知识文件 |
|------|------|---------|------------|
| 陈次 | 字节跳动 | 抖音流量池算法、推荐系统架构 | content-director.md |
| 魏美 | 多平台 | 各平台评分公式、算法评分机制 | platform-adapter.md |
| 林默 | 小红书 | KFS组合（刷+粉+搜）投放策略 | content-director.md |
| 陈雪频 | 小红书 | 小红书算法推荐机制分析 | platform-adapter.md |
| 苏琪 | B站 | B站内容分发、UP主运营策略 | content-director.md |

### 6.2 平台算法可信度对比

| 平台 | 算法透明度 | 主要流量来源 | 内容生命周期 |
|------|---------|------------|------------|
| 抖音 | 低（黑盒） | 推荐页>80% | 48h黄金期 |
| 小红书 | 中（半透明） | 推荐+搜索各半 | 7~30天 |
| B站 | 高（相对透明） | 关注+推荐各半 | 长尾效应强 |

---

## 7. 专家知识更新机制

### 7.1 触发条件

- 同领域新论文/新观点出现
- 原有专家有新公开演讲/采访/著作
- 知识文件引用来源被证伪或过时
- 用户/主编识别到知识缺口

### 7.2 更新流程

```
主编识别知识缺口
    ↓
检索专家最新公开材料（按可信度优先级）
    ↓
验证材料可信度（★≥3再使用）
    ↓
追加到知识文件对应章节
    ↓
更新来源标注（注明更新日期）
    ↓
在文件末尾「更新日志」记录
```

### 7.3 更新日志格式

```markdown
## 更新日志

| 日期 | 更新内容 | 来源 | 执行人 |
|------|---------|------|-------|
| 2026-05-17 | 初始版本：港股18A管线估值概率树模型 | 黄咏衫（高盛香港）2023~2024年研报 | 主编 |
| 2026-06-01 | 新增FCPA自愿披露谈判框架 | James M. Peck（Cleary Gottlieb）2024年演讲 | 主编 |
```

---

## 8. 专家知识检索工具推荐

| 工具 | 适用场景 | 网址/说明 |
|------|---------|---------|
| Google Scholar | 检索英文论文 | scholar.google.com |
| CNKI知网 | 检索中文论文 | cnki.net |
| 私募排排网 | 检索量化私募观点 | simuwang.com |
| 萝卜投研 | 检索券商研报 | r.datayes.com |
| 雪球 | 检索投资者讨论 | xueqiu.com |
| 高盛研报库 | 检索外资行研报 | Goldman Sachs Research |
| 中金公司研报 | 检索中资行研报 | cics.com |
| 巨潮资讯网 | 检索A股公告/财报 | cninfo.com.cn |