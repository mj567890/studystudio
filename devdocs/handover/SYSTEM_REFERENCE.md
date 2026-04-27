# StudyStudio 系统参考手册

> 最后更新：2026-04-22 — Blueprint 竞态锁修复 + discuss Bug 修复 + 课程跳转修复 + celery_worker_review

---

## 一、服务架构

| 服务 | 作用 | 端口 |
|------|------|------|
| `api` | FastAPI 后端 | 8000 |
| `web` | Vue 前端 nginx（托管 dist） | 3000 |
| `celery_worker` | tutorial / low_priority 队列 | - |
| `celery_worker_knowledge` | knowledge / blueprint.synthesis 队列，并发 8 | - |
| `celery_worker_review` | knowledge.review 队列，并发 2（审核专用，防饿死）| - |
| `celery_beat` | 定时任务（resume_pending_review 每 5 分钟） | - |
| `postgres` | 主数据库（含 pgvector） | 5432 |
| `rabbitmq` | 消息队列 | 5672, 15672 |
| `redis` | 缓存 | 6379 |
| `minio` | 对象存储 | 9000, 9001 |

**前端重新构建：**
```bash
docker-compose build web && docker-compose up -d web
```

**连接数据库：**
```bash
docker-compose exec postgres psql -U user -d adaptive_learning
```

---

## 二、Worker 稳定性配置（禁止违反）

```yaml
celery_worker_knowledge:
  command: celery ... --heartbeat-interval=10 --prefetch-multiplier=1
  restart: unless-stopped

celery_worker:
  command: celery ... --heartbeat-interval=10
  restart: unless-stopped

celery_worker_review:
  command: celery ... --heartbeat-interval=10 --prefetch-multiplier=1
  restart: unless-stopped

rabbitmq:
  environment:
    RABBITMQ_SERVER_ADDITIONAL_ERL_ARGS: "-rabbit consumer_timeout 28800000"
```

- **绝对禁用 `--without-heartbeat`**
- `--prefetch-multiplier=1`：knowledge 类任务耗时长，每次只取一条
- `consumer_timeout=28800000`：ACK 超时 8 小时

---

## 三、前端菜单结构（当前）

```
学习        /tutorial
AI 对话     /chat
薄弱环节    /gaps
课程信息    /spaces
资料库      /upload
我的笔记    /notes
讨论        /discuss
发现课程    /community
账号设置    /profile
管理后台    /admin（仅管理员）
```

---

## 四、Space 相关规范

### visibility 字段
- `private`：仅自己
- `shared`：凭邀请码加入
- `public`：出现在发现页，可无码加入

### space_type 字段
内部保留，前端不展示。当前所有 space 均为 `personal`。

### 路由注册顺序（违反会 422）
1. `GET  /spaces/public`
2. `POST /spaces/join`
3. `GET  /spaces/{space_id}`
4. `POST /spaces/{space_id}/join-public`

---

## 五、Blueprint V2 规范

### Feature Flag
`BLUEPRINT_V2_ENABLED=true`（docker-compose.yml）

### V2 生成流程
1. 实体 embedding → KMeans 聚类
2. `_rebalance_clusters`：超大簇拆分，过小簇合并
3. 每簇调 LLM 命名章节
4. 全局调一次 LLM 做 Stage 规划 + 动词去重
5. 每章调 LLM 生成内容
6. 发布后异步预生成测验

### Blueprint 任务保障机制

```
任务开始 → _check_blueprint_lock()
         → generating 且 < 2h → 直接退出（幂等）
         → 否则 → 正常执行

执行成功 → status = published
执行失败 → retry（最多 2 次）
         → 耗尽 → on_failure → status = failed，error_message 记录原因

resume_pending_review（每 5 分钟，queue=knowledge.review）：
  → generating 超 2h → 重置为 draft → 重触发
  → failed / 无 blueprint → 重触发
  → parsed 且无实体 → 重触发提取任务
```

**禁止修改 `task_acks_late=True` 全局配置**，重型任务用幂等锁解决重投问题。

### Blueprint status 枚举
`draft` / `generating` / `review` / `published` / `archived` / `failed`

`failed` 状态：`error_message` 字段记录原因，`resume_pending_review` 自动重触发。

### LLM 超时规范
- `tutorial_content` / `blueprint_synthesis` / `coherence_eval`：120s
- 其他：30s

新增耗时路由时加入 `_LONG_TIMEOUT_ROUTES`，不修改全局默认值。

---

## 六、接口规范

### 统一响应格式
```json
{"code": 200, "msg": "success", "data": {...}}
```
前端 axios 拦截器已拆一层：`res.data` = payload，不写 `res.data.data`。

### asyncpg 参数规范

**UUID 写入必须 CAST：**
```sql
WHERE space_id = CAST(:sid AS uuid)
```

**同一 SQL 参数名必须唯一（重要！）**

asyncpg 无法推断同名参数的类型，会抛 `AmbiguousParameterError`。

```python
# 错误：:tk 出现 3 次
INSERT INTO skill_blueprints (topic_key, title, skill_goal)
VALUES (:tk, :tk, :tk)    -- ← 报 AmbiguousParameterError

# 正确：每个参数使用唯一名称
INSERT INTO skill_blueprints (topic_key, title, skill_goal)
VALUES (:tk, :title, :goal)
{"tk": topic_key, "title": topic_key, "goal": topic_key}
```

### source 接口向量检索逻辑
`GET /api/teaching/chapters/{chapter_id}/source`

1. 取章节实体 canonical_name（最多 8 个，core_term 优先）
2. embed query → 向量检索同 space chunks
3. 同 space 无结果 → 向量检索全局
4. 无向量（embedding IS NULL）→ fallback ILIKE 关键词检索

### space_id 参数
以下接口均支持可选 `space_id` query 参数：
- `GET /tutorials/topic/{topic_key}`
- `POST /conversations`
- `GET /conversations`
- `GET /repair-path`

### 主要接口清单（space 相关）

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | /api/spaces | 创建空间 |
| GET | /api/spaces | 列出我的空间（含加入的） |
| GET | /api/spaces/public | 发现页 |
| POST | /api/spaces/join | 邀请码加入 |
| GET | /api/spaces/{id} | 空间详情 |
| PATCH | /api/spaces/{id} | 修改名称/描述/visibility |
| POST | /api/spaces/{id}/join-public | 公开课程无码加入 |
| GET | /api/spaces/{id}/members | 成员列表 |
| DELETE | /api/spaces/{id}/members/{uid} | 移除成员 |
| POST | /api/spaces/{id}/invite-code | 生成邀请码 |
| DELETE | /api/spaces/{id}/invite-code | 撤销邀请码 |
| POST | /api/spaces/{id}/fork | Fork 空间（异步） |
| GET | /api/fork-tasks/{task_id} | 查询 fork 任务状态 |

### 主要接口清单（discuss 课程讨论区）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /api/discuss/spaces/{space_id}/posts | 帖子列表（支持 chapter_id / post_type 过滤） |
| POST | /api/discuss/spaces/{space_id}/posts | 创建帖子 |
| DELETE | /api/discuss/posts/{post_id} | 删除帖子（仅本人） |
| GET | /api/discuss/posts/{post_id}/replies | 回复列表 |
| POST | /api/discuss/posts/{post_id}/replies | 创建回复 |
| DELETE | /api/discuss/replies/{reply_id} | 删除回复（仅本人） |
| GET | /api/discuss/feed | 跨 space 聚合动态 |

### 主要接口清单（账号相关）

| 方法 | 路径 | 说明 |
|------|------|------|
| PATCH | /api/users/me | 更新昵称/头像 |
| POST | /api/users/me/avatar | 上传头像 |
| POST | /api/users/me/password | 修改密码 |
| DELETE | /api/users/me | 账号注销（软删除） |

---

## 七、定时任务（celery_beat）

| 任务 | 间隔 | 队列 | 说明 |
|------|------|------|------|
| `resume_pending_review` | 5 分钟 | `knowledge.review` | 续接审核 + 触发缺失 blueprint + 重置超时 generating |
| `check_dlq` | 5 分钟 | — | 检查死信队列积压 |

---

## 八、关键数据表速查

| 表名 | 说明 |
|------|------|
| `knowledge_spaces` | 知识空间（含 visibility / invite_code） |
| `space_members` | 空间成员关系 |
| `documents` | 上传文档（status: uploaded/parsed/extracted/embedding/reviewed） |
| `document_chunks` | 文档分块（embedding vector(1024)、page_no） |
| `knowledge_entities` | 知识实体（含 embedding） |
| `skill_blueprints` | 课程蓝图（status 含 failed，error_message 字段） |
| `skill_stages` | 学习阶段 |
| `skill_chapters` | 章节（含 content_text / code_example） |
| `chapter_entity_links` | 章节-实体关联（core_term / related） |
| `conversations` | 对话（含 space_id） |
| `chapter_progress` | 章节完成进度 |
| `chapter_progress_entities` | 章节完成时快照的实体 |
| `learner_knowledge_states` | 实体掌握度（mastery_score 0~0.9） |
| `chapter_quizzes` | 预生成测验题（含 ai_rubric） |
| `fork_tasks` | 异步 fork 任务状态 |
| `course_posts` | 课程讨论帖（绑 space_id / chapter_id，post_type: note/question/discussion） |
| `course_post_replies` | 帖子回复（一层，含 reply_count 冗余计数） |

---

## 九、Migrations 清单

| 编号 | 文件 | 内容 |
|------|------|------|
| 001 | initial_schema.sql | 初始 31 张表 |
| 002 | ai_config.sql | AI 配置表 |
| 003 | social_learning_phase1.sql | 多成员 space + 邀请码 |
| 005 | space_subscriptions.sql | 话题订阅 |
| 006 | phase3_topic_key_fork.sql | Topic Key Fork |
| 007 | tutorial_skeletons_space_id.sql | 教程骨架支持 space_id |
| 008 | community_curations.sql | 社区策展 |
| 009 | fork_space.sql | Fork 空间异步任务 |
| 010 | account_deactivation.sql | 账号注销软删除 |
| 011 | wall_posts_space_id.sql | 讨论帖按 space 隔离 |
| 012 | blueprint_failed_status.sql | blueprint failed 状态 + error_message 字段 |
| 013 | course_posts.sql | 课程讨论区建表（course_posts / course_post_replies） |

---

## 十、开发规范 Checklist

- **raw SQL，无 ORM**：迁移写 `.sql` 放 `migrations/`，按序号命名
- **asyncpg UUID**：写入侧一律 `CAST(:x AS uuid)`
- **asyncpg 参数名唯一**：同一 SQL 中不允许重复参数名，否则 AmbiguousParameterError
- **axios 拦截器已剥一层**：`res.data` = payload，不写 `res.data.data`
- **前端 clipboard**：HTTP 环境下用 `execCommand('copy')` fallback
- **Admin 组件禁止直接 `import axios`**：用带 Authorization 拦截器实例
- **固定路由在参数路由之前注册**
- **LLM 新增耗时路由**加入 `_LONG_TIMEOUT_ROUTES`
- **重型 Celery 任务必须加幂等锁**，不依赖 `task_acks_late` 保证唯一性
- **RabbitMQ 队列属性变更**：先 `delete_queue` 再重启 worker
- **前端源码修改后必须 rebuild**（nginx 托管 dist）

---

## 十一、常用诊断命令

```bash
# 查看某空间处理进度（含 blueprint 失败信息）
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
docker-compose exec api tail -100 /tmp/api.log 2>/dev/null || docker-compose logs api --tail=50 | grep -E "error|Error|500"

# knowledge worker 实时日志
docker-compose logs celery_worker_knowledge -f | grep -E "start|done|error|approved|resume|lock|failed"

# review worker 实时日志
docker-compose logs celery_worker_review -f

# 手动触发 chunk embedding
docker-compose exec -T api python3 -c "
from apps.api.tasks.embedding_tasks import embed_document_chunks
embed_document_chunks.apply_async(args=['DOCUMENT_ID'], queue='knowledge')
print('dispatched')
"

# 手动重置卡死的 generating blueprint
docker-compose exec postgres psql -U user -d adaptive_learning -c \
  "UPDATE skill_blueprints SET status='draft', updated_at=now()
   WHERE status='generating' AND updated_at < now() - interval '2 hours';" -P pager=off

# 查看 blueprint 版本和状态
docker-compose exec postgres psql -U user -d adaptive_learning -c \
  "SELECT topic_key, status, version, error_message, updated_at
   FROM skill_blueprints ORDER BY updated_at DESC LIMIT 10;" -P pager=off

# 清空 knowledge 队列积压（谨慎使用）
docker-compose exec rabbitmq rabbitmqctl purge_queue knowledge

# 清空测验题目缓存
docker-compose exec postgres psql -U user -d adaptive_learning -c \
  "DELETE FROM chapter_quizzes;" -P pager=off
```

---

*文档版本：v5.0*
*生成时间：2026-04-22*
