# StudyStudio 课程制作全流程 — Markdown 结构大纲

> 可直接导入 Gamma.app / Beautiful.ai / Canva / 讯飞智文 等工具
> 每级标题对应一页幻灯片，`---` 分隔页面

---

## 封面
**StudyStudio 课程制作全流程**
从文件上传到学生学习的完整技术链路

副标题：10 个自动化阶段 · 全异步事件驱动 · AI + 向量聚类合成
版本：v2.8.0 · 2026-04

---

## 总览：10 阶段流水线

| 阶段 | 名称 | 核心动作 |
|------|------|----------|
| 1 | 文件上传 | 格式校验 → SHA-256 去重 → MinIO 存储 |
| 2 | 事件调度 | RabbitMQ 订阅 → ingest 队列分发 |
| 3 | 文档解析 | PyMuPDF/pdfplumber → 分块 + 标准化 |
| 4 | 知识提取 | 三步 LLM 流水线：实体识别→分类→关系抽取 |
| 5 | 自动审核 | 两轮 LLM 评审：approve / reject |
| 6 | 向量化 | Embedding 批量生成 → pgvector 存储 |
| 7 | 蓝图生成 | K-Means 聚类 + LLM 章节内容生成 |
| 8 | 测验预生成 | 每章自动出题 → 写入题库 |
| 9 | 学生学习 | 三种阅读模式 + 测验 + 反思 + 笔记 |
| 10 | 教师精调 | 自然语言指令 → 章节重写 → 联动更新 |

---

## 系统架构全景

### 前端层
- **UploadView.vue** — 文件上传（4 种格式 / 100MB）
- **TutorialView.vue** — 课程学习（3 种阅读模式）
- **API 客户端** — 统一封装

### API 网关层 (FastAPI)
- REST 端点 + WebSocket
- Depends 依赖注入鉴权
- EventBus 事件发布

### 消息队列层 (RabbitMQ)
- `file_uploaded` → `knowledge.ingest.queue`
- `document_parsed` → `knowledge.extraction.queue`
- 蓝图 / 测验 / 讨论事件

### Celery Workers
- **knowledge** 队列 — 解析 + 提取 + 向量化
- **knowledge.review** 队列 — 自动审核
- **blueprint.synthesis** 队列 — 蓝图生成

### 存储层
- **PostgreSQL + pgvector** — 结构化 + 向量检索
- **MinIO** — 对象存储
- **Redis** — 结果 / 缓存

### 文档状态机
```
uploaded → parsed → extracting → extracted → embedding → reviewed → published
```

---

## 阶段 1：文件上传与存储

### 前端入口
- UploadView.vue
- 支持 PDF / DOCX / MD / TXT
- 最大 100MB

### 后端校验
- Content-Type 白名单
- 文件名安全过滤（路径穿越防护）

### SHA-256 去重
- 同文件同空间 → 复用已有记录
- 同文件不同空间 → 创建新文档记录

### MinIO 存储
- 键格式：`files/{file_id}/{safe_filename}`
- AsyncMinIOClient 异步封装（asyncio）

### 事件发布
- `POST /api/files/upload`
- → `EventBus.publish("file_uploaded")`
- → 初始状态：`uploaded`

---

## 阶段 2：事件驱动任务调度

### 订阅注册
- FastAPI `startup` 事件中注册（main.py）
- 2 个核心订阅：
  - `file_uploaded` → `knowledge.ingest.queue` → `run_ingest`
  - `document_parsed` → `knowledge.extraction.queue` → `run_extraction`

### Celery 配置
- Broker: RabbitMQ
- Result Backend: Redis
- 5 个专用队列：`knowledge`, `knowledge.review`, `tutorial`, `blueprint.synthesis`, `low_priority`

### 超时策略
| 任务 | Soft Limit | Hard Limit |
|------|-----------|------------|
| run_ingest | 180s | 240s |
| run_extraction | 无限制 | 无限制 |
| auto_review | 600s | 720s |

---

## 阶段 3：文档解析与文本分块

### 多格式解析引擎
- **PDF**: PyMuPDF (fitz) — 按物理页提取 + TOC 大纲
- **DOCX**: python-docx — 段落级提取
- **MD/TXT**: charset 检测 → 解码

### 文本分块
- LangChain RecursiveCharacterTextSplitter
- 每页独立分块（保留页面边界）
- 元数据：`index_no`, `title_path`, `page_no`, `token_count`

### 截断保护
- `MAX_CHUNK_COUNT = 500`
- 超出标记 `is_truncated`
- 批量 INSERT（50 条/批）→ `document_chunks` 表

### 状态变更
- `parsed` → 发布 `document_parsed` → 触发 chunk embedding

---

## 阶段 4：知识提取 — 三步 LLM 流水线

### Step 1: 实体识别
- Prompt: `ENTITY_RECOGNITION_PROMPT`
- 从文本提取教学实体名称列表

### Step 2: 实体分类
- Prompt: `ENTITY_CLASSIFICATION_PROMPT`
- 5 种类别：`concept / element / flow / case / defense`
- 附加 `short_definition`

### Step 3: 关系抽取
- Prompt: `RELATION_EXTRACTION_PROMPT`
- 4 种关系类型：`prerequisite_of / related_to / part_of / example_of`
- 仅对 2+ 新实体的 chunk 执行

### 去重策略
- 跨块去重：按 `entity_name` 合并
- 跨文档去重：同 `canonical_name` + 同 `domain_tag` 跳过

### 原子锁
```sql
UPDATE documents SET document_status = 'extracting'
WHERE ... NOT IN ('extracting', 'extracted', ...)
RETURNING document_id::text
```

### 完成动作
- 状态 → `extracted`
- 派发 `auto_review_entities`（countdown=5s）

---

## 阶段 5：AI 自动审核 — 两轮质量把关

### Round 1 评审
- LLM 逐实体评审
- 输出：`approve / reject / uncertain` + confidence

### 裁决规则
- `approve` + confidence ≥ 0.75 → **approved**
- `reject` → **rejected**
- 其余 → **Round 2**

### Round 2 评审
- 更严格的二次审核
- `approve` + confidence ≥ 0.60 → **approved**
- 其余 → **rejected**

### 并发安全
- PostgreSQL `pg_try_advisory_lock()` 空间级锁
- 每批 5 个实体

### 守护任务
- `resume_pending_review` 每 5 分钟 celery_beat 执行
- 抢救卡住的审核

### 完成动作
- 文档状态 → `embedding`
- 触发向量化任务

---

## 阶段 6：向量化 — Embedding 生成

### 嵌入文本构建
- `canonical_name + " — " + short_definition`
- 截断 512 字符

### 批量生成
- `backfill_entity_embeddings` 任务
- batch_size = 32
- `LLMGateway.embed()` 调用

### 存储格式
- PostgreSQL `vector` 类型
- pgvector 扩展索引加速

### Chunk 向量（并行）
- `embed_document_chunks` 任务
- 用于原文相似度搜索

### 完成检测
- `_trigger_blueprint_if_ready()` 检查是否所有实体已完成
- 状态 → `reviewed`
- 派发 `synthesize_blueprint`

---

## 阶段 7：蓝图/课程生成 — V2 合成引擎

### Phase 1: 过滤 + 聚类
1. 读取空间所有 approved 实体 + embedding
2. 过滤非教学实体（CVE / 版本号 / 厂商 / 漏洞描述）
3. K-Means 聚类：`K = max(4, round(N/7))`，上限 30
4. 均衡化：合并 < 3 实体的簇，拆分 > 12 实体的簇

### Phase 2: LLM 多步生成
1. **簇命名** (`CLUSTER_CHAPTER_PROMPT`) — 标题 + 目标 + 任务描述 + 通过标准 + 常见误区
2. **阶段规划** (`STAGE_PLANNING_PROMPT`) — 基础 → 实践 → 评估，动词多样化
3. **课程标题** (`COURSE_TITLE_PROMPT`)
4. **章节正文** (`CHAPTER_CONTENT_PROMPT`) — 600-900 字，结构化输出

### 两种模式

| 模式 | 场景 | 特点 |
|------|------|------|
| A: 全新生成 | 首次创建课程 | K-Means 从头聚类 + 生成 |
| B: 增量合并 | 追加文档 | 余弦相似度差异分析，>0.92 跳过，<0.75 新章 |

### 输出内容结构
- `scene_hook` — 场景导入
- `skim_summary` — 速览要点
- `full_content` — 正文（含 CHECKPOINT 断点）
- `code_example` — 代码示例
- `misconception_block` — 常见误区

### 完成动作
- 状态 → `published`
- 派发 `pregen_chapter_quizzes`

---

## 阶段 8：测验预生成

- 每章读取关联 `core_term` 实体
- 调用 `QUIZ_GENERATION_PROMPT`
- 写入 `chapter_quizzes` 表
- 学生端随机抽题，≥60% 自动标记已读

---

## 阶段 9：学生学习与交互

### 三种阅读模式
| 模式 | 内容 |
|------|------|
| **速览** (skim) | `skim_summary` 要点 |
| **正常** (normal) | 完整正文 + CHECKPOINT 断点 |
| **深度** (deep) | 正文 + `prereq_adaptive` 扩展 |

### 交互功能
- **章节测验** — 随机抽题，≥60% 标记已读
- **AI 反思** — 学生写理解总结，LLM 评分反馈
- **社交笔记** — 每章独立笔记区，点赞互动
- **源文档追溯** — 查看影响本章的原始文档片段

### 其他功能
- 关联推荐
- 证书下载（全部已读后）
- 蓝图更新订阅通知

---

## 阶段 10：教师精调（Layer 2+3）

### Layer 2: 对话式章节精调
- **入口**：TutorialView 章节标题旁 "✨ 精调本章" 按钮
- **交互**：`ElMessageBox.prompt` textarea，输入自然语言指令
- **API**：`POST /admin/courses/chapters/{id}/refine`
- **鉴权**：`get_current_user` + `require_space_owner()`（仅课程所有者）
- **LLM 调用**：`tutorial_content` route，150s timeout

### Layer 3: 附属内容联动
1. 测验缓存自动失效
2. `regenerate_chapter_quiz` 重新生成题目
3. `generate_discussion_seeds` 可选讨论种子更新

### Layer 1: 生成前约束
- 上传时输入全局教学约束
- 注入所有 LLM Prompt
- 控制风格 / 难度 / 受众

---

## 三层教师迭代方案汇总

```
Layer 1（生成前）    Layer 2（生成后）      Layer 3（联动）
全局教学约束    →    自然语言精调    →    测验/讨论自动更新
上传时输入          "✨ 精调本章"按钮      缓存失效 + 重新生成
注入所有 Prompt      保留版本历史           全自动
```

---

## 技术栈一览

| 层级 | 技术 |
|------|------|
| 前端 | Vue 3 + TS, Vite, Element Plus, Pinia |
| API | FastAPI, Pydantic v2, Uvicorn, WebSocket |
| 任务 | Celery, RabbitMQ, Redis, EventBus |
| AI | LangChain, LLMGateway, PyMuPDF, python-docx |
| 数据 | PostgreSQL + pgvector, SQLAlchemy 2.0, Alembic |
| 存储 | MinIO (S3), boto3 |

## 项目规模
- 27 个数据库迁移
- 144 个测试用例（0 失败）
- 9 个 Docker 服务
- 10 个流水线阶段
- 5 个 Celery 队列

---

## 谢谢

StudyStudio DS · v2.8.0 · 全异步 AI 驱动课程生成系统

devdocs/course_creation_flow/ — PPT · Markdown · AI 提示词 · 视频脚本
