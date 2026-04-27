# StudyStudio 系统参考手册

> 本次更新：测验系统、AI批改、上传体验、Worker稳定性、auto_review续接机制。

---

## 一、服务架构

| 服务 | 作用 | 端口 |
|------|------|------|
| `api` | FastAPI 后端 | 8000 |
| `web` | Vue 前端 nginx | 3000 |
| `celery_worker` | tutorial/low_priority 队列 | - |
| `celery_worker_knowledge` | knowledge 队列 | - |
| `celery_beat` | 定时任务（含 resume_pending_review） | - |
| `postgres` | 主数据库（含 pgvector） | 5432 |
| `rabbitmq` | 消息队列 | 5672, 15672 |
| `redis` | 缓存 | 6379 |
| `minio` | 对象存储 | 9000, 9001 |

前端构建（宿主机执行）：

    cd apps/web && npm run build
    cd ~/studystudio
    docker compose cp apps/web/dist/. web:/usr/share/nginx/html/

DB 连接：`docker compose exec postgres psql -U user -d adaptive_learning`

---

## 二、Worker 稳定性配置（重要，禁止违反）

```yaml
# celery_worker_knowledge
command: celery ... --heartbeat-interval=10 --prefetch-multiplier=1
restart: unless-stopped

# celery_worker
command: celery ... --heartbeat-interval=10
restart: unless-stopped

# rabbitmq
environment:
  RABBITMQ_SERVER_ADDITIONAL_ERL_ARGS: "-rabbit consumer_timeout 28800000"
```

**原理：**
- `--heartbeat-interval=10`：每 10 秒探测连接，断了立即重连
- `--prefetch-multiplier=1`：knowledge 队列任务耗时长，每次只取一条防止超时
- `consumer_timeout=28800000`：RabbitMQ ACK 超时改为 8 小时
- `restart: unless-stopped`：容器崩溃自动重启
- **绝对禁用 `--without-heartbeat`**

**诊断积压：**

    docker compose exec rabbitmq rabbitmqctl list_queues name messages consumers

`messages > 0` 且 `consumers = 0` → worker 断线，重启 `celery_worker_knowledge`。

---

## 三、定时任务（celery_beat）

| 任务 | 间隔 | 说明 |
|------|------|------|
| check_dlq | 5分钟 | 检查死信队列积压 |
| resume_pending_review | 5分钟 | 检查所有有 pending 实体的 space，自动续接中断的审核链 |

`resume_pending_review` 是关键容灾机制——即使 worker 重启导致 `auto_review_entities` 任务链断裂，最多 5 分钟后会自动恢复，无需人工干预。

---

## 四、上传 → 课程生成流程

```
用户上传文件
  → POST /api/spaces
  → file_uploaded 事件
  → run_ingest（knowledge）：文件解析 → document_parsed 事件
  → run_extraction（knowledge）：知识点提取 → auto_review_entities
  → auto_review_entities（knowledge）：两轮 LLM 审核，LIMIT 100/批，自触发续接
    （如中断，resume_pending_review 每 5 分钟自动恢复）
  → synthesize_blueprint（knowledge）：生成 blueprint + 章节内容
  → blueprint.status = published
  → pregen_chapter_quizzes（knowledge，countdown=10s）：预生成题目
```

**时间估算（前端动态显示）：**
- < 1MB：5~10 分钟
- 1~5MB：10~20 分钟
- 5~20MB：20~40 分钟
- > 20MB：1 小时以上

---

## 五、测验系统

### 流程
1. 用户点"📝 做测验" → `GET /api/learners/me/chapter-quiz/{chapter_id}`
2. 有缓存直接返回；无缓存即时生成（LLM，约 10~30 秒）
3. 客观题前端判对错，简答题点"AI 批改" → `POST /api/learners/me/rubric-check`
4. 提交 → `POST /api/learners/me/chapter-quiz/submit`：按知识点更新 mastery_score（答对 +0.2，答错 -0.1）
5. 得分 ≥ 60 自动标记章节已读，章节标题旁显示"🎉 已完成"

### AI 批改关键规范
- prompt 用 `.replace("{rubric}", val)` 不用 `.format()`
- LLM 返回 JSON 解析前：`.replace("{{","{").replace("}}","}")`
- score 强制 `float()`，is_correct 用 `score >= 0.6`

### 题目缓存
存在 `chapter_quizzes` 表。清空重生成：`DELETE FROM chapter_quizzes`。

---

## 六、关键数据表

### users
status：active / disabled / deleted（Migration 010）

### skill_chapters.content_text（JSON）
scene_hook、skim_summary、full_content（含 CHECKPOINT）、misconception_block、prereq_adaptive.if_high

### chapter_quizzes
题目类型：single_choice（60%）、true_false（20%）、fill_blank（20%，含 ai_rubric）

---

## 七、账号相关接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /api/users/me | 获取当前用户 |
| PATCH | /api/users/me | 更新昵称/avatar_url |
| POST | /api/users/me/avatar | 上传头像（multipart，限 5MB） |
| POST | /api/users/me/password | 修改密码 |
| DELETE | /api/users/me | 注销账号（软删除） |

---

## 八、常见坑位

**asyncpg 类型转换：** 写入侧一律 CAST(:x AS uuid)。

**SQL 参数名必须一致：** `:user_id` 对应 `{"user_id": ...}`，不能用 `{"uid": ...}`。

**rubric prompt 大括号：** 用 `.replace()` 不用 `.format()`，LLM 返回双括号需 unescape。

**getDomains 不得硬编码：** admin/router.py 统计字段必须真实查询。

**axios 拦截器已剥一层：** `res.data` = payload，不写 `res.data.data`。

**auto_review 任务链：** 靠 `apply_async(countdown=3)` 自续，worker 重启会断。已有 `resume_pending_review` 兜底，无需担心。

---

## 九、常用诊断命令

```bash
# 查看某空间处理进度
docker compose exec postgres psql -U user -d adaptive_learning -c "
  SELECT d.document_status,
    (SELECT COUNT(*) FROM knowledge_entities ke WHERE ke.space_id=d.space_id) AS total,
    (SELECT COUNT(*) FROM knowledge_entities ke WHERE ke.space_id=d.space_id AND review_status='approved') AS approved,
    (SELECT status FROM skill_blueprints sb WHERE sb.space_id=d.space_id LIMIT 1) AS bp_status
  FROM documents d WHERE d.space_id = 'SPACE_ID'::uuid;
"

# 知识点审核进度
docker compose exec postgres psql -U user -d adaptive_learning -c "
  SELECT review_status, COUNT(*) FROM knowledge_entities
  WHERE space_id='SPACE_ID' GROUP BY review_status;
"

# 手动触发审核（通常不需要，beat 会自动续接）
docker compose exec -T api python3 -c "
from apps.api.tasks.auto_review_tasks import auto_review_entities
auto_review_entities.apply_async(args=['SPACE_ID'], queue='knowledge')
"

# RabbitMQ 队列积压
docker compose exec rabbitmq rabbitmqctl list_queues name messages consumers

# 清空测验题目缓存
docker compose exec postgres psql -U user -d adaptive_learning -c "DELETE FROM chapter_quizzes;"

# API 错误日志
docker compose logs api --tail=50 | grep -E "error|Error|500"

# knowledge worker 实时日志
docker compose logs celery_worker_knowledge -f | grep -E "start|done|error|approved|resume"
```

---

## 十、回滚方案

账号注销 Migration（010）：

    ALTER TABLE users DROP CONSTRAINT users_status_check;
    ALTER TABLE users ADD CONSTRAINT users_status_check
      CHECK (status::text = ANY (ARRAY['active'::text, 'disabled'::text]::text[]));

Worker 配置回滚：用 `docker-compose.yml.bak.*` 恢复，重启对应服务。

Phase 1 space 功能：

    docker compose exec -T postgres psql -U user -d adaptive_learning \
      -f - < migrations/003_social_learning_phase1_rollback.sql

---

## 十一、Fork 功能

- POST /api/spaces/{space_id}/fork → { task_id, target_space_id }
- GET /api/fork-tasks/{task_id} → { status, error_msg }
- 关键文件：fork_tasks.py、space/repository.py、service.py、router.py

回滚：

    DROP TABLE IF EXISTS fork_tasks;
    ALTER TABLE knowledge_spaces DROP COLUMN IF EXISTS fork_from_space_id;
