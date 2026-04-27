# StudyStudio — 开发者文档

> 本文档面向参与代码贡献的开发者，涵盖本地环境搭建、架构说明、API 规范和开发约定。

---

## 目录

1. [本地开发环境](#1-本地开发环境)
2. [项目架构](#2-项目架构)
3. [后端模块说明](#3-后端模块说明)
4. [Celery 异步任务](#4-celery-异步任务)
5. [数据库说明](#5-数据库说明)
6. [API 规范](#6-api-规范)
7. [前端说明](#7-前端说明)
8. [开发约定 Checklist](#8-开发约定-checklist)
9. [常用诊断命令](#9-常用诊断命令)

---

## 1. 本地开发环境

### 前置条件

| 工具 | 最低版本 |
|:---|:---|
| Docker | 20.10 |
| Docker Compose | 2.0 |
| Node.js（仅前端热更新） | 18 |
| Python（仅单测） | 3.11 |

### 首次启动

```bash
# 1. 克隆仓库
git clone <repo-url>
cd studystudio

# 2. 配置环境变量
cp .env.example .env
# 编辑 .env，至少填写 OPENAI_API_KEY

# 3. 启动所有容器
docker-compose up -d

# 4. 初始化数据库（依次执行迁移）
for f in migrations/*.sql; do
  docker-compose exec -T postgres psql -U user -d adaptive_learning < "$f"
done
```

### 日常开发

```bash
# 仅重建后端
docker-compose build api && docker-compose up -d api

# 仅重建前端（Vue 源码修改后必须 build，nginx 托管 dist）
docker-compose build web && docker-compose up -d web

# 前端热更新（开发调试用，需在 .env 中设置 VITE_API_BASE）
cd apps/web && npm install && npm run dev
```

### 服务地址

| 服务 | 地址 |
|:---|:---|
| 前端 | http://localhost:3000 |
| API 文档 | http://localhost:8000/docs |
| MinIO 控制台 | http://localhost:9001 |
| RabbitMQ 管理 | http://localhost:15672 |
| PostgreSQL | localhost:5432 |

---

## 2. 项目架构

```
┌──────────────────────────────────────────────┐
│              Browser / Client                 │
│          Vue 3 SPA  ·  Element Plus           │
└───────────────────┬──────────────────────────┘
                    │  REST API
┌───────────────────▼──────────────────────────┐
│             FastAPI  (port 8000)              │
│                                               │
│  /auth  /knowledge  /learner  /tutorial       │
│  /teaching  /blueprint  /space  /discuss      │
└─────┬──────────────┬──────────────┬───────────┘
      │              │              │
 ┌────▼─────┐   ┌────▼────┐   ┌────▼──────┐
 │PostgreSQL│   │  Redis  │   │ RabbitMQ  │
 │ pgvector │   │  Cache  │   │ EventBus  │
 └──────────┘   └─────────┘   └─────┬─────┘
                                    │
              ┌─────────────────────┼─────────────────────┐
              │                     │                     │
       ┌──────▼──────┐      ┌───────▼──────┐    ┌────────▼──────┐
       │   Worker    │      │    Worker    │    │    Worker     │
       │  tutorial   │      │  knowledge   │    │    review     │
       │  low_prio   │      │  blueprint   │    │  (审核专用)    │
       └─────────────┘      └─────────────┘    └───────────────┘
```

### 事件驱动流水线

API 启动时在 `main.py` 中注册 4 个 RabbitMQ 事件订阅，实现全异步流水线：

```
文件上传 → file_uploaded
           └─► run_ingest（解析文档，queue=knowledge）
                 └─► document_parsed
                       └─► run_extraction（提取知识点，queue=knowledge）
                             └─► knowledge_extracted
                                   └─► synthesize_blueprint（生成蓝图，queue=knowledge）
                                         └─► skeleton_generated
                                               └─► generate_annotations（写章节，queue=tutorial）
```

---

## 3. 后端模块说明

所有业务路由聚合在 `apps/api/modules/routers.py`。

| 模块 | 前缀 | 说明 |
|:---|:---|:---|
| `auth` | `/api/auth` `/api/users` | 注册、登录、用户信息、账号注销 |
| `knowledge/file_router` | `/api/files` | 文件上传、文档管理、重解析 |
| `learner` | `/api/learners/me` | 掌握度、分级测验、学习路径、章节进度、笔记、成就 |
| `tutorial` | `/api/tutorials` | 教程获取（蓝图优先，fallback 骨架） |
| `teaching` | `/api/teaching` | AI 教学对话、对话管理、源文档溯源 |
| `skill_blueprint` | `/api/blueprints` | 蓝图状态查询、手动触发生成 |
| `space` | `/api/spaces` | 知识空间 CRUD、成员管理、邀请码、Fork |
| `community` | `/api/community` | 社区策展（提交 / 审核 / 列表） |
| `discuss` | `/api/discuss` | 课程讨论区（帖子 / 回复 / 聚合 feed） |
| `admin` | `/api/admin` | 用户管理、知识审核、系统配置、AI 配置 |

### core/ 核心组件

| 文件 | 职责 |
|:---|:---|
| `db.py` | AsyncSession 工厂 + pgvector 初始化 |
| `llm_gateway.py` | LLM 统一调用（多 provider / RRF 融合检索） |
| `events.py` | RabbitMQ 事件总线（aio-pika） |
| `storage.py` | MinIO 客户端封装 |
| `crypto.py` | AI 配置加密（Fernet） |

---

## 4. Celery 异步任务

### Worker 架构

| Worker | 队列 | 职责 | 并发 |
|:---|:---|:---|:---:|
| `celery_worker` | `tutorial` · `low_priority` | 教程骨架生成、章节内容编写 | 4 |
| `celery_worker_knowledge` | `knowledge` · `blueprint.synthesis` | 文档解析、知识提取、蓝图合成 | 8 |
| `celery_worker_review` | `knowledge.review` | 知识点 AI 双轮审核（专用隔离） | 2 |
| `celery_beat` | — | 定时巡检（每 5 分钟） | — |

> **注意：** `celery_worker_review` 独立隔离，防止长耗时审核任务被高频提取任务饿死。

### Worker 稳定性配置（禁止修改）

```yaml
command: celery ... --heartbeat-interval=10 --prefetch-multiplier=1
```

- `--prefetch-multiplier=1`：每次仅取一条任务，防止长任务堆积
- `--without-heartbeat` 绝对禁用
- RabbitMQ `consumer_timeout=28800000`（8 小时 ACK 超时）

### Blueprint 任务保障链

```
任务开始  →  _check_blueprint_lock()
              generating 且 < 2h  →  直接退出（幂等）
              否则               →  正常执行

执行成功  →  status = published
执行失败  →  retry（最多 2 次）
              耗尽  →  on_failure  →  status = failed，error_message 记录原因

每 5 分钟（celery_beat）：
  generating 超 2h  →  重置为 draft，重新触发
  failed / 无 blueprint  →  自动重新触发
```

### 定时任务

| 任务 | 间隔 | 队列 | 说明 |
|:---|:---|:---|:---|
| `resume_pending_review` | 5 min | `knowledge.review` | 续接中断的审核 + 补发缺失 blueprint + 重置超时 generating |
| `check_dlq` | 5 min | — | 检查死信队列积压 |

---

## 5. 数据库说明

### 技术选型

- **PostgreSQL 15 + pgvector**：关系型 + 向量检索一体
- **asyncpg**：异步驱动，裸 SQL，无 ORM
- **迁移方式**：手动 SQL 文件，按序号执行（`migrations/001_*.sql` 起）

### 核心数据表

| 表名 | 说明 |
|:---|:---|
| `users` | 用户账号（含软删除 `status` 字段） |
| `knowledge_spaces` | 知识空间（`visibility`: private / shared / public） |
| `space_members` | 空间成员关系 |
| `documents` | 上传文档（状态流：uploaded → parsed → extracted → embedding → reviewed） |
| `document_chunks` | 文档分块（`embedding vector(1024)`，`page_no`） |
| `knowledge_entities` | 知识实体（`review_status`: pending / approved / rejected） |
| `skill_blueprints` | 课程蓝图（`status`: draft / generating / published / failed，含 `error_message`） |
| `skill_stages` | 学习阶段 |
| `skill_chapters` | 章节（`content_text`，`code_example`） |
| `chapter_entity_links` | 章节-实体关联（`core_term` / `related`） |
| `conversations` | 教学对话（含 `space_id`） |
| `chapter_progress` | 章节完成进度 |
| `learner_knowledge_states` | 实体掌握度（`mastery_score` 0~0.9） |
| `chapter_quizzes` | 预生成测验题（含 `ai_rubric`） |
| `course_posts` | 课程讨论帖（绑 `space_id` / `chapter_id`） |
| `course_post_replies` | 帖子回复（一层） |
| `fork_tasks` | 异步 Fork 任务状态 |

### 迁移文件清单

| 编号 | 文件 | 内容 |
|:---|:---|:---|
| 001 | `initial_schema.sql` | 初始 31 张表 |
| 002 | `ai_config.sql` | AI 配置表 |
| 003 | `social_learning_phase1.sql` | 多成员 space + 邀请码 |
| 005 | `space_subscriptions.sql` | 话题订阅 |
| 006 | `phase3_topic_key_fork.sql` | Topic Key Fork |
| 007 | `tutorial_skeletons_space_id.sql` | 教程骨架支持 space_id |
| 008 | `community_curations.sql` | 社区策展 |
| 009 | `fork_space.sql` | Fork 空间异步任务 |
| 010 | `account_deactivation.sql` | 账号注销软删除 |
| 011 | `wall_posts_space_id.sql` | 讨论帖按 space 隔离 |
| 012 | `blueprint_failed_status.sql` | blueprint failed 状态 + error_message |
| 013 | `course_posts.sql` | 课程讨论区建表 |

---

## 6. API 规范

### 统一响应格式

```json
{ "code": 200, "msg": "success", "data": { ... } }
```

前端 axios 响应拦截器已剥一层：`res.data` 即 payload，无需写 `res.data.data`。

错误格式：

```json
{ "detail": { "code": "ERR_CODE", "msg": "可读错误信息" } }
```

### 路由注册顺序

**固定路由必须在同前缀的参数路由之前注册**，否则 FastAPI 会误匹配（返回 422）。

示例（`/spaces` 路由）：

```python
GET  /spaces/public          # ← 固定路由，必须在前
POST /spaces/join            # ← 固定路由，必须在前
GET  /spaces/{space_id}      # ← 参数路由，放后面
POST /spaces/{space_id}/join-public
```

### asyncpg 参数规范

- 所有 UUID 写入必须加 `CAST(:x AS uuid)`
- 同一 SQL 语句中，每个参数名必须唯一（asyncpg 无法推断重复参数类型）

```python
# 错误：:tk 出现 3 次
INSERT ... VALUES (:tk, ..., :tk, ..., :tk, ...)

# 正确：拆分为独立参数
INSERT ... VALUES (:tk, ..., :title, ..., :goal, ...)
{"tk": topic_key, "title": topic_key, "goal": topic_key}
```

### LLM 超时规范

| 路由类型 | 超时 |
|:---|:---|
| `tutorial_content` / `blueprint_synthesis` / `coherence_eval` | 120s |
| 其他 | 30s |

新增耗时路由需加入 `llm_gateway.py` 中的 `_LONG_TIMEOUT_ROUTES`，禁止修改全局默认值。

### space_id 可选参数

以下接口均支持可选 `space_id` query 参数：

- `GET /tutorials/topic/{topic_key}`
- `POST /teaching/conversations`
- `GET /teaching/conversations`
- `GET /learners/me/repair-path`

---

## 7. 前端说明

### 技术栈

- Vue 3 + TypeScript + Vite
- Element Plus UI 组件库
- Pinia 状态管理
- axios（统一封装在 `src/api/index.ts`）

### 构建与部署

前端由 nginx 托管编译后的 `dist/`，**源码修改后必须重新 build**：

```bash
docker-compose build web && docker-compose up -d web
```

### API 调用规范

所有接口调用必须通过 `src/api/index.ts` 导出的模块，禁止直接 `import axios`。

```typescript
// 正确
import { spaceApi, teachingApi } from '@/api'

// 错误
import axios from 'axios'
```

### 剪贴板 API

HTTP 环境（非 HTTPS）下 `navigator.clipboard` 不可用，使用 `execCommand('copy')` fallback：

```typescript
const el = document.createElement('textarea')
el.value = text
document.body.appendChild(el)
el.select()
document.execCommand('copy')
document.body.removeChild(el)
```

### 菜单路由结构

| 路径 | 页面 | 权限 |
|:---|:---|:---|
| `/tutorial` | 学习（教程） | 已登录 |
| `/chat` | AI 对话 | 已登录 |
| `/gaps` | 薄弱环节分析 | 已登录 |
| `/spaces` | 课程信息 | 已登录 |
| `/upload` | 资料库 | 已登录 |
| `/notes` | 我的笔记 | 已登录 |
| `/discuss` | 讨论区 | 已登录 |
| `/community` | 发现课程 | 已登录 |
| `/profile` | 账号设置 | 已登录 |
| `/admin` | 管理后台 | 管理员 |

---

## 8. 开发约定 Checklist

- [ ] **裸 SQL，无 ORM**：迁移写 `.sql` 放 `migrations/`，按序号命名
- [ ] **asyncpg UUID**：写入侧一律 `CAST(:x AS uuid)`
- [ ] **asyncpg 参数唯一**：同一 SQL 中参数名不重复
- [ ] **axios 拦截器**：`res.data` 即 payload，勿写 `res.data.data`
- [ ] **固定路由在参数路由之前注册**
- [ ] **LLM 耗时路由**：加入 `_LONG_TIMEOUT_ROUTES`，不改全局超时
- [ ] **重型 Celery 任务必须加幂等锁**
- [ ] **禁用 `--without-heartbeat`**
- [ ] **禁止直接修改 `task_acks_late` 全局配置**
- [ ] **RabbitMQ 队列属性变更**：先 `delete_queue` 再重启 worker
- [ ] **前端源码修改后必须 rebuild**（nginx 托管 dist）

---

## 9. 常用诊断命令

```bash
# 查看某空间处理进度
docker-compose exec postgres psql -U user -d adaptive_learning -c "
  SELECT
    (SELECT COUNT(*) FROM knowledge_entities WHERE space_id='SPACE_ID') AS total,
    (SELECT COUNT(*) FROM knowledge_entities WHERE space_id='SPACE_ID' AND review_status='approved') AS approved,
    (SELECT status FROM skill_blueprints WHERE space_id='SPACE_ID' LIMIT 1) AS bp_status,
    (SELECT error_message FROM skill_blueprints WHERE space_id='SPACE_ID' LIMIT 1) AS bp_error;
" -P pager=off

# 查看所有 failed blueprint
docker-compose exec postgres psql -U user -d adaptive_learning -c \
  "SELECT topic_key, status, error_message, updated_at FROM skill_blueprints WHERE status='failed';" -P pager=off

# chunk embedding 进度
docker-compose exec postgres psql -U user -d adaptive_learning -c "
  SELECT d.title, COUNT(dc.chunk_id) AS total, COUNT(dc.embedding) AS with_emb
  FROM documents d JOIN document_chunks dc ON dc.document_id=d.document_id
  GROUP BY d.title ORDER BY total DESC LIMIT 10;
" -P pager=off

# RabbitMQ 队列积压
docker-compose exec rabbitmq rabbitmqctl list_queues name messages consumers 2>/dev/null

# API 错误日志
docker-compose logs api --tail=50 | grep -E "error|Error|500"

# knowledge worker 实时日志
docker-compose logs celery_worker_knowledge -f

# review worker 实时日志
docker-compose logs celery_worker_review -f

# 手动重置卡死的 generating blueprint
docker-compose exec postgres psql -U user -d adaptive_learning -c \
  "UPDATE skill_blueprints SET status='draft', updated_at=now()
   WHERE status='generating' AND updated_at < now() - interval '2 hours';" -P pager=off

# 连接数据库
docker-compose exec postgres psql -U user -d adaptive_learning
```

---

*文档版本：v1.0*
*更新时间：2026-04-22*
