# StudyStudio 课程制作全流程 — AI 工具提示词

以下是针对不同 AI 演示工具（Gamma、Tome、Beautiful.ai、讯飞智文）的完整提示词。
直接复制粘贴到对应工具的输入框中即可生成演示文稿。

---

## 一、Gamma.app 完整提示词

> 复制到 Gamma → "Create with AI" → "Paste in text"

```
生成一份专业的技术演示文稿，主题：StudyStudio 课程制作全流程 — 从文件上传到学生学习的 AI 驱动自动化系统。

整体风格：深色科技风，深蓝背景 + 青色强调色，适合技术架构演示。

请生成以下页面（共 16 页）：

第 1 页 — 封面：
标题：StudyStudio 课程制作全流程
副标题：从文件上传到学生学习的完整技术链路
底部标注：10 个自动化阶段 · 全异步事件驱动 · AI + 向量聚类合成 · v2.8.0

第 2 页 — 目录/总览：
用 2×5 卡片展示 10 个阶段：
1. 文件上传 — 格式校验 · SHA-256 去重 · MinIO
2. 事件调度 — RabbitMQ · Celery 任务分发
3. 文档解析 — PyMuPDF · 分块标准化
4. 知识提取 — 三步 LLM：识别→分类→关系
5. 自动审核 — 两轮 AI 评审
6. 向量化 — Embedding · pgvector
7. 蓝图生成 — K-Means 聚类 · LLM 章节生成
8. 测验预生成 — 自动出题
9. 学生学习 — 三种阅读模式 + 互动
10. 教师精调 — 自然语言重写章节

第 3 页 — 系统架构全景：
展示 5 层架构：
- 前端层：Vue 3 + TS (UploadView, TutorialView)
- API 网关：FastAPI (REST + WebSocket + EventBus)
- 消息队列：RabbitMQ (事件驱动链路)
- Celery Workers：knowledge / review / blueprint.synthesis 队列
- 存储层：PostgreSQL + pgvector / MinIO / Redis
底部用箭头展示文档状态机：uploaded → parsed → extracted → embedding → reviewed → published

第 4 页 — 阶段 1：文件上传与存储：
左侧：支持格式（PDF/DOCX/MD/TXT）、最大 100MB、文件名安全过滤
中间：SHA-256 去重流程图 — 同文件同空间复用 / 同文件不同空间新建
右侧：MinIO 对象存储，键格式 files/{id}/{name}
底部代码：POST /api/files/upload → sanitize → dedup → MinIO → EventBus

第 5 页 — 阶段 2：事件驱动调度：
左侧：FastAPI startup 注册 2 个 RabbitMQ 订阅
中间：5 个 Celery 队列卡片：knowledge / knowledge.review / tutorial / blueprint.synthesis / low_priority
右侧：超时策略表：ingest 180s / extraction 无限制 / review 600s

第 6 页 — 阶段 3：文档解析与分块：
三列：PDF(PyMuPDF) / DOCX(python-docx) / MD(charset检测)
下方：LangChain RecursiveCharacterTextSplitter → 每页独立分块 → MAX 500 块截断保护
底部：批量 INSERT document_chunks → 状态变为 parsed → 触发 embedding

第 7 页 — 阶段 4：知识提取（三步 LLM 流水线）：
用 3 个步骤卡片展示：
Step 1: 实体识别 (ENTITY_RECOGNITION_PROMPT)
Step 2: 实体分类 (concept/element/flow/case/defense + short_definition)
Step 3: 关系抽取 (prerequisite_of/related_to/part_of/example_of)
下方：跨块去重 + 跨文档去重 + 原子锁机制

第 8 页 — 阶段 5：AI 自动审核：
两轮评审流程图：Round 1 (approve≥0.75/reject/→Round2) → Round 2 (approve≥0.60/reject)
底部：pg_try_advisory_lock 空间级锁 + celery_beat 守护任务

第 9 页 — 阶段 6：向量化：
左侧：嵌入文本构建（canonical_name + short_definition，截断 512 字符）
中间：批量生成 batch_size=32 → pgvector 存储
右侧：完成检测 → 状态变为 reviewed → 触发蓝图合成

第 10 页 — 阶段 7：蓝图生成 V2：
上半部分：K-Means 聚类流程图（N 个实体 → K=max(4,N/7) → 均衡化 → 30 上限）
下半部分：LLM 4 步生成（簇命名 → 阶段规划 → 课程标题 → 章节正文）
右下角：两种模式（全新 vs 增量合并），相似度阈值标注

第 11 页 — 阶段 7 续：课程内容结构：
展示章节输出结构：scene_hook / skim_summary / full_content (600-900字) / code_example / misconception_block / prereq_adaptive

第 12 页 — 阶段 8：测验预生成：
流程：关联实体 → QUIZ_GENERATION_PROMPT → chapter_quizzes 表
学生端：随机抽题 → ≥60% 自动标记已读

第 13 页 — 阶段 9：学生学习与交互：
三列三种阅读模式：速览 / 正常 / 深度
下方功能列表：章节测验 / AI 反思 / 社交笔记 / 源文档追溯 / 证书下载

第 14 页 — 阶段 10：教师精调 + 三层方案：
Layer 1 (上传时约束) → Layer 2 ("精调本章"自然语言) → Layer 3 (测验讨论联动)
鉴权：require_space_owner() — 仅课程所有者

第 15 页 — 技术栈汇总：
6 列技术分类：前端 / API / 任务 / AI / 数据 / 存储
下方指标：27 迁移 · 144 测试 · 9 服务 · 10 阶段 · 5 队列 · 3 迭代层

第 16 页 — 结束页：
标题：谢谢
副标题：StudyStudio DS · v2.8.0 · 全异步 AI 驱动课程生成系统

重要设计注意事项：
- 所有代码片段使用等宽字体
- 阶段编号使用彩色圆形标记
- 流程图箭头清晰标注方向
- 关键数字（阈值、超时、数量）用强调色突出
- 保持整体深色科技风统一
```

---

## 二、Tome.app 提示词

```
创建一个技术演示文稿，标题 "StudyStudio 课程制作全流程"。

主题：一个全异步 AI 驱动的在线课程自动生成系统，从文件上传到学生学习的 10 阶段流水线。

请按以下叙事线索组织内容：

开篇：系统定位
- StudyStudio 是一个基于 AI 的教学内容自动生成平台
- 核心能力：用户上传学习材料 → AI 自动生成结构化在线课程
- 技术特点：全异步、事件驱动、向量聚类、10 阶段自动化

第一部分：技术架构（2 页）
- 5 层架构：前端(Vue3) → API(FastAPI) → 消息队列(RabbitMQ) → Worker(Celery) → 存储(PostgreSQL+MinIO+Redis)
- 文档状态机：uploaded→parsed→extracted→embedding→reviewed→published

第二部分：核心流程（7 页，每页一个关键阶段）
1. 上传 & 去重：SHA-256、MinIO 存储
2. 解析 & 分块：PyMuPDF、LangChain Splitter
3. 知识提取：三步 LLM 流水线（识别→分类→关系）
4. 自动审核：两轮 AI 评审
5. 向量化 & 聚类：K-Means 章节分组
6. LLM 课程生成：结构化内容（场景导入 + 正文 + 代码示例 + 误区）
7. 测验自动生成

第三部分：用户体验（2 页）
- 学生端：三种阅读模式、测验、AI 反思、社交笔记
- 教师端：Layer 1 生成前约束 + Layer 2 对话式精调 + Layer 3 联动再生

结尾：技术栈与规模指标

视觉偏好：
- 深色背景、科技蓝主题
- 架构图使用流程图/卡片式布局
- 每个阶段配图标/编号
- 代码片段使用等宽字体样式
- 数据指标突出显示
```

---

## 三、Beautiful.ai 提示词

```
主题：StudyStudio — AI 驱动的在线课程自动生成系统技术流程

演示目的：技术架构介绍与流程展示
页数：约 15 页
风格：Professional Dark / Technology

页面结构：

1. Title Slide
   Title: StudyStudio 课程制作全流程
   Subtitle: 从文件上传到学生学习的完整 AI 自动化链路
   Footer: 10 阶段 · 异步事件驱动 · v2.8.0

2. Smart Slide — Numbered List
   Title: 全流程总览
   10 个编号步骤，每个配简短描述

3. Smart Slide — Process Diagram
   Title: 系统架构
   展示 5 层架构的层次关系

4-13. Content Slides（每页一个阶段）
   每页使用图标 + 标题 + 3-4 个要点：
   - 文件上传与去重
   - 事件驱动调度
   - 文档解析与分块
   - 三步知识提取
   - 两轮自动审核
   - 向量化与存储
   - K-Means 聚类 + LLM 课程生成
   - 测验预生成
   - 学生学习体验
   - 教师精调方案

14. Smart Slide — Comparison
   Title: 三种教师迭代方式对比
   Layer 1 (生成前约束) vs Layer 2 (对话式精调) vs Layer 3 (联动再生)

15. Smart Slide — Metrics
   Title: 项目规模
   27 迁移 · 144 测试 · 9 服务 · 10 阶段流水线

16. Thank You Slide
```

---

## 四、讯飞智文 提示词

```
生成一份演示文稿，主题为"StudyStudio 课程制作全流程技术解析"。

【演示对象】技术团队、产品经理、教育科技从业者
【演讲时长】30 分钟
【页数要求】16 页左右

【内容大纲】

一、项目概况（1 页）
- StudyStudio 是什么
- 解决什么痛点：手工制作在线课程耗时费力
- 核心价值：上传材料 → 10 阶段自动化 → 生成结构化课程

二、系统架构（1 页）
- 前端：Vue 3 + TypeScript + Vite
- 后端：FastAPI 异步 Python 框架
- 任务：Celery + RabbitMQ 事件驱动
- AI：LangChain + LLMGateway 多模型网关
- 存储：PostgreSQL(pgvector) + MinIO + Redis

三、文档处理（3 页）
- 第 1 步：上传与去重（SHA-256、MinIO）
- 第 2 步：解析与分块（PyMuPDF、LangChain）
- 第 3 步：知识提取（LLM 三步流水线：实体识别 → 分类 → 关系抽取）

四、AI 质量把关（2 页）
- 两轮自动审核机制（Round 1: confidence≥0.75, Round 2: confidence≥0.60）
- 确保无实体卡在 pending 状态

五、课程生成（3 页）
- K-Means 聚类分组（K = max(4, round(N/7))，上限 30）
- LLM 四步生成：章节命名 → 阶段规划 → 课程标题 → 结构化内容
- 两种模式：全新生成 vs 增量合并

六、学习体验（2 页）
- 学生端：速览/正常/深度三种阅读模式，测验、反思、笔记
- 教师端：Layer 1 生成前约束 + Layer 2 自然语言精调 + Layer 3 联动更新

七、总结（1 页）
- 技术栈与规模指标
- 后续规划

【设计要求】
- 配色：深蓝 + 青色科技风格
- 代码段使用等宽字体
- 架构图使用流程图
- 关键数字突出显示
```

---

## 五、通用短视频脚本提示词（用于 AI 视频生成工具）

> 适用于 HeyGen / Synthesia / 剪映 AI 等

```
为一个技术教程视频生成脚本。视频主题：StudyStudio 课程制作全流程。

视频时长：15-20 分钟
风格：专业技术讲解，配屏幕录制/架构动画
语言：中文

视频结构：
1. 开场（60 秒）— 系统定位与痛点介绍
2. 架构概览（90 秒）— 5 层技术架构展示
3. 文档处理链（5 分钟）— 上传→解析→提取→审核→向量化
4. 课程生成核心（4 分钟）— K-Means 聚类 + LLM 生成
5. 产品体验（3 分钟）— 学生端 + 教师端功能演示
6. 总结（60 秒）— 技术栈与亮点回顾

每个部分需要：
- 对应的画面描述（架构图/流程图特写、代码关键行高亮、界面操作录屏）
- 旁白文案
- 画面切换节点
- 重点标注的数字和概念
```

---

## 使用建议

| 工具 | 推荐度 | 适用场景 |
|------|--------|----------|
| **Gamma** | ★★★★★ | 最佳整体效果，支持深色科技风 |
| **Beautiful.ai** | ★★★★ | 结构清晰，模板专业 |
| **Tome** | ★★★★ | 叙事流畅，适合讲故事 |
| **讯飞智文** | ★★★ | 中文优化好，模板较商务 |
| **Canva** | ★★★ | 手动排版灵活，但需调整 |

建议先用 Gamma 生成初稿，导出 PPTX 后在本地微调。
