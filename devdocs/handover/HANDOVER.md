# StudyStudio 会话交接文档

**生成日期：** 2026-04-27
**上次更新主题：** 会话后继推进 — 密钥轮换验证、前端重构建、JWT 强化、Auth 单元测试(43)、管理面板合并评估

---

## 一、历史完成工作（已稳定）

### Phase 1~4（略，见旧文档备份）

### 账号管理功能
- POST /api/users/me/avatar：头像上传到 MinIO
- PATCH /api/users/me：更新昵称、头像
- POST /api/users/me/change-password：修改密码（含强度校验）
- DELETE /api/users/me：账号注销软删除，Migration 010

### 社交学习功能（Phase 1~3）
- 多成员 space + 邀请码 + visibility（003 迁移）
- 话题订阅（005 迁移）
- 公开广场 /community：visibility=public 课程发现 + 一键加入
- Fork 空间：异步复制（009 迁移）
- Wall 讨论按 space_id 隔离（011 迁移）

### 测验系统完善
- 章节测验、得分联动、答题回顾、预生成、ai_rubric

### Phase 3a — 课程讨论区（2026-04-22 完成）
- Migration 013：course_posts + course_post_replies 建表
- 后端：`apps/api/modules/discuss/router.py`，接口前缀 `/api/discuss`
- 前端：SpacePostsView.vue、DiscussView.vue、WallSection.vue 全部对接
- discussApi 已添加到 api/index.ts

### Celery 队列架构修复
- 新增 `celery_worker_review` 专用 worker，订阅 `knowledge.review` 队列，并发=2
- `auto_review_entities` 和 `resume_pending_review` 路由到 `knowledge.review`
- `celery_worker_knowledge` 并发从 4 提升到 8
- synthesize_blueprint 路由到 `blueprint.synthesis.queue`
- RabbitMQ 队列属性冲突修复（delete_queue 后重启）
- _safe_parse_json 修复非法反斜杠转义

### 文档状态流水线修复
- 五阶段：uploaded → parsed → extracted → embedding → reviewed
- Migration 014：documents CHECK 约束新增 embedding / failed 值

### Blueprint V2（已完成四项质量修复）
- P0 章节内容覆盖（cluster_id 做 key）
- P1+P2 Stage 规划 + 动词多样性
- P3 簇大小均衡（_rebalance_clusters）

### 精读原文功能（S2 已修复）
- document_chunks 新增 page_no 字段
- source 接口：向量检索 + ILIKE 关键词 fallback

### Blueprint 任务风暴根治（P0~P3）
- 幂等锁 `_check_blueprint_lock()`
- on_failure 钩子，status='failed'，error_message 字段记录
- max_retries 5→2
- resume_pending_review 排除 published / 2小时内 generating

---

## 二、本次会话完成工作（2026-04-25 ~ 2026-04-26）

### 文档到课程全自动管线优化（Phase 0~4）

详见 `devdocs/PROJECT_LOG_V2_管线优化记录.md`，摘要如下：

**Phase 0 — 致命缺陷修复（6 项）：**
- 0.1 LLM 异常捕获遗漏（APIConnectionError/APITimeoutError 穿透）
- 0.2 消除事件双重发布（同一文档触发多个并行 extraction worker）
- 0.3 启用事件幂等保护（event_idempotency 表空转）
- 0.4 增加文档级提取锁（并发 worker 竞态）
- 0.5 修复 TaskTracker 写入 DB（task_executions 表为空）
- 0.6 补全提取锁状态列表（遗漏 extracting/failed）

**Phase 1 — 严重问题修复（3 项）：**
- 1.1 ingest flush→commit + 异常保护
- 1.2 LLM 恢复后自动重试失败文档
- 1.3 审核后批量 embedding 派发（100 条逐条 → 1 条批量）

**Phase 2 — 自动化增强（3 项）：**
- 2.1 文档管线进度 API（GET /api/files/documents/my-details）
- 2.2 前端文档进度可视化（UploadView 进度条 + ETA + 重试按钮）
- 2.3 管理面板告警聚合（system_health 增强 + SystemHealthView 告警）

**Phase 3 — 用户参与（2 项）：**
- 3.1 用户通知系统（user_notifications 表 + notification_router + 管线节点触发）
- 3.2 前端通知铃铛（NotificationBell 组件 + 30s 轮询 + 未读 badge）

**Phase 4 — 验证与修复（7 项）：**
- 4.1 课程代码格式修复（CHAPTER_CONTENT_PROMPT 重写 + _normalize_chapter_content + renderTerms 保护 pre 块）
- 4.2 Tutorial 500 修复（chapter_progress 无 status 列）
- 4.3 Admin 返回学习端导航修复（显式 @click）
- 4.4 404 after rebuild 修复（nginx 缓存控制 + notification_router prefix）
- 4.5 Web 构建错误修复（NotificationBell import 路径）
- 4.6 reviewed→published 文档状态回写缺失（blueprint 发布后不更新文档状态）
- 4.7 管理员全量文档面板（all-documents API 增强 + SystemHealthView「全部文档」Tab）

### 课程内容代码格式（专项修复）

**文件**：`apps/api/tasks/blueprint_tasks.py`、`apps/web/src/views/tutorial/TutorialView.vue`

**问题链**：LLM 生成裸代码（无 ``` 围栏）、raw `⏸` 字符、前端 `v-html` 渲染时 `\n→<br>` 破坏 `<pre>` 结构。

**修复链**：
1. 重写 `CHAPTER_CONTENT_PROMPT`：要求 markdown ```fences``` + 语言标识
2. 新增 `_normalize_chapter_content()`：``` → `<pre><code class="language-xxx">`（正则 + 语言自动检测），清理 `⏸`
3. 重写 `renderTerms()`：`<pre>` 块先替换为占位符 → 文本处理 → 还原 `<pre>`
4. 3 处内容存储点（V1/V2）均应用 normalize

---

## 三、本次会话完成工作（2026-04-27）

### 部署系统（零→完整方案）

详见 `devdocs/architecture/deployment_system.md`，摘要：

**升级系统：**
- 单文件自解压脚本（377K），上传即用，bash 执行
- 7 步自动流程：备份（pg_dump + 代码）→ 停止 → 更新 → 增量迁移 → 重建 → 启动 → 验证
- 迁移追踪：`schema_migrations` 表记录已执行迁移，升级时仅执行增量（Migration 022）
- 文件保护：`.env` 直接恢复，`docker-compose.yml` 旧版存 `.bak`，文档（INSTALL.md/README.md）旧版存 `.old_时间戳`
- 失败回滚：完整备份 + 回滚命令在脚本末尾输出

**全新安装：**
- 交互式配置：端口（8 项）、AI API、MinIO 外部地址
- 自动生成 `.env`（含随机密钥）、初始化管理员
- 与新装共享同一个 `upgrade_package.tar.gz`（369K）

**端口自定义：**
- 8 个端口变量（WEB/API/PG/REDIS/RABBITMQ×2/MINIO×2），`.env` 统一管理
- `docker-compose.yml` 使用 `${VAR:-default}` 语法，容器内部地址不变

**版本管理：**
- `VERSION` 文件（当前 2.7.0）+ `schema_migrations` 表追踪迁移
- 升级脚本对比版本，同版本跳过，不同版本仅执行差额迁移

**Docker 子网冲突：**
- 安装脚本检测宿主机 172.17.x.x → 如冲突则由用户自行输入安全子网 → 写入 `docker-compose.override.yml`
- 无冲突用户零影响，默认不使用自定义网络

**LLM 公有 API 兼容：**
- 已确认通过 `ai_providers` 表（`kind` 字段：`openai_compatible`/`anthropic`/`gemini`/`ollama`/`azure_openai`）完整支持

**代码级修复（顺手修）：**
- `file_router.py:541`：MinIO 预签名 URL 从硬编码 `localhost:9000` 改为读取 `MINIO_PUBLIC_ENDPOINT`

**交付物：**
| 文件 | 大小 | 用途 |
|------|------|------|
| `fresh_install_selfextract.sh` | 383K | 新装单文件 |
| `upgrade_studystudio_selfextract.sh` | 380K | 升级单文件 |
| `upgrade_package.tar.gz` | 369K | 纯代码包 |
| `INSTALL.md` | — | 安装升级指南 |
| `.env.example` | — | 环境变量模板（含 8 端口 + MinIO 外部地址） |
| `VERSION` | — | `2.7.0` |

---

## 三-B、全会话完成工作（2026-04-27 安全审计与修复）

### 全栈安全审计

详见 `devdocs/security/SECURITY_AUDIT_REPORT_20260427.md`

**审计方法：** 6 个并行安全 agent 分别审计：认证/JWT、SQL注入、XSS前端、硬编码密钥/Docker、文件上传/MinIO、CORS/错误处理。

**发现统计：** 4 CRITICAL + 10 HIGH + 14 MEDIUM + 5 LOW

### 已修复项（18 项）

**CRITICAL 修复：**
- C-1：轮换 `.env` 中泄露的真实 DeepSeek API Key → 占位符
- C-2：轮换 `.env` 中泄露的 AI_CONFIG_ENCRYPTION_KEY → 占位符
- C-3：`config.py` JWT 默认 `"change-me-in-production"` → 非 dev 环境强制要求环境变量，启动时校验
- C-4：（推迟）JWT→HttpOnly Cookie 需前后端同时改造

**HIGH 修复：**
- H-1：`system_health.py` 8 个管理端点 → 全部添加 `Depends(require_role("admin"))`
- H-2：`admin/router.py:1385` all-documents → `require_role("admin")` 替代 `get_current_user`
- H-3：`ChatView.vue` + `UploadView.vue` 的 `marked.parse()` → 全部包裹 `DOMPurify.sanitize()`
- H-4：`main.py` CORS `allow_origins=["*"]` + `credentials=True` 冲突 → 改为白名单模式
- H-5：`nginx.conf` → 添加 CSP/X-Frame-Options/HSTS/X-Content-Type-Options/Referrer-Policy
- H-6：`auth/router.py` login/register → 添加 IP 级速率限制（20次/分钟登录，5次/分钟注册）
- H-7：`tutorial_service.py:623` f-string UUID 拼接 SQL → `ANY(:ids)` 参数化查询
- H-8：`Dockerfile.api` → 添加非 root 用户 `appuser`，移除 `--reload`（生产环境）
- H-9：`docker-compose.yml` Postgres/RabbitMQ/MinIO 凭据 → `.env` 变量化
- H-10：（推迟到生产部署时评估）

**MEDIUM 修复：**
- M-1：`package.json` axios 1.6.0 → 1.7.9（修复 CVE-2023-45857）
- docker-compose.yml 宿主机挂载已标注（生产环境需改为 `:ro`）

### 变更文件一览

| 文件 | 变更类型 | 说明 |
|------|---------|------|
| `.env` | 密钥轮换 | API Key + Encryption Key → 占位符 |
| `.env.example` | 重构 | 新增 POSTGRES_USER/PASS、RABBITMQ_USER/PASS、MINIO_ROOT 变量 |
| `apps/api/core/config.py` | 强化 | JWT 启动校验，空/弱密钥拒绝启动（非 dev 环境） |
| `apps/api/main.py` | 修复 | CORS 白名单模式 + 方法约束 |
| `apps/api/modules/admin/system_health.py` | 修复 | 8 端点添加 `require_role("admin")` |
| `apps/api/modules/admin/router.py` | 修复 | all-documents 权限升级 |
| `apps/api/modules/tutorial/tutorial_service.py` | 修复 | SQL 参数化 |
| `apps/api/modules/auth/router.py` | 强化 | IP 速率限制 + Request 依赖 |
| `apps/web/nginx.conf` | 强化 | 完整安全响应头 |
| `apps/web/src/views/tutorial/ChatView.vue` | 修复 | DOMPurify 净化 |
| `apps/web/src/views/learner/UploadView.vue` | 修复 | DOMPurify 净化 |
| `apps/web/package.json` | 升级 | axios 1.6.0→1.7.9, +dompurify, +@types/dompurify |
| `docker/Dockerfile.api` | 加固 | 非 root appuser |
| `apps/web/Dockerfile.web` | 标注 | nginx 用户说明 |
| `docker-compose.yml` | 外部化 | Pg/RabbitMQ/MinIO 凭据 → ${VAR} |
| `devdocs/security/SECURITY_AUDIT_REPORT_20260427.md` | 新增 | 完整审计报告 |

### 推迟修复（需架构变更）

| 修复项 | 原因 |
|--------|------|
| JWT → HttpOnly Cookie | 前后端同时改造，所有 API 调用方式变更 |
| refresh_token + logout | 需新建 DB 表 + Redis 黑名单 |
| API 宿主机挂载只读 | 开发环境需可写，生产部署时再做分离 |
| 文件魔术字节验证 | 现有管线解析阶段会自动拒绝无效格式 |

---

## 三-C、本次会话完成工作（2026-04-27 后继推进）

### 密钥轮换验证
- 确认 `.env` 中 DeepSeek API Key 已更新（`sk-dbe87700...`）
- 确认 `AI_CONFIG_ENCRYPTION_KEY` 已轮换（44 字符 base64）

### JWT 密钥强化
- 开发环境 JWT_SECRET_KEY 从 `dev-secret-key-CHANGE-IN-PRODUCTION` → 随机 `secrets.token_hex(32)`
- 虽 APP_ENV=development 允许弱密钥，仍生成强密钥以消除安全隐患

### 前端重构建
- `npm run build` 成功（7.41s，1742 模块），产出含 dompurify + axios 1.7.9 + CSP 兼容代码

### 安全审计遗留项评估

| 项目 | 决定 | 理由 |
|------|------|------|
| C-4 JWT→HttpOnly Cookie | **保持推迟** | 需前后端全面改造（auth.py 登录响应 + auth.ts localStorage + axios withCredentials + 所有 API 调用），属架构级变更 |
| C-4 refresh_token + logout | **保持推迟** | 需新建 DB 表 + Redis 黑名单 |
| D1-D5 V1 残留代码 | **保持推迟** | V2 质量已验证稳定，但删除 V1 代码有回归风险，建议下个里程碑做 |
| S2 旧文档 page_no 为 null | **低优先级** | 管理员逐一重解析可补 |

### 管理员控制面板合并评估

**当前状态：** 管理后台 8 个独立页面，其中「系统监控」和「任务管理」功能高度相关。

**评估结论：不建议合并为单页面。**
- `SystemHealthView.vue` 已包含多 Tab（概览/全部文档/告警），页面已足够复杂
- `TaskManagementView.vue` 同样包含统计/筛选/批量操作/分页，独立运作良好
- 合并将产生 >1500 行的巨型组件，维护成本高

**建议方案：**
1. 增强 `DashboardView.vue`，增加运维摘要卡片（关键队列状态 + 近期失败任务数），点击跳转详细页
2. 在 SystemHealthView 告警项中添加到 TaskManagementView 的联动链接（如"查看相关任务"按钮）

### Auth/安全单元测试

**新文件：** `tests/unit/test_auth_security.py`（43 个测试，全部通过）

覆盖范围：
- 密码哈希与验证（bcrypt 格式、salt 随机性、Unicode 支持）
- 72 字节密码截断（ASCII/Unicode/截断后兼容性）
- JWT 签发/解码/过期时间/无效令牌/空令牌/SQL 注入防护
- UUID 规范化（有效性校验、SQL 注入字符串拒绝）
- 密码强度校验（长度/字符类型/常见弱密码/边界值）
- IP 速率限制器（滑动窗口/限额超限/独立 key/过期清理）
- RBAC 权限检查（admin 通过/learner 拒绝/多角色/空角色）
- JWT 密钥配置验证（dev 环境容错/production 强制）

### V1 残留代码清理（D1-D5）

**文件：** `apps/api/tasks/blueprint_tasks.py`（2248 → 1993 行，-255 行）

**已删除：**
- `SKILL_SIGNAL_PROMPT`（~14 行）— V1 技能信号提取 prompt
- `BLUEPRINT_SYNTHESIS_PROMPT`（~31 行）— V1 "一次规划全局" prompt
- `_synthesize_blueprint_async`（~200 行）— V1 三段式蓝图生成函数
- `use_v2` / `version` 变量 + V1/V2 分支逻辑 — `synthesize_blueprint` 入口点
- docker-compose.yml 中 `BLUEPRINT_V2_ENABLED=true`（2 处）

**保留：**
- `CHAPTER_CONTENT_PROMPT` — V2 和 merge 共用
- 所有 V2 函数（`_synthesize_blueprint_v2_async`、`_synthesize_blueprint_merge_async` 等）
- `_check_blueprint_lock`（full/merge 双模式均需保留）

### DashboardView 运维摘要增强

**文件：** `apps/web/src/views/admin/DashboardView.vue`

**实现：**
- 新增「管线状态」卡片：文档总数 / 卡住数 / 失败数，彩色数值 + 状态标签（正常/需关注/暂无数据），点击跳转系统监控
- 新增「任务状态」卡片：24h 内成功 / 需人工处理 / 最终失败，点击跳转任务管理
- 数据源复用已有 API：`getPipelineStatus()` + `getTaskStats()`，并行加载，不阻塞主页面
- 卡片布局与现有统计卡片风格一致，hover 阴影效果

### 原有测试修复
- `test_core_modules.py` 中 2 个过期测试修复：
  - `test_long_message_is_signal`：V2.6 后需 ≥2 信号才归为 complex，补上 deep_inquiry 信号
  - `test_mechanism_keyword`：同上，补上第二个 gap_type

**全部测试：98 passed, 0 failed**

### 变更文件一览

| 文件 | 变更 | 说明 |
|------|------|------|
| `.env` | 修改 | JWT_SECRET_KEY 强化 |
| `apps/web/dist/` | 重构建 | 1742 模块，含全部安全修复 |
| `tests/unit/test_auth_security.py` | **新增** | 43 个认证/安全测试 |
| `tests/unit/test_core_modules.py` | 修复 | 2 个过期测试断言（适配 V2.6 classify 逻辑） |
| `apps/web/src/views/admin/DashboardView.vue` | 增强 | 管线状态 + 任务状态运维摘要卡片 |
| `apps/api/tasks/blueprint_tasks.py` | 清理 | V1 残留代码 D1-D5，-255 行 |
| `docker-compose.yml` | 清理 | 移除废弃 BLUEPRINT_V2_ENABLED |
| `apps/web/dist/` | 重构建 | 含 DashboardView 运维摘要 |
| `devdocs/handover/HANDOVER.md` | 更新 | 本会话工作记录 v14.0 |

---

## 三-D、本次会话完成工作（2026-04-27 部署 + 测试扩展）

### 集成测试扩展
- **新文件：** `tests/integration/test_document_pipeline.py`（46 个测试，全部通过）
- 覆盖范围：
  - 文档状态机（八状态正向流转/失败/锁/终态）
  - 提取锁原子性（rowcount 检查）
  - Embedding 完成后状态提升（reviewed/published）
  - 知识提取纯函数（JSON 解析/修复/实体归一化/分类回退）
  - 自动审核（JSON 数组解析/恢复逻辑）
  - 蓝图合成（CVE 过滤/null安全/JSON 修复/代码格式转换）
  - 端到端流程（六阶段触发链/事件顺序）
  - 错误恢复（失败/重试/锁安全/Celery retry 枯竭）
- 46 个测试全部基于实际管线函数的真实签名验证，与现有 98 个测试零冲突

### 全量测试
- **144 passed, 0 failed**（87 unit + 11 旧集成 + 46 新管线集成）

### 管理员面板联动
- `SystemHealthView.vue`：管线告警区新增「查看相关任务 →」按钮，跳转 `/admin/tasks`

### 生产部署推进
- 重建 `upgrade_package.tar.gz`（923K，含最新前端 dist + 完整测试套件）
- 通过 SCP 上传到远程服务器（10.10.50.14）
- 服务器完成：备份（database.sql 93MB + code_backup.tar.gz 47MB）→ 停止 → 解压代码 → .env 追加缺失变量 → JWT 密钥强化 → 增量迁移（018-021）→ docker compose build --no-cache（进行中）

### 变更文件一览

| 文件 | 变更 | 说明 |
|------|------|------|
| `tests/integration/test_document_pipeline.py` | **新增** | 46 个管线集成测试 |
| `apps/web/src/views/admin/SystemHealthView.vue` | 增强 | 管线告警 → 任务管理联动按钮 |
| `apps/web/dist/` | 重构建 | 含 SystemHealthView 联动链接 |
| `upgrade_package.tar.gz` | 重建 | 923K，含全部最新代码 |
| `devdocs/testing/TESTING.md` | **新增** | 完整测试体系文档（结构/覆盖矩阵/运行/原则） |

---

## 四、待开发

### 下次会话首要任务

1. **生产环境部署完成**：服务器构建完成后，启动服务验证 → 健康检查 → 前端/API 可达性
2. **升级后验证**：确认所有容器正常运行，管线功能可用
3. **SystemHealthView 队列联动增强**：工作队列 Tab 中挂起任务跳转到 TaskManagementView

---

## 五、已知 Bug 与技术债

| 编号 | 位置 | 内容 | 状态 |
|---|---|---|---|
| T1 | blueprint_tasks.py | chapter_contents 用 title 做 key | **已修复** |
| T3 | llm_gateway.py | Lock 绑旧 loop | **已根修** |
| T4 | blueprint_tasks.py | stage_type 硬编码 | **已修复** |
| T5 | blueprint_tasks.py | CHAPTERS_PER_STAGE 硬编码切片 | **已修复** |
| S1 | embedding_tasks.py | chunk embedding 写入代码缺失 | **已修复** |
| S2 | document_chunks | 旧文档 page_no 为 null | 管理员逐一重解析可补 |
| S3 | llm_gateway.py | max_tokens 未传导致长内容截断 | **已修复** |
| S4 | tutorial_tasks.py | beat_schedule resume_pending_review 缺 queue | **已修复** |
| S5 | docker-compose.yml | knowledge worker 并发不足，审核任务被饿死 | **已修复（独立队列+专用worker）** |
| S6 | tutorial_tasks.py | synthesize_blueprint 无路由配置 | **已修复** |
| S7 | knowledge_tasks.py | _safe_parse_json 非法反斜杠转义 | **已修复** |
| S8 | documents / embedding_tasks.py | 文档状态审核完即显示完成 | **已修复** |
| S9 | blueprint_tasks.py | asyncpg AmbiguousParameterError（:tk 重复3次） | **已修复** |
| S10 | blueprint_tasks.py | published 蓝图被误改为 generating | **已修复** |
| S11 | auto_review_tasks.py | rescue_session UPDATE 在已关闭 session 外执行 | **已修复** |
| S12 | discuss/router.py | list_replies 字段名 r.nickname → r.username | **已修复** |
| S13 | CommunityView.vue | goLearn 未传 space_id，跳转到错误课程 | **已修复** |
| S14 | blueprint_tasks.py | reviewed→published 文档状态回写缺失 | **已修复** |
| S15 | llm_gateway.py | APIConnectionError/APITimeoutError 未捕获 | **已修复** |
| S16 | knowledge_tasks.py | 事件双重发布导致并行 worker 竞态 | **已修复** |
| S17 | knowledge_tasks.py | 文档提取无锁保护 | **已修复（原子 UPDATE 锁）** |
| S18 | main.py | 事件幂等保护未启用 | **已修复** |
| S19 | task_tracker.py | task_executions 表始终为空 | **已修复** |
| S20 | ingest_service.py | flush 不 commit 导致异常时记录丢失 | **已修复** |
| S21 | notification_router.py | 路由前缀缺少 /api 导致 404 | **已修复** |
| S22 | nginx.conf | index.html 无缓存控制导致 stale 404 | **已修复** |
| S23 | blueprint_tasks.py | CHAPTER_CONTENT_PROMPT 输出裸代码/⏸ | **已修复** |
| S24 | routers.py | chapter_progress SQL 引用不存在的 status 列 | **已修复** |
| ~~D1-D5~~ | blueprint_tasks.py | ~~V1 残留代码~~ | **2026-04-27 已清理：-255 行** |

### 已知数据污染（需重跑消除）
- websecret blueprint v11：ch6/ch7 同名导致内容污染（T1 已修，重跑后消失）

---

## 六、关键决策记录

- **space_type 对用户完全隐藏**：前端不展示，数据库保留
- **visibility 是可见性控制字段**：private / shared / public
- **固定路由必须在参数路由之前注册**
- **asyncpg 同一 SQL 参数名必须唯一**：重复参数名触发 AmbiguousParameterError
- **V1 补偿代码推迟清理**：等 V2 质量达到可用再删
- **task_acks_late=True 不改**：改为在重型任务层面加幂等锁
- **blueprint failed 状态**：Migration 012，error_message 字段记录，resume 自动重触发
- **knowledge 队列积压属正常运行**：有消费者时积压不报告警
- **审核任务独立队列**：knowledge.review + 专用 worker，避免被饿死
- **讨论区替代学习墙**：统一用 course_posts 表，旧 wall_posts 数据已迁移
- **文档状态六阶段**：uploaded → parsed → extracted → embedding → reviewed → published
- **文档状态 reviewed→published 回写**：在蓝图发布（V1/V2）时更新同空间所有 reviewed 文档为 published
- **nginx 缓存策略**：index.html 禁止缓存（no-store），带 hash 的 /assets/ 长期缓存（immutable）
- **LLM 异常处理**：必须同时捕获 APIError、APIConnectionError、APITimeoutError
- **事件幂等保护**：subscribe() 必须传 db_session_factory，否则幂等检查跳过
- **文档提取锁**：原子 UPDATE 将状态改为 extracting，rowcount=0 则跳过
- **通知系统**：独立 engine（NullPool），兼容 Celery prefork 模式
- **API 路由前缀**：所有路由必须含 /api 前缀，nginx 只代理 /api/ 路径
- **RabbitMQ 队列属性变更**：先 delete_queue 再重启 worker
- **课程总标题展示**：blueprint.title 是 AI 生成的权威概括，区别于用户自定义课程名
- **升级包排除字体目录**：`apps/api/assets/fonts/`（19MB）中的 CJK 字体 Docker 镜像已通过 apt 安装，升级包排除以减少体积
- **自解压脚本模式**：脚本末尾附加 `__STUDYSTUDIO_ARCHIVE__` 标记 + tar.gz 二进制，`grep -a` 定位标记后 tail 提取，单文件部署
- **迁移追踪**：`schema_migrations` 表（Migration 022）记录已执行迁移文件名，升级时仅执行未记录的迁移。新装时 001 由 postgres initdb 自动执行，002~021 由脚本执行并标记
- **配置文件保护策略**：`.env`→直接恢复不可覆盖；`docker-compose.yml`→新版生效旧版存`.bak`；文档→新版生效旧版存`.old_时间戳`
- **端口不在 docker-compose.yml 中硬编码**：全部使用 `${VAR:-default}`，用户仅编辑 `.env` 即可
- **Docker 子网不做默认值**：安装脚本检测到 172.17 冲突时由用户自行输入子网，写入 `docker-compose.override.yml`。无冲突用户不受影响
- **全栈安全审计**：6 个 agent 并行审计，发现 4 CRITICAL + 10 HIGH + 14 MEDIUM + 5 LOW，已修复所有可修复项。审计报告：`devdocs/security/SECURITY_AUDIT_REPORT_20260427.md`
- **密钥轮换**：`.env` 中真实 DeepSeek API Key 和加密密钥已替换为占位符。用户需在 DeepSeek 控制台生成新 Key
- **JWT 强制**：非 development 环境必须设置 `JWT_SECRET_KEY`，否则启动失败。`config.py` 启动时校验
- **管理端点鉴权**：`system_health.py` 全部 8 个端点 + `all-documents` 端点均要求 `require_role("admin")`
- **前端 XSS 防护**：引入 `dompurify` 对所有 `marked.parse()` 输出做 HTML 净化，CSP 头加固
- **认证速率限制**：登录 20次/分钟，注册 5次/分钟，基于 IP 的滑动窗口
- **SQL 参数化**：`tutorial_service.py` 中 UUID 列表的 IN 查询改为 `ANY(:ids)` 数组参数化
- **Docker 非 root**：`Dockerfile.api` 创建 `appuser` 用户运行，移除生产环境的 `--reload` 标志
- **Docker 凭据外部化**：Postgres/RabbitMQ/MinIO 凭据全部改为 `.env` 变量
- **nginx 安全头**：添加 CSP/X-Frame-Options/X-Content-Type-Options/Referrer-Policy 等 8 个安全头
- **axios 升级**：1.6.0 → 1.7.9（修复 CVE-2023-45857）
- **Admin 面板合并评估**：不建议合并 SystemHealthView + TaskManagementView 为单页（均已是复杂页面）。建议在 DashboardView 增加运维摘要 + 跨页联动链接
- **JWT_SECRET_KEY 强化**：即使开发环境也使用随机密钥（`secrets.token_hex(32)`），消除默认密钥安全隐患
- **Auth 单元测试覆盖**：43 个测试覆盖密码哈希/JWT/UUID 防注入/密码强度/速率限制/RBAC，全部通过
- **V1 残留代码清理**：删除 `_synthesize_blueprint_async` + V1 Prompts（SKILL_SIGNAL/BLUEPRINT_SYNTHESIS）+ feature flag 分支，blueprint_tasks.py -255 行。V2 全阶段验证稳定后执行
- **DB 事务回滚修复**：`router.py` 4 处 + `system_health.py` 9 处 `except` 块吞掉异常但未 `await db.rollback()`，导致后续查询全部 `InFailedSQLTransactionError`。全部补齐 rollback
- **前端 axios 裸调用修复**：`SystemHealthView.vue` 中 `llm-status`、`all-documents` 等 13 处使用裸 `axios.get/post()` 未带 auth 拦截器，改为 `http.get/post()`
- **Migration 023**：`documents` 表缺 `last_error` 列，`failed`/`extracting` 状态未入 CHECK 约束。新建 023 迁移补齐

---

## 七、开场指引

1. 读本文件（HANDOVER.md）+ SYSTEM_REFERENCE.md + COLLABORATION.md
2. 勘察想做的功能相关代码（勘察脚本先跑，再动手）
3. 直接说想推进哪个任务

---

*文档版本：v15.0*
*生成时间：2026-04-27*
