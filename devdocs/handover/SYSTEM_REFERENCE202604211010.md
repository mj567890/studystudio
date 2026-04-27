# StudyStudio 系统参考手册

> 最后更新：2026-04-20 — Blueprint V2 质量修复、LLMGateway 根因修复、space_id 全线贯通、账号功能完善

---

## 一、服务架构

| 服务 | 作用 | 端口 |
|------|------|------|
| `api` | FastAPI 后端 | 8000 |
| `web` | Vue 前端 nginx | 3000 |
| `celery_worker` | tutorial / low_priority 队列 | - |
| `celery_worker_knowledge` | knowledge 队列 | - |
| `celery_beat` | 定时任务（含 resume_pending_review） | - |
| `postgres` | 主数据库（含 pgvector） | 5432 |
| `rabbitmq` | 消息队列 | 5672, 15672 |
| `redis` | 缓存 | 6379 |
| `minio` | 对象存储 | 9000, 9001 |

**前端构建与部署（Docker 镜像模式，当前环境）：**

```powershell
# 在项目目录 D:\studystudio 的 PowerShell 中运行
docker compose up -d --no-deps --build web
```

> 注意：web 容器无源码 volume 挂载，修改前端后必须重建镜像。
> 旧方式（`npm run build + docker compose cp`）仅适用于有 volume 挂载的部署，当前不适用。

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

- `--heartbeat-interval=10`：每 10 秒探测连接，断了立即重连
- `--prefetch-multiplier=1`：knowledge 任务耗时长，每次只取一条防超时
- `consumer_timeout=28800000`：RabbitMQ ACK 超时改为 8 小时
- `restart: unless-stopped`：容器崩溃自动重启
- **绝对禁用 `--without-heartbeat`**

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

### visibility 字段（用户可见）
- `private`：仅自己
- `shared`：凭邀请码加入
- `public`：出现在发现页，可无码加入

### space_type 字段（内部，用户不可见）
数据库保留但前端不展示。当前所有 space 均为 `personal`。

### 路由注册顺序（重要，违反会 422）
固定路径必须在路径参数之前：
1. `GET  /spaces/public`           发现课程
2. `POST /spaces/join`             邀请码加入
3. `GET  /spaces/{space_id}`
4. `POST /spaces/{space_id}/join-public`  公开无码加入
5. 其他 `/spaces/{space_id}/xxx`

### 删除 space 的正确顺序
先删 `skill_blueprints`（space_id 有非空约束），再删 `knowledge_spaces`。

---

## 五、Blueprint V2 规范

### Feature Flag
`BLUEPRINT_V2_ENABLED=true`（docker-compose.yml 环境变量）

### V2 生成流程
1. 实体 embedding → KMeans 聚类
2. `_rebalance_clusters`：超大簇（>12）拆分，过小簇（<3）合并
3. 每簇调 LLM 命名章节（`CLUSTER_CHAPTER_PROMPT`）
4. 全局调一次 LLM 做 Stage 规划 + 动词去重（`STAGE_PLANNING_PROMPT`）
5. 每章调 LLM 生成内容（`CHAPTER_CONTENT_PROMPT`）
6. blueprint 发布后异步预生成测验（`pregen_chapter_quizzes`）

### V2 内容字段
- `full_content`：600-900 字，含 CHECKPOINT 标记
- `code_example`：涉及编程/命令行时必填，`<pre><code class="language-xxx">` 格式
- `if_high`：高阶补充，100 字以内

### 回滚方式
删除 `BLUEPRINT_V2_ENABLED=true`，重启 `celery_worker_knowledge`，V1 自动重新生成。

### LLM 超时规范
`llm_gateway.py` 按 `model_route` 分级：
- `tutorial_content` / `blueprint_synthesis` / `coherence_eval`：120s
- 其他：30s

**新增耗时路由时**，把 route name 加入 `_LONG_TIMEOUT_ROUTES` 集合，不要修改全局默认值。

---

## 六、接口规范

### 统一响应格式
```json
{"code": 200, "msg": "success", "data": {...}}
```
前端 axios 拦截器已拆一层：`res.data` = payload，组件里不写 `res.data.data`。

### space_id 参数
以下接口均支持可选的 `space_id` query 参数：
- `GET /tutorial/{topic_key}`
- `POST /conversations`
- `GET /conversations`
- `POST /chat/{topic_key}`
- `GET /repair-path/{topic_key}`

### 主要接口清单（space 相关）

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | /api/spaces | 创建空间 |
| GET | /api/spaces | 列出我的空间（含加入的） |
| GET | /api/spaces/public | 发现页：所有 visibility=public 课程 |
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
| GET | /api/spaces/{id}/entities | 空间知识点列表 |
| GET | /api/spaces/{id}/blueprint | 空间 blueprint |
| GET | /api/spaces/{id}/chapters | 空间章节列表 |
| GET | /api/spaces/{id}/export | 导出空间 |
| POST | /api/spaces/import | 导入空间 |

### 主要接口清单（账号相关）

| 方法 | 路径 | 说明 |
|------|------|------|
| PATCH | /api/users/me | 更新昵称/头像 |
| POST | /api/users/me/avatar | 上传头像（MultipartFile） |
| POST | /api/users/me/change-password | 修改密码 |
| DELETE | /api/users/me | 账号注销（软删除） |

### 主要接口清单（管理员）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /api/admin/courses | 列出所有有 blueprint 的课程（含章节数统计） |
| GET | /api/admin/spaces | 所有空间列表 |

---

## 七、定时任务（celery_beat）

| 任务 | 间隔 | 说明 |
|------|------|------|
| `check_dlq` | 5 分钟 | 检查死信队列积压 |
| `resume_pending_review` | 5 分钟 | 续接审核 + 触发缺失 blueprint |

手动触发审核续接：
```python
from apps.api.tasks.auto_review_tasks import auto_review_entities
auto_review_entities.apply_async(args=['SPACE_ID'], queue='knowledge')
```

---

## 八、关键数据表速查

### 核心流程表
| 表名 | 说明 |
|------|------|
| `knowledge_spaces` | 知识空间（含 visibility / invite_code / fork_from_space_id） |
| `space_members` | 空间成员关系（owner/admin/member） |
| `documents` | 上传文档 |
| `knowledge_entities` | 知识实体（含 embedding） |
| `skill_blueprints` | 课程蓝图（含 space_id / status） |
| `skill_stages` | 学习阶段 |
| `skill_chapters` | 章节（含 content_text / code_example） |
| `chapter_entity_links` | 章节-实体关联（link_type: core_term / related） |
| `conversations` | 对话（含 space_id） |
| `chapter_progress` | 章节完成进度 |
| `chapter_progress_entities` | 章节完成时快照的实体（幂等写入） |
| `learner_knowledge_states` | 实体掌握度（mastery_score 0~0.9） |
| `chapter_quizzes` | 预生成测验题（含 ai_rubric） |
| `fork_tasks` | 异步 fork 任务状态 |

### 待建表（Phase 3a）
| 表名 | 说明 |
|------|------|
| `course_posts` | 课程帖子（绑 space_id / chapter_id） |
| `course_post_replies` | 帖子回复（一层） |

---

## 九、开发规范 Checklist

- **raw SQL，无 ORM**：迁移写 `.sql` 放 `migrations/`，按序号命名
- **asyncpg 类型转换**：写入侧一律 `CAST(:x AS uuid)`
- **SQL 参数名一致**：`:user_id` 对应 `{"user_id": ...}`
- **rubric prompt 大括号**：用 `.replace()` 不用 `.format()`
- **axios 拦截器已剥一层**：`res.data` = payload，不写 `res.data.data`
- **前端剪贴板**：HTTP 环境下 `navigator.clipboard` 不可用，必须 `execCommand('copy')` fallback
- **Admin 组件禁止直接 `import axios`**：必须用带 Authorization 拦截器的实例，否则 HTTPBearer 返回 403
- **getDomains 统计字段必须真实查询**：admin/router.py 禁止硬编码为 0
- **Vue ref null 需显式泛型**：`ref<any>(null)` 或具体类型
- **固定路由在参数路由之前注册**（见第四节）
- **LLM 新增耗时路由**加入 `_LONG_TIMEOUT_ROUTES`（见第五节）

---

## 十、常用诊断命令

```bash
# 查看所有公开课程
docker compose exec postgres psql -U user -d adaptive_learning -c \
  "SELECT space_id, name, visibility FROM knowledge_spaces WHERE visibility='public';"

# 查看某空间处理进度
docker compose exec postgres psql -U user -d adaptive_learning -c "
  SELECT
    (SELECT COUNT(*) FROM knowledge_entities ke WHERE ke.space_id='SPACE_ID') AS total,
    (SELECT COUNT(*) FROM knowledge_entities ke WHERE ke.space_id='SPACE_ID' AND review_status='approved') AS approved,
    (SELECT status FROM skill_blueprints sb WHERE sb.space_id='SPACE_ID' LIMIT 1) AS bp_status;
"

# 知识点审核进度
docker compose exec postgres psql -U user -d adaptive_learning -c \
  "SELECT review_status, COUNT(*) FROM knowledge_entities WHERE space_id='SPACE_ID' GROUP BY review_status;"

# RabbitMQ 队列积压
docker compose exec rabbitmq rabbitmqctl list_queues name messages consumers

# API 错误日志
docker compose logs api --tail=50 | grep -E "error|Error|500"

# knowledge worker 实时日志
docker compose logs celery_worker_knowledge -f | grep -E "start|done|error|approved|resume"

# beat 触发日志
docker compose logs celery_beat --tail=20 | grep -E "Sending|due task"

# 清空测验题目缓存（重新生成）
docker compose exec postgres psql -U user -d adaptive_learning -c "DELETE FROM chapter_quizzes;"

# 查看 blueprint 版本
docker compose exec postgres psql -U user -d adaptive_learning -c \
  "SELECT topic_key, status, version, updated_at FROM skill_blueprints ORDER BY updated_at DESC LIMIT 10;"

# 查看章节掌握度分布
docker compose exec postgres psql -U user -d adaptive_learning -c \
  "SELECT user_id, COUNT(*), AVG(mastery_score)::numeric(4,2) FROM learner_knowledge_states GROUP BY user_id;"
```

---

*文档版本：v3.0*
*生成时间：2026-04-20*
