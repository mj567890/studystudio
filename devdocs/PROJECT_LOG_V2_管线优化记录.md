# 项目开发日志 V2 — 文档到课程全自动管线优化

**项目：自适应学习平台 v1.0.0**
**周期：2026-04-25 ~ 2026-04-26**
**目标：使 6 阶段文档处理管线（上传→解析→提取→审核→嵌入→蓝图）全自动可靠运行，并实现课程工厂多文档增量融合**
**状态：全计划完成（Phase 5-9）**

---

## 阶段 0：致命缺陷修复（管线可靠运行的前提）

### 0.1 修复 LLM 异常捕获遗漏

**文件**：`apps/api/core/llm_gateway.py`

**问题**：`APIConnectionError`/`APITimeoutError` 继承自 `OpenAIError` 而非 `APIError`，当前只捕获 `APIError`，导致连接/超时错误直接穿透到上层，引发未处理异常。

**修复**：
- import 增加 `APIConnectionError, APITimeoutError`
- `except APIError` → `except (APIError, APIConnectionError, APITimeoutError)`

### 0.2 消除事件双重发布

**文件**：`apps/api/tasks/knowledge_tasks.py`

**问题**：`ingest_service.py:190` 已发布 `document_parsed` 事件（含 3 次重连重试），`knowledge_tasks.py:142` 再次发布导致下游收到 2 次事件，触发多个并行的 `run_extraction` worker。

**修复**：删除 `_run_ingest_async` 末尾的兜底 `document_parsed` 发布逻辑（第 130–151 行）。

### 0.3 启用事件幂等保护

**文件**：`apps/api/main.py`

**问题**：`subscribe()` 调用均缺少 `db_session_factory` 参数，导致 `events.py:103` 的幂等检查分支完全跳过，`event_idempotency` 表空转。

**修复**：4 处 `subscribe()` 调用均增加 `db_session_factory=async_session_factory` 参数。

### 0.4 增加文档级提取锁（防并行竞态）

**文件**：`apps/api/tasks/knowledge_tasks.py`

**问题**：同一文档被多个并行 worker 同时处理（无锁保护）。

**修复**：在 `_run_extraction_async` 中插入原子 UPDATE 锁：
```sql
UPDATE documents SET document_status = 'extracting', updated_at = NOW()
WHERE document_id = :doc_id
  AND document_status NOT IN ('extracted','embedding','reviewed','published','extracting')
RETURNING document_id
```
若 `rowcount == 0` 则跳过。失败时从 `extracting` 回退到 `failed`。

### 0.5 修复 TaskTracker 写入 DB

**文件**：`apps/api/tasks/task_tracker.py`

**问题**：`task_executions` 表完全为空，`on_failure`/`on_success` 回调未能写入。

**修复**：`_make_session()` 及相关方法中的 `create_async_engine` 增加 `connect_args={"timeout": 5}`，确保在 Celery prefork 子进程事件循环中可用。

### 0.6 补全 idempotency 检查的状态列表

**文件**：`apps/api/tasks/knowledge_tasks.py`

**问题**：跳过条件遗漏 `'extracting'`（0.4 新增状态）和 `'failed'`，导致失败文档被重复拉入提取。

**修复**：跳过条件改为 `doc_status in ('extracting', 'extracted', 'embedding', 'reviewed', 'published')`。

---

## 阶段 1：严重问题修复

### 1.1 ingest_from_file_event 提交保护

**文件**：`apps/api/modules/knowledge/ingest_service.py`

**问题**：`flush()` 不 commit，若 `ingest()` 抛异常则 document 记录丢失。

**修复**：`flush()` → `commit()`，try/except 包裹 `ingest()` 调用，失败时标记 document 为 `failed`。

### 1.2 LLM 恢复后自动重试机制

**文件**：`apps/api/tasks/auto_review_tasks.py`

**问题**：LLM 服务恢复后，之前因 LLM 连接问题标记为 `failed` 的文档不会自动重试，需要人工介入。

**修复**：`resume_pending_review` 增加 Phase 5：查询最近 1 小时内因 LLM 连接问题标记为 `failed` 的文档，若 provider 已恢复则重置为 `parsed` 并重新触发 `run_extraction`。

### 1.3 审核后批量 embedding 派发

**文件**：`apps/api/tasks/auto_review_tasks.py`

**问题**：审核通过 100 个实体 = 100 条逐条 `embed_single_entity` Celery 消息。

**修复**：改为批量 `backfill_entity_embeddings.apply_async(args=[space_id, 32])`，失败时降级为逐条派发。

---

## 阶段 2：自动化增强

### 2.1 文档管线进度 API

**文件**：`apps/api/modules/knowledge/file_router.py`

**改动**：新增 `GET /api/files/documents/my-details`，返回用户所有文档的管线进度（阶段标签、百分比、ETA 预估、错误信息、已审核/待审核知识点数）。

### 2.2 前端文档进度可视化

**文件**：`apps/web/src/views/learner/UploadView.vue`

**改动**：在"我的文档"列表中每条文档增加进度条 + 阶段标签 + ETA 预估 + 失败时的错误详情和重试按钮。

### 2.3 管理面板告警聚合

**文件**：
- `apps/api/modules/admin/system_health.py`
- `apps/web/src/views/admin/SystemHealthView.vue`

**改动**：`get_system_health()` 返回体增加 `alerts` 字段（critical/warnings 分级），前端增加告警横条 + 一键修复按钮。复用已有 `_get_pipeline_summary()` 检测逻辑和 `_diagnose_stuck()` 中文诊断。

---

## 阶段 3：用户参与

### 3.1 用户通知系统

**文件**：
- `migrations/019_user_notifications.sql`（新建 `user_notifications` 表）
- `apps/api/modules/knowledge/notification_router.py`（新建）

**改动**：
- 创建 `user_notifications` 表（id, user_id, type, title, message, target_type, target_id, is_read, created_at）
- 在关键管线节点（提取完成/失败、蓝图发布）插入通知
- API 端点：`GET /api/notifications`、`POST /{id}/read`、`POST /read-all`
- 独立 engine（兼容 Celery prefork 模式）

### 3.2 前端通知铃铛

**文件**：
- `apps/web/src/components/NotificationBell.vue`（新建）
- `apps/web/src/views/LayoutView.vue`（修改引入）

**改动**：导航栏右侧增加 Bell 图标 + 未读 badge，30 秒轮询 `/api/notifications`，下拉展示最近通知，点击跳转到对应资源。

---

## 阶段 4：端到端验证与问题修复

### 4.1 课程代码格式修复

**文件**：
- `apps/api/tasks/blueprint_tasks.py`

**问题**：LLM 生成课程时输出裸代码（无 code fence）、raw `⏸` 字符、无语言标识。

**修复**：
- **重写 `CHAPTER_CONTENT_PROMPT`**：从 HTML `<pre><code>` 改为 markdown ```fences```，增加语言标识要求，添加负面示例列表，禁止 raw `⏸`
- **新增 `_normalize_chapter_content()` 函数**（~160 行）：
  - 清理 raw `⏸` 字符
  - ```fences``` → `<pre><code class="language-xxx">`（正则转换）
  - 自动检测语言：Python (def/import/class)、SQL (SELECT/INSERT)、bash (apt/docker/curl)、JS (function/const/=>)、Java (public class/@Bean)、XML (<?xml/<context-param)
  - 容忍 JSON 外围的非 JSON 文本
  - 对所有字符串字段应用标准化（full_content、code_example、scene_hook、misconception_block、skim_summary）
- **3 处存储点均应用 normalize**（V1 line 820、V2 line 1094、V2 line 1371）

**文件**：`apps/web/src/views/tutorial/TutorialView.vue`

**修复**：重写 `renderTerms()` 函数——保护 `<pre>` 块不被 `\n→<br>` 破坏。先将 `<pre>` 块替换为占位符 → `\n→<br>` + hotwords 高亮 → 还原 `<pre>` 块。

### 4.2 Tutorial 500 错误修复

**文件**：`apps/api/modules/routers.py`

**问题**：`chapter_progress` 表没有 `status` 列，SQL 查询引用了不存在的列导致 500。

**修复**：移除 SELECT 中的 `status`，改为从 `completed` boolean 计算。

### 4.3 Admin 返回学习端导航修复

**文件**：`apps/web/src/views/AdminLayoutView.vue`

**问题**：管理后台点"返回学习端`"使用 `el-menu` 的 `router` 属性跳转 `/`，但 admin 角色无学习端路由权限。

**修复**：为"返回学习端"菜单项增加显式 `@click="router.push('/')"`。

### 4.4 404 after rebuild 修复

**问题**：每次 `docker compose build web` 后浏览器所有页面 404。

**根因分析（2 个）**：
1. **nginx 无缓存控制**：浏览器缓存旧 `index.html`，引用旧 hash 的 JS/CSS 文件（已不存在）
2. **notification_router 前缀缺失**：`/notifications` 缺少 `/api/` 前缀，nginx 不代理非 `/api/` 路径

**修复**：
- **`apps/web/nginx.conf`**：完整重写——`index.html` 设置 `Cache-Control: no-store`，`/assets/` 设置 `immutable` 长期缓存，SPA fallback `try_files $uri /index.html`
- **`apps/api/modules/knowledge/notification_router.py`**：router prefix `/notifications` → `/api/notifications`

### 4.5 Web 构建错误修复

**文件**：
- `apps/web/src/components/NotificationBell.vue`
- `apps/web/src/api/index.ts`

**问题**：`NotificationBell.vue` 导入了不存在的 `@/api/client`。

**修复**：改为 `import { http } from '@/api'`，在 `api/index.ts` 中导出 `http` 实例。

### 4.6 reviewed→published 文档状态回写缺失

**文件**：`apps/api/tasks/blueprint_tasks.py`

**问题**：文档管线 6 阶段中，`reviewed → published` 转换代码完全缺失。蓝图发布后文档永远停在 `reviewed`（83%）。

**根因**：两处蓝图发布（V1 line 887、V2 line 1182）仅调用 `update_blueprint_status(blueprint_id, "published")`，未更新文档状态。

**修复**：
- V1/V2 两处蓝图书写完成后，均新增：
  ```sql
  UPDATE documents SET document_status = 'published', updated_at = now()
  WHERE space_id = :sid AND document_status = 'reviewed'
  ```
- V1 完成日志从 quiz pregen 的 `except` 块内移到外部 + 修正 `status=review` → `status=published`

### 4.8 JSON 解析降级路径修复

**文件**：`apps/api/tasks/blueprint_tasks.py`

**问题**：`_normalize_chapter_content` 在 `json.loads` 失败时调用 `_text_only_cleanup`，该函数对**整个原始 JSON 文本**（含 `{`, `"scene_hook"`, `"full_content"` 等结构字符）做清理，导致 JSON 包装结构泄露到前端渲染输出。触发条件：课程内容中 bash/SQL 代码含未转义双引号（如 `"http://target.com/..."`）。

**修复**：重写 `_text_only_cleanup`，改为智能提取模式：
1. 定位 `"full_content"` 键 → 找到值的起始引号
2. 逐字符扫描，跟踪 `\` 转义，定位匹配的闭合引号
3. 仅提取值内容，反转义 `\n`/`\"`/`\\`，转换围栏
4. JSON 包装结构完全丢弃

### 4.9 单章重生成缺少内容标准化

**文件**：`apps/api/modules/admin/router.py`

**问题**：`POST /admin/courses/chapters/{chapter_id}/regenerate` 直接存储 LLM 原始输出 `content.strip()`，未经过 `_normalize_chapter_content` 处理。全量重生成 `regenerate_all_chapters` 却正确调用了标准化。

**修复**：单章重生成路径补上 `_normalize_chapter_content()` 调用。

### 4.10 课程学习页刷新丢失章节位置

**文件**：`apps/web/src/views/tutorial/TutorialView.vue`

**问题**：`selectChapter()` 不持久化当前章节。`last_chapter_id` 仅在跳转到 Chat 前保存，且 `loadTutorial()` 恢复后会立即删除。刷新页面始终回到第一章。

**修复**：
- `selectChapter()` 新增 `localStorage.setItem("last_chapter:{topic}", chapter_id)`，每次选章即保存
- `loadTutorial()` 恢复逻辑改为：优先 `last_chapter_id`（Chat 跳转一次性）→ 降级 `last_chapter:{topic}`（刷新持久化）
- 不同主题独立存储，互不干扰

### 4.7 管理员全量文档面板

**后端文件**：`apps/api/modules/admin/router.py`

**改动**：`GET /api/files/all-documents` 增强为：
- 查询参数：`status`、`space_type`、`page`、`page_size`、`sort_by`、`sort_order`
- 返回字段：文档标题、管线状态、进度百分比、停留时长、空间信息、owner 信息、文件名/类型/大小、chunk 数、已审核/已嵌入知识点数、错误摘要、时间戳
- 分页元数据：`total`、`page`、`page_size`、`total_pages`
- 排序列白名单校验

**前端文件**：
- `apps/web/src/api/index.ts`：`getAllDocuments` 增加参数支持
- `apps/web/src/views/admin/SystemHealthView.vue`：新增「全部文档」Tab
  - 状态/空间类型/排序过滤栏
  - 表格列：文档标题、所属用户、管线进度条、空间、知识点数、停留/错误、更新时间、操作按钮
  - 分页控制
  - 重试/重新解析操作按钮

---

## 阶段 5：质量底线（P0 — 无证据拒答 + 查询改写 + 裸代码检测 + 来源标注）

### 5.1 无证据拒答护栏

**文件**：`apps/api/modules/teaching/teaching_service.py`、`apps/api/core/llm_gateway.py`

**问题**：RAG 检索结果为空或 RRF 得分极低时，LLM 仍会编造答案（幻觉）。

**修复**：
- 检索结果为空（`retrieved` 空列表）时直接返回模板回答，`confidence=0`，不调用 LLM
- RRF norm_score < 0.3 时，在 system prompt 追加低证据约束指令，要求明确说「当前课程资料中未覆盖此问题」
- 返回体增加 `cited_sources`：`[{entity_name, short_definition_preview}]`

### 5.2 轻量查询改写

**文件**：`apps/api/modules/teaching/teaching_service.py`

**问题**：用户输入口语化模糊问题（如"那个注入怎么防的"），BM25 和向量检索均无法匹配。

**修复**：
- 新增 `_rewrite_query()` 方法：用 LLM 将问题改写为 2-3 个检索关键词短语（分号分隔）
- 每个改写短语独立检索，结果经 RRF 去重融合
- 总超时 2s，LLM 不可用时降级为原始 query

### 5.3 激活裸代码检测死代码

**文件**：`apps/api/tasks/blueprint_tasks.py`

**问题**：`_normalize_code_blocks()` 中裸代码检测的正则模式已定义（`_is_code_line`、`_wrap_bare_code`），但函数在第 251 行有 `return text` 早退，检测逻辑从未执行。

**修复**：
- 删除早退的 `return text`
- 实现完整检测流程：对疑似代码的连续行自动包裹 `<pre><code class="language-xxx">`
- SQL 关键字扩展：增加 PREPARE、TRUNCATE、MERGE、REPLACE、UPSERT、DEALLOCATE
- 增加 `<pre>` 标签检测防双重包裹
- 检测到裸代码时记录 warning 日志

### 5.4 答案来源标注

**文件**：`apps/api/modules/teaching/teaching_service.py`

**修复**：
- chat_and_prepare 构造 system prompt 时追加「## 来源标注要求」：回答中引用知识点时用【知识点名称】格式标注来源
- 后端返回 `cited_sources` 字段：`[{entity_name, short_definition_preview}]`（已有）

### 5.5 Celery fork 后 EventBus event loop 修复

**文件**：
- `apps/api/core/events.py` — 新增 `reset()` 方法
- `apps/api/modules/knowledge/ingest_service.py` — `document_parsed` 发布前强制 `reset()`

**问题**：Celery prefork 后子进程复用父进程的 EventBus 单例，底层 `aio_pika` 连接的 asyncio.Event 绑定到父进程的 event loop，导致 `document_parsed` 事件发布在子进程中失败（C5 测试中发现）。

**修复**：
- `EventBus.reset()`：强制关闭旧连接 → 清空 _connection/_channel/_exchange → 新 connect() 在子进程 event loop 中建立全新连接
- `ingest_service.py` 发布前：`await event_bus.reset()` → `await event_bus.connect()` → `await event_bus.publish()`
- 每 attempt 均先 `connect()` 再 `publish()`，不再依赖 `_connection.is_closed` 判断（fork 后不可靠）

---

## 阶段 6：内容感知增强（P1 — 页面分块 + chunk 检索 + 路径分层）

### 6.1 页面级分块 + title_path 填充

**文件**：`apps/api/modules/knowledge/ingest_service.py`

**问题**：`_extract_pages()` 已实现但从未被 `ingest()` 调用，始终用 `_extract_text()` 压平全文再切 chunk，`page_no` 和 `title_path` 始终为空。

**修复**：
- `ingest()` 切换为 `_extract_pages()`：PDF 用 `fitz` 按页提取文本，每页独立切 chunk，记录 `page_no`
- 新增 `_extract_outline()`：用 `fitz.get_toc()` 提取 PDF 大纲/TOC
- 新增 `_build_title_path()`：优先使用 PDF 大纲构建层级标题路径，无大纲时正则检测标题行（第X章/Chapter N/数字编号）
- 截断前记录原始分块数 `original_chunk_count`

### 6.2 RAG 增加 chunk 检索通道

**文件**：`apps/api/modules/teaching/teaching_service.py`

**问题**：检索仅覆盖 `knowledge_entities` 表（术语级别），文档原文段落不可检索。

**修复**：
- 新增 `_chunk_bm25()` 方法：对 `document_chunks` 表做 PostgreSQL 全文检索（`ts_rank` + `plainto_tsquery`）
- 新增 `_chunk_vector()` 方法：对 `document_chunks` 做向量检索（复用 chunk embedding）
- `retrieve()` 改为 4 通道并行检索（实体 BM25 + 实体向量 + chunk BM25 + chunk 向量），RRF 融合
- `RankedKnowledgeItem` 扩展 `source_type`、`page_no`、`title_path` 字段

### 6.3 学习路径初学者/进阶分层

**文件**：`apps/api/modules/learner/learner_service.py`

**修复**：
- `_compute_chapter_path()` 对每个章节计算 `priority`：`gap_score > 0.8` → `foundation`（必修），`gap_score < 0.3` → `enrichment`（拓展），其余 → `standard`
- `estimated_minutes` 改为基于 `content_text` 正文长度动态计算（100 字 ≈ 1 分钟），不再硬编码 30
- 返回体增加 `priority` 和 `estimated_minutes` 字段

---

## 阶段 7：多文档融合（课程工厂核心 — P1）

### 问题背景

`_check_blueprint_lock` 对 `published` 状态蓝图直接拒绝。新文档实体通过审核→嵌入后，`_trigger_blueprint_if_ready` 触发 `synthesize_blueprint`，锁检查发现已 published，返回 False。**新知识点永远无法进入已有课程。**

### 整体融合流程

```
新文档完成嵌入 → _trigger_blueprint_if_ready
                     ↓
            synthesize_blueprint 入口
                     ↓
        _has_published_blueprint?
         ├─ 无 → 原有全量生成（V1/V2）
         └─ 有 → _check_blueprint_lock(mode="merge")
                     ↓
        _synthesize_blueprint_merge_async
                     ↓
            _diff_new_entities()
                     ↓
      ┌──────┼──────┼──────┐
already_covered  supplement  new_topic
    (跳过)     → 增强章节  → 插入新章节
```

### 7.1 实体差异分析

**文件**：`apps/api/tasks/blueprint_tasks.py` — 新增 `_diff_new_entities()`

**实现**：
- 查询已有章节链接的实体（含 embedding）+ 新近审核通过的实体（`created_at > blueprint.updated_at`）
- 用 embedding 余弦相似度做比对（复用已生成的 embedding，无需新 LLM 调用）
- 分类逻辑：
  - `already_covered`：相似度 > 0.92 → 跳过
  - `supplement`：0.75 ~ 0.92 → 追加到对应章节
  - `new_topic`：< 0.75 且无匹配章节 → 后续生成新章节
  - `conflict`：> 0.85 但定义文本有矛盾 → 暂跳过（预留人工审核）

### 7.2 章节增量增强

**文件**：`apps/api/tasks/blueprint_tasks.py` — 新增 `_enhance_existing_chapters()`

**实现**：
- 对每个 supplement 实体，通过 embedding 相似度找到最匹配的已有章节
- 用 LLM 读取章节当前内容 + 新实体定义，生成"补充说明"段落
- 追加到 `full_content` 末尾（不删除、不替换原内容）
- 链接新实体到章节（`link_type = "supplement"`）

### 7.3 新章节插入

**文件**：`apps/api/tasks/blueprint_tasks.py` — 新增 `_insert_new_chapters()`

**实现**：
- 对 new_topic 实体聚类（pairwise 相似度 > 0.7，≥3 个形成主题）
- 每组调用已有 `_normalize_chapter_content` 生成新章节
- 新章节插入到已有最后一个阶段末尾，`chapter_order` 重新排序
- 发布 `blueprint_merged` 事件通知课程更新

### 7.4 merge 模式开关

**文件**：
- `apps/api/tasks/blueprint_tasks.py` — `_check_blueprint_lock()` 新增 `mode` 参数
- `apps/api/tasks/blueprint_tasks.py` — 新增 `_has_published_blueprint()`、`_synthesize_blueprint_merge_async()`
- `apps/api/tasks/blueprint_tasks.py` — `synthesize_blueprint` 入口改造：优先检测 published 蓝图 → merge 分支

**实现**：
- `_check_blueprint_lock(mode="merge")`：WHERE 子句移除 `'published'` 限制，允许对已发布蓝图获取锁
- `_check_blueprint_lock(mode="full")`：保持原行为（阻拦 generating + published）
- `synthesize_blueprint` 入口：先调用 `_has_published_blueprint()` → 有则走 merge，无则走 full
- merge 完成后：blueprint version+1，状态回 `published`，预生成新章节测验题
- 若无新实体（diff 为空）：直接恢复 published 状态，零副作用

---

## C1/C2 验证结果

| 检查点 | 内容 | 结果 |
|--------|------|------|
| C1 基线 | 文档/蓝图/章节数据完整 | ✅ 1 文档、1 蓝图、3 章节 |
| C2 课程 API | 课程接口可访问、章节有内容 | ✅ 200、3 章节 (1569/1571/929 chars) |
| C2 管理员 | 全量文档 API 返回丰富数据 | ✅ 含 owner/space/progress/entities/error |

---

## 关键文件改动汇总

| 文件 | 改动类型 | 所属阶段 |
|------|---------|---------|
| `apps/api/core/llm_gateway.py` | 异常类型扩展 + teach prompt 来源标注 | 0.1 / 5.4 |
| `apps/api/tasks/knowledge_tasks.py` | 删除双重发布 + 提取锁 + 状态列表 | 0.2/0.4/0.6 |
| `apps/api/main.py` | db_session_factory + blueprint_merged 事件订阅 | 0.3 / 9.4 |
| `apps/api/tasks/task_tracker.py` | engine connect_args | 0.5 |
| `apps/api/modules/knowledge/ingest_service.py` | flush→commit + 异常保护 + 页面级分块 + title_path + event loop 修复 | 1.1 / 6.1 / 5.5 |
| `apps/api/core/events.py` | EventBus reset() 方法（Celery fork 修复） | 5.5 |
| `apps/api/tasks/auto_review_tasks.py` | LLM 恢复重试 + 批量 embedding | 1.2/1.3 |
| `apps/api/modules/knowledge/file_router.py` | 文档进度 API | 2.1 |
| `apps/api/modules/admin/system_health.py` | 告警聚合 | 2.3 |
| `apps/api/modules/admin/router.py` | 全量文档 API + 单章重生成标准化 | 4.7/4.9 |
| `apps/api/modules/knowledge/notification_router.py` | 新建通知系统 + dismiss 端点 | 3.1 / 9.4 |
| `apps/api/modules/routers.py` | chapter_progress SQL 修复 + quiz mastery 闭环 | 4.2 / 9.1 |
| `apps/api/modules/teaching/teaching_service.py` | 拒答护栏 + 查询改写 + chunk 检索通道 + 来源标注 | 5.1/5.2/6.2/5.4 |
| `apps/api/modules/learner/learner_service.py` | 学习路径分层 | 6.3 |
| `apps/api/modules/learner/eight_dim_endpoints.py` | dashboard 端点 + 笔记实体关联 | 9.2/9.3 |
| `apps/api/modules/skill_blueprint/repository.py` | merge 模式 + 字段拆分写入/读取 | 7.4/8.1 |
| `apps/api/tasks/blueprint_tasks.py` | 课程格式 + 文档回写 + 裸代码检测 + JSON 降级 + 多文档融合 + 结构化字段 | 4.1/4.6/5.3/4.8/7.1-7.4/8.1 |
| `apps/web/src/views/learner/UploadView.vue` | 进度可视化 | 2.2 |
| `apps/web/src/views/admin/SystemHealthView.vue` | 告警展示 + 全量文档 Tab | 2.3/4.7 |
| `apps/web/src/views/admin/AdminLayoutView.vue` | 返回导航修复 | 4.3 |
| `apps/web/src/views/tutorial/TutorialView.vue` | renderTerms 重写 + JSON fallback + 章节持久化 + 结构化字段 + quiz mastery | 4.1/5.4/4.10/8.1/9.1 |
| `apps/web/src/views/tutorial/ChatView.vue` | renderMd 来源标注高亮 | 5.4 |
| `apps/web/src/views/HomeView.vue` | 学习仪表板（继续学习+薄弱章节+进度条+最近记录） | 9.3 |
| `apps/web/src/views/learner/NotesView.vue` | 笔记实体标签 + 过滤 + 弹窗 | 9.2 |
| `apps/web/src/components/NotificationBell.vue` | 通知铃铛 + merge 通知 UI | 3.2 / 9.4 |
| `apps/web/nginx.conf` | 缓存控制重写 | 4.4 |
| `apps/web/src/api/index.ts` | 新增 API 函数 + 导出 http | 3.2/4.5/4.7/9.2/9.3 |
| `migrations/019_user_notifications.sql` | 新建通知表 | 3.1 |
| `migrations/020_note_entity_links.sql` | 新建笔记实体关联表 | 9.2 |
| `migrations/021_chapter_content_columns.sql` | 章节内容字段拆分 | 8.1 |

---

## C3/C4/C5 验证结果（2026-04-26）

### C3 全管线验证 ✅

新文档 `c3_test_xss.pdf`（XSS 防御相关）全程自动通过 7 个阶段：

| 阶段 | 状态 |
|------|------|
| upload | ✅ 通过 |
| parse（页面分块 + 大纲提取） | ✅ 通过 |
| extract（实体提取） | ✅ 通过 |
| review（AI 审核） | ✅ 通过 |
| embed（向量生成） | ✅ 通过 |
| synthesize（蓝图生成） | ✅ 通过 |
| publish | ✅ 通过 |

**产出**：蓝图 `C3-XSS-Test` v3，「Web应用安全防护与漏洞防御」，3 阶段 12 章节

### C4 PDF 大纲/页面分块验证 ✅

使用带 PDF 大纲（TOC）的 `c4_csrf_test.pdf` 验证 page_no 和 title_path 填充：

- `page_no`：正确填充（1-5 页，与物理页码一致）
- `title_path`：通过 PyMuPDF `get_toc()` 正确提取层级标题（如 `["Chapter 1: CSRF Attack Fundamentals"]`）
- 整条管线（upload→parse→extract→review→embed→blueprint→publish）全部自动完成

**产出**：蓝图 `C4-CSRF-Test` v2，「CSRF防御与安全会话管理」，1 阶段 5 章节

### C5 多文档增量融合验证 ✅

在两阶段测试中完整验证了增量 merge 路径：

**阶段 1**（首次全量生成）：上传 2 本 NoSQL 相关 PDF 到新空间 → 全量 V2 生成 8 章课程

**阶段 2**（增量 merge 重测）：上传第 3 本 PDF（Redis/CouchDB/WAF 注入防御）到同一空间：
- `_has_published_blueprint` 检测到已发布蓝图 → 走 merge 分支
- `_diff_new_entities`：existing=57, new=35 → already_covered=1, supplement=33, new_topic=1, conflict=0
- `_enhance_existing_chapters`：33 个实体追加到 7 个已有章节（Redis 注入 → 注入攻击类型章节，WAF 规则 → API 边界防护章节，等）
- 蓝图 version v2 → v3，状态回 published
- `blueprint_merged` 事件发布成功

**C5 测试中发现的 bug**：`ingest_service.py` 中 `document_parsed` 事件发布在 Celery fork 后因 EventBus 的 asyncio.Event 绑定到不同 event loop 而失败（3 次重试全部失败），导致第 3 本书的 extraction 管线中断。手动重发事件后恢复。已在 EventBus 增加 `reset()` 方法解决。

---

## 待完成

（无 — 全计划已完成）

---

## 阶段 8：结构化存储（P2 — 章节内容字段拆分）✅

### 8.1 章节内容字段拆分

**文件**：
- `migrations/021_chapter_content_columns.sql`（新建 5 个列）
- `apps/api/tasks/blueprint_tasks.py` — `_extract_chapter_fields()` + `_build_chapter_response()`
- `apps/api/modules/skill_blueprint/repository.py` — `update_chapter_content()` + `get_chapters()` 更新
- `apps/web/src/views/tutorial/TutorialView.vue` — `chapterContent` 优先使用结构化字段

**实现**：
- **Migration**：`skill_chapters` 新增 5 列（全部 NULLABLE TEXT）：
  - `scene_hook` — 场景引入
  - `code_example` — 代码示例（已格式化为 `<pre><code>` HTML）
  - `misconception_block` — 常见误区
  - `skim_summary` — 速览摘要
  - `prereq_adaptive` — 自适应内容 JSON
- **写入**：`repo.update_chapter_content()` 和 `regenerate_all_chapters` 均改为同时写入 5 个结构化列（调用 `_extract_chapter_fields()` 从 normalized JSON 提取）
- **读取**：`repo.get_chapters()` 使用 `_build_chapter_response()`，优先取列值，列值为 NULL 时 fallback 到 `content_text` JSON 解析（旧数据无缝兼容）
- **前端**：`chapterContent` computed 优先检查 `ch.scene_hook`/`ch.code_example`/`ch.skim_summary` 是否存在 → 直接使用结构化字段；否则走 `JSON.parse(content_text)` 旧路径

### 向后兼容性

| 场景 | 行为 |
|------|------|
| 新生成章节 | 5 列同时写入，API 直接返回字段值 |
| 旧章节（列值为 NULL） | `_build_chapter_response` 从 content_text JSON 解析提取 |
| 极旧章节（content_text 非 JSON） | 将 content_text 原值作为 full_content |
| 前端 TutorialView | 优先取结构化字段 → fallback JSON.parse |

---

## 下一步计划：Phase 9 — 学习体验闭环（P1）

### 9.1 测验结果→知识掌握度闭环 ✅

**文件**：
- `apps/api/modules/routers.py` — `submit_chapter_quiz()`
- `apps/web/src/views/tutorial/TutorialView.vue`

**实现**：
- 后端 `submit_chapter_quiz` 已实现 mastery_score 增量写入（single_choice/scenario ±0.2, true_false ±0.1），ON CONFLICT DO UPDATE
- 返回体增加 `entity_name` 字段（通过 knowledge_entities 表 JOIN 查找 canonical_name）
- 前端 `submitQuiz()` 捕获 `quizMasteryChanges` 返回值
- 测验结果面板展示每个实体的掌握度变化（绿色 +Δ / 红色 -Δ），含实体名称标签

### 9.2 笔记→知识实体关联 ✅

**文件**：
- `migrations/020_note_entity_links.sql`（新建 `note_entity_links` 表）
- `apps/api/modules/learner/eight_dim_endpoints.py` — `create_note()`、`list_notes()`、`get_notes_by_entity()`
- `apps/web/src/views/learner/NotesView.vue`
- `apps/web/src/api/index.ts`

**实现**：
- **Migration**：`note_entity_links` (note_id UUID → learner_notes, entity_id UUID → knowledge_entities, 联合主键 + 双索引)
- **笔记创建自动关联**：`create_note()` 中若提供 `chapter_id`，自动查询 `chapter_entity_links` 并批量 INSERT INTO note_entity_links（ON CONFLICT DO NOTHING 幂等），实体关联失败不阻断笔记创建
- **笔记列表附带实体**：`list_notes()` 批量加载 note_entity_links → knowledge_entities，返回每个笔记的 `linked_entities` 数组（entity_id + canonical_name + short_definition）
- **按知识点查看笔记**：新增 `GET /api/learners/me/notes/by-entity/{entity_id}`，返回实体基本信息 + 关联的 50 条笔记
- **前端实体标签**：笔记卡片展示关联知识点标签（📌 canonical_name），hover 弹出 short_definition tooltip，点击过滤该知识点的所有笔记
- **过滤提示条**：蓝色提示条显示当前过滤的知识点名称 + 清除/查看全部按钮
- **知识点笔记弹窗**：点击"查看此知识点全部笔记"打开弹窗，展示该实体的基本信息 + 所有关联笔记列表

### 9.3 学习进度仪表板 ✅

**后端文件**：`apps/api/modules/learner/eight_dim_endpoints.py`

**新增端点**：`GET /api/learners/me/dashboard`
- 最近学习记录（`recent_activity`）：最近 5 条已完成章节，含章节名、阶段名、主题、完成时间
- 薄弱章节（`weak_chapters`）：平均掌握度 < 0.4 的章节（通过 learner_knowledge_states → chapter_entity_links → skill_chapters 关联），按掌握度升序
- 上次学习章节（`last_learned`）：每主题最近完成的章节（DISTINCT ON topic_key）
- 课程进度概览（`course_progress`）：每主题已读/总章节数

**前端文件**：`apps/web/src/views/HomeView.vue`、`apps/web/src/api/index.ts`

**实现**：
- **继续上次学习卡片**：蓝色渐变卡片，显示上次章节名 + 所属课程，点击跳转 `/tutorial?topic=xxx`（TutorialView 通过 localStorage `last_chapter:{topic}` 恢复到具体章节）
- **课程卡片进度条**：每个课程卡片显示已读/总章节数 + 进度条（灰色底，el-progress）
- **薄弱章节区**：红色告警卡片，列出掌握度不足的章节，含弱知识点计数、进度条、百分比，点击跳转对应课程
- **最近学习记录**：时间线样式，蓝色圆点 + 章节名 + 阶段/课程信息 + 相对时间（刚刚/X分钟前/X小时前/X天前）
- 课程卡片"继续学习"按钮改为携带 topic 参数跳转
- 数据加载策略：`loadDomains()` 时并行加载 radar + review + dashboard；切换主题时重新加载

### 9.4 课程订阅通知增强 ✅

**文件**：
- `apps/api/main.py` — 新增 `blueprint_merged` 事件订阅者
- `apps/api/modules/knowledge/notification_router.py` — 新增 `POST /{id}/dismiss` 端点
- `apps/web/src/components/NotificationBell.vue`

**实现**：
- **事件订阅**：`main.py` 中订阅 `blueprint_merged` 事件，查询 `space_subscriptions` 表获取所有订阅该空间/主题的用户，为每人调用 `send_notification()` 发送通知
- **通知格式**：`type` = `blueprint_merged`，`title` = `"课程「{topic_key}」已更新"`，`message` = JSON `{"enhanced": N, "new": M, "topic_key": "...", "space_id": "..."}`
- **忽略端点**：`POST /api/notifications/{id}/dismiss` 标记通知已读（与已读同步，避免重复提醒）
- **前端通知卡片**：
  - `parseMergeMsg()` 解析 message JSON → 展示 ✨ 新增 N 章 / 📝 增强 M 章
  - **"查看变更"按钮** → `router.push('/tutorial?topic=...')` 跳转到更新后的课程
  - **"忽略"按钮** → 调用 dismiss API，减少未读计数
  - 蓝色背景 + 蓝色边框（`.notif-item--merged`），与其他通知区分

### 实施进度

```
9.1 测验闭环        ✅ 已完成
9.2 笔记关联        ✅ 已完成
9.3 进度仪表板      ✅ 已完成
9.4 通知增强        ✅ 已完成
```

### 关键文件

| 文件 | 所属 | 状态 |
|------|------|------|
| `apps/web/src/views/tutorial/TutorialView.vue` | 9.1 | ✅ |
| `apps/api/modules/routers.py` | 9.1 | ✅ |
| `apps/api/modules/learner/eight_dim_endpoints.py` | 9.3 | ✅ |
| `apps/web/src/views/HomeView.vue` | 9.3 | ✅ |
| `apps/web/src/api/index.ts` | 9.3 | ✅ |
| `apps/web/src/views/learner/NotesView.vue` | 9.2 | ✅ |
| `apps/api/modules/learner/eight_dim_endpoints.py` | 9.2/9.3 | ✅ |
| `apps/web/src/components/NotificationBell.vue` | 9.4 | ✅ |
| `apps/api/modules/knowledge/notification_router.py` | 9.4 | ✅ |
| `apps/api/main.py` | 9.4 | ✅ |
| `migrations/020_note_entity_links.sql` | 9.2 | ✅ |

---

## Phase 5-8 完成验证与增强（2026-04-26）

### 背景

在 Phase 0-4 管线稳定 + Phase 9 体验闭环完成后，对 Phase 5-8 计划中 12 个子项进行逐项代码验证。大部分功能实际在计划制定时就已实现于代码中，本次验证确认状态并修复发现的 bug。

### 5.1 无证据拒答护栏 ✅

**文件**：`apps/api/modules/teaching/teaching_service.py`

**验证结果**：`chat_and_prepare()` 第 613-638 行已完整实现。
- `retrieved` 为空 → 直接返回模板回答，`confidence=0`，不调 LLM
- 低置信度时 system prompt 追加 "不要猜测" 指令

### 5.2 查询改写 ✅

**文件**：`apps/api/modules/teaching/teaching_service.py` `_rewrite_query()`

**验证结果**：第 236-299 行已实现。LLM 轻量 prompt 改写为 2-3 个关键词短语，2s 超时降级。

### 5.3 裸代码检测 ✅

**文件**：`apps/api/tasks/blueprint_tasks.py` `_normalize_code_blocks()`

**验证结果**：第 304-411 行已完整激活，无 `return text` 死代码。
- `_is_code_line()` 检测 SQL/Python/JS/Java/C/XML/CLI 代码行
- `_wrap_bare_code()` 包裹连续代码行（≥2 行）为 `<pre><code>`
- 自动语言检测

### 5.4 答案来源标注 ✅

**文件**：`apps/api/core/llm_gateway.py`、`apps/api/modules/teaching/teaching_service.py`、`apps/web/src/views/tutorial/ChatView.vue`

**验证结果**：
- teach system prompt 已追加 "【实体名】标注来源" 指令
- API 返回体包含 `cited_sources` 字段
- 前端 ChatView `renderMd()` 将 `【xxx】` 渲染为 `.source-annot` 元素
- CSS hover 显示知识点定义 tooltip

### 6.1 页面级分块 + title_path ✅

**文件**：`apps/api/modules/knowledge/ingest_service.py`

**验证结果**：`ingest()` 已调用 `_extract_pages()`（非 `_extract_text()`），每页独立切分 chunk。
- `_extract_outline()` 提取 PDF 大纲
- `_build_title_path()` 构建层级标题路径
- chunk 记录 `page_no` 和 `title_path`

### 6.2 chunk 检索通道 ✅

**文件**：`apps/api/modules/teaching/teaching_service.py` `RetrievalFusionService`

**验证结果**：`retrieve()` 已实现四路召回（实体 BM25 + 实体向量 + chunk BM25 + chunk 向量）。
- `_chunk_bm25()` / `_chunk_vector()` 方法
- RRF 融合时 chunk 结果与实体结果混合排名
- chunk 结果标注 `page_no` 和 `title_path`

### 6.3 学习路径分层 ✅

**文件**：`apps/api/modules/learner/learner_service.py`

**验证结果**：`_compute_chapter_path()` 第 650-682 行已实现。
- `gap_score > 0.8` → `foundation`（必修）
- `gap_score < 0.3` → `enrichment`（拓展）
- 其余 → `standard`
- `estimated_minutes` 按内容长度估算（100 字 ≈ 1 分钟）

### 7.1-7.4 多文档融合（merge 模式） ✅

**验证状态**：C5 增量合并测试通过（Book C → 已有 Blueprint）。
- `_diff_new_entities()` 通过余弦相似度分类实体
- `_enhance_existing_chapters()` 增强已有章节
- `_insert_new_chapters()` 插入新章节
- `_check_blueprint_lock(mode="merge")` 支持已发布蓝图 merge
- `blueprint_merged` 事件通知订阅用户

### Phase 8：章节内容字段结构化 ✅

**DB 迁移**：`skill_chapters` 表已增加 5 个结构化列：
- `scene_hook`（场景引入）
- `code_example`（代码示例）
- `misconception_block`（常见误区）
- `skim_summary`（速览摘要）
- `prereq_adaptive`（前置知识自适应）

**后端**：
- `_parse_content_fields()` 从 JSON 提取结构化字段
- `update_chapter_content()` 同时写入 `content_text` 和结构化列
- `_build_chapter_response()` 优先取结构化列，NULL 时 fallback JSON 解析
- old data backward compatible

**前端**：
- `TutorialView.vue` `chapterContent` computed 优先使用 API 返回的结构化字段
- 无需 `JSON.parse(content_text)`，零解析开销

**2026-04-26 Bugfix**：
- `_build_chapter_response` 结构化路径 `full_content` 错误取到 JSON blob → 修复为从 JSON 提取 `full_content` 文本
- 前端 `chapterContent` 优先用 `ch.full_content`（API 已提取）
- `/reflect` 端点直接查 `skim_summary` 列，跳过 JSON 解析

---

## Reranker 交叉编码精排（2026-04-26）

### 背景

双路检索（BM25 + 向量）经 RRF 融合后，取 top-k 结果直接用于教学问答。RRF 仅利用排名位置信息，未利用 query-document 语义交互。引入 reranker 作为第三级精排，提升检索精度。

### 实现

**新文件/方法**：
- `apps/api/core/llm_gateway.py` — `async def rerank(query, documents, top_n=5)` (line 458-548)
- `apps/api/modules/admin/ai_config_router.py` — `_test_reranker_raw()` (line 423-490)

**检索管线**：`teaching_service.py` `RetrievalFusionService.retrieve()`
```
RRF 粗排取 20 候选项 → reranker 精排 → top 5
```
- `RERANK_INPUT_N = 20`：送入 reranker 的候选数
- reranker 不可用时自动回退 RRF 排序

**端点兼容性**：按顺序探测 4 种路径
| 顺序 | 端点 | 适用 |
|------|------|------|
| 1 | `/reranking` | llama.cpp |
| 2 | `/v1/reranking` | Nvidia NIM |
| 3 | `/v1/rerank` | TEI / vLLM / Jina |
| 4 | `/rerank` | 裸端点兜底 |

支持 `params.rerank_path` 手动覆盖路径，适配未来新 provider 无需改代码。

**管理后台**：
- capability 注册表新增 `reranker`（kind=reranker）
- Provider 测试新增第三个选项：reranker（测 reranking 端点）
- 测试用 3 篇文档验证相关性排序（2 篇相关 + 1 篇无关）
- 错误透传：非 200 响应不再被静默吞掉，完整展示每个 URL 的失败原因

**响应格式兼容**：
- 标准：`{"results": [{"index": 0, "relevance_score": 0.95}]}`
- 降级：`{"scores": [0.95, 0.3, ...]}`

### nginx DNS 动态解析

**文件**：`apps/web/nginx.conf`

**问题**：nginx 启动时解析 `api:8000` 一次并缓存 IP，API 容器重建后 IP 变化 → 502。

**修复**：
```nginx
resolver 127.0.0.11 valid=30s;
set $api_upstream "api:8000";
proxy_pass http://$api_upstream;
```
使用变量强制 nginx 每次请求重新 DNS 解析（按 `valid` TTL），杜绝 502。

### 关键文件

| 文件 | 变更 |
|------|------|
| `apps/api/core/llm_gateway.py` | + rerank() 方法（90 行） |
| `apps/api/modules/teaching/teaching_service.py` | RRF → reranker 管线接入 |
| `apps/api/modules/admin/ai_config_router.py` | + reranker 测试 + 错误透传 |
| `apps/web/src/views/admin/AiConfigView.vue` | + reranker 测试选项 + 结果展示 |
| `apps/web/nginx.conf` | Docker DNS 动态解析 |
| `apps/api/core/config.py` | chunk_size 1500→3500，chunk_overlap 150→350 |
| `apps/web/src/views/learner/RepairPathView.vue` | + priority 标签（必修/拓展） |

### 实施进度

```
Phase 5.1 拒答护栏           ✅ 已验证
Phase 5.2 查询改写           ✅ 已验证
Phase 5.3 裸代码检测         ✅ 已验证
Phase 5.4 来源标注           ✅ 已验证
Phase 6.1 页面级分块         ✅ 已验证
Phase 6.2 chunk 检索通道     ✅ 已验证
Phase 6.3 学习路径分层       ✅ 已验证
Phase 7   多文档融合          ✅ 已验证
Phase 8   字段结构化          ✅ 已验证 + bugfix
Reranker  精排管线            ✅ 已完成
nginx     DNS 动态解析       ✅ 已部署
chunk     1500→3500          ✅ 已调整
前端      学习路径标签        ✅ 已完成
```
