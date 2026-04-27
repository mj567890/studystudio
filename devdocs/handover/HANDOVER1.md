# StudyStudio 会话交接文档

**生成日期：** 2026-04-19（更新：2026-04-19 第三次追加）
**上次会话主题：** 测验系统 + AI批改 + 上传体验 + Worker稳定性 → SystemHealthView TS修复 + UI重设计 → 章节内容质量提升 + 课程管理 Web 页面

---

## 一、历史完成工作（已稳定）

### Phase 1~4（略，见旧文档）

### 账号管理功能
- POST /api/users/me/avatar：头像上传到 MinIO
- DELETE /api/users/me：账号注销软删除，Migration 010

### 新用户体验改进
- 首页新用户引导卡片
- 上传后 blueprint 就绪轮询
- 上传表单简化

### 测验系统完善（本次）
- 章节标题旁"📝 做测验"按钮，完成后显示"🎉 已完成"标签
- 测验得分 ≥ 60 自动标记章节已读，联动 mastery_score 更新
- 提交后显示答题回顾（每题对错 + 正确答案 + 解析，支持滚动）
- 得分 < 60 时显示"仍然标记已读"选项
- 页面加载时立即拉取进度，刷新后侧边栏立即显示 ✓
- blueprint 发布后异步预生成章节测验题（pregen_chapter_quizzes）
- QUIZ_GENERATION_PROMPT 加入 ai_rubric 字段
- AI 批改三重修复（见第二节）

### 上传页体验改进（本次）
- 处理流程步骤条（4个阶段图标）
- 各阶段进度提示：排队中动画条、解析中片段数、审核中 approved/total 进度条
- 文件大小动态估算处理时间
- 按钮"查看"改为"打开原文"
- 下拉列表显示所有课程（不按 spaceType 过滤）
- getDomains 接口实体数量从硬编码 0 改为真实查询

### Worker 稳定性修复（本次，重要）
- 去掉 `--without-heartbeat`，改为 `--heartbeat-interval=10`
- celery_worker_knowledge 加 `--prefetch-multiplier=1`
- RabbitMQ 加 `consumer_timeout=28800000`（8小时）
- celery_worker_knowledge 加 `restart: unless-stopped`
- **新增 `resume_pending_review` 定时任务**：每 5 分钟由 beat 触发，检查所有有 pending 实体的 space，自动续接中断的审核链，彻底解决 worker 重启后任务链断掉的问题

---

## 二、本次会话 Bug 修复

### GapScanService.scan 参数名不匹配
SQL 里 `:user_id`，传参 `{"uid": user_id}` → 改为 `{"user_id": user_id}`

### AI 批改固定 50 分（三重根因）
1. `model_route="simple"` 不存在 → 改为 `teaching_chat_simple`
2. prompt 用 `.format()` 但含大括号 → 改为 `.replace()`
3. LLM 返回 `{{}}` 双大括号 → 解析前 unescape

### getDomains 下拉列表为空
SQL 硬编码 `0 AS entity_count`，dict 访问了 `row.approved_count` 导致异常 → 补全真实查询

### auto_review_entities 任务链断裂
worker 重启后 pending 实体永久停滞 → 加 `resume_pending_review` 定时巡检自动续接

---

## 二-B、本次会话工作（2026-04-19 追加）

### SystemHealthView.vue — TypeScript 编译错误修复
文件：`apps/web/src/views/admin/SystemHealthView.vue`

| 错误类型 | 根因 | 修复方式 |
|---|---|---|
| `ref(null)` 无类型推断 | 初始值 null 无泛型 | 改为 `ref<any>(null)` |
| filter/some 回调 `q` implicit any | `any` 类型数组上调用时 TS 无法推断 | 计算属性显式声明 `computed<any[]>`，回调加 `(q: any)` |
| `m[healthData.value?.overall]` 索引错误 | 字面量对象不能用 any 做 key | `m` 改为 `Record<string, string>` |
| `statusTagType/statusLabel` 参数无类型 | 函数参数隐式 any | 加 `status: string` 注解 |
| `confirmAction` 参数无类型 | 函数参数隐式 any | 加 `act: any, queueName: string` |

### SystemHealthView.vue — UI/UX 全面重设计
同一文件完整重写，保留所有业务逻辑，改动纯 UI 层：

**布局**
- Workers 列：span 8 → 6，内容更紧凑
- 队列展示：4 个独立堆叠卡片 → 单卡片 + `el-tabs`（工作/事件/死信/临时）
- 队列列宽：18（原 16）
- Header 区：状态横幅 + 操作栏合并为统一 header-panel

**视觉**
- 所有 30+ 处 inline style 移入 `<style scoped>` CSS 类
- emoji 图标（⚙📋📡💀📎🎓）替换为 Element Plus 官方 icon 组件
- 统计卡片加左侧 4px 色带状态指示（绿/橙/红）
- Worker 状态点加 CSS pulse 动画
- Tab 异常状态用 `el-badge is-dot` 角标标识

**设计参考**：Grafana/Datadog 运维监控风格

---

## 二-C、本次会话工作（2026-04-19 第三次追加）

### 章节内容质量提升

**文件：** `apps/api/tasks/blueprint_tasks.py`

- `CHAPTER_CONTENT_PROMPT` 字数要求：500字 → 600-900字
- 新增 `code_example` JSON 字段：要求 LLM 输出 `<pre><code class="language-xxx">` HTML 格式，含行注释，禁止伪代码
- `asyncio.wait_for` 超时：90s → 150s

**文件：** `apps/api/core/llm_gateway.py`

新增按 `model_route` 区分 API 调用超时：
```python
_LONG_TIMEOUT_ROUTES = {"tutorial_content", "blueprint_synthesis", "coherence_eval"}
req_timeout = 120.0 if model_route in _LONG_TIMEOUT_ROUTES else 30.0
```
传给 `chat.completions.create(timeout=req_timeout)`，解决 tutorial_content 30s 超时失败问题。

**文件：** `apps/web/src/views/tutorial/TutorialView.vue`

在正文段落后、关键词高亮前，新增 `code_example` 渲染块：
```html
<div v-if="readMode!=='skim' && chapterContent.code_example" class="code-example-block">
  <p class="section-label">💻 代码示例</p>
  <div v-html="chapterContent.code_example" class="code-example-body" />
</div>
```
加 scoped CSS：深色 pre/code 样式，inline code 浅灰背景。

---

### 课程管理 Web 页面（FE-A06）

**替代命令行操作**，管理员可在 `/admin/courses` 页面：查看所有课程内容完整度、按 stage 浏览章节、单章重生成、全量批量重生成。

#### 后端：4 个新接口（`apps/api/modules/admin/router.py` 末尾追加）

| 接口 | 说明 |
|------|------|
| `GET /admin/courses` | LATERAL JOIN 取每个 space 最新 blueprint，返回 chapter_count / content_count |
| `GET /admin/courses/{blueprint_id}/chapters` | 按 stage 分组返回章节列表，含 has_content 标志 |
| `POST /admin/courses/chapters/{chapter_id}/regenerate` | 同步调用 LLM 重生成单章，timeout=150s，直接写库 |
| `POST /admin/courses/{blueprint_id}/regenerate-all` | 派发 `regenerate_all_chapters` Celery 任务，立即返回 |

SQL 关键点：需用 `LATERAL (...LIMIT 1)` 避免 LEFT JOIN 多行问题。

#### 后端：新 Celery 任务（`apps/api/tasks/blueprint_tasks.py` 末尾追加）

```python
@celery_app.task(bind=True, max_retries=1, default_retry_delay=60)
def regenerate_all_chapters(self, blueprint_id: str):
    ...
    asyncio.run(_regenerate_all_chapters_async(blueprint_id))
```

逐章顺序处理（不并发，避免限速），每章独立 try/except + commit。

`apps/api/tasks/tutorial_tasks.py` 的 `task_routes` 中注册：
```python
"apps.api.tasks.blueprint_tasks.regenerate_all_chapters": {"queue": "knowledge"},
```

#### 前端：新文件 `apps/web/src/views/admin/CourseAdminView.vue`

- 课程列表 `el-table`（名称/类型/章节数/内容比例/更新时间/操作）
- 右侧 `el-drawer` 按 stage 折叠展示章节，标注有/无内容
- 单章重生成：`ElMessageBox.confirm` 二次确认，axios timeout 180s，完成后就地更新 `has_content`
- 全量重生成：确认后派发后台任务，立即返回

**修改 `AdminLayoutView.vue`**：菜单加「课程管理」，titleMap 加对应条目，import `Reading` 图标。

**修改 `router/index.ts`**：`/admin` children 加 `{ path: 'courses', component: ... }`。

#### 403 根因及修复

**根因**：`CourseAdminView.vue` 最初直接 `import axios` 发请求，raw axios 无 Authorization 拦截器，`HTTPBearer()` 返回 403（不是 401，不触发跳转登录）。

**修复**：组件内创建带拦截器的局部 http 实例，并将所有 4 处 `axios.get/post` → `http.get/post`，路径去掉 `/api` 前缀（baseURL 已含）：
```javascript
const http = axios.create({ baseURL: '/api', timeout: 30000 })
http.interceptors.request.use(cfg => {
  const tk = localStorage.getItem('access_token')
  if (tk) cfg.headers.Authorization = `Bearer ${tk}`
  return cfg
})
```

#### 辅助脚本

**新文件：** `scripts/regen_chapter.py` — 命令行单章重生成，用法：
```bash
docker compose exec api python3 scripts/regen_chapter.py <chapter_id>
```
注意：`get_llm_gateway()` 是同步函数，不加 `await`。

---



### 待观察
| 事项 | 说明 |
|------|------|
| python编程空间审核 | 正在运行，resume_pending_review 已验证有效。审核完成后 blueprint 自动生成，验证上传→课程完整流程 |

### 下一步产品改进（按优先级）
1. **首页课程卡片化**：把顶部下拉框改成课程卡片列表
2. **零输入上传**：领域名从文件名自动推断
3. **测验反馈优化**：措辞更友好，减少挫败感

---

## 四、关键决策与惯例（每次会话必读）

### 4.1 asyncpg cast 写法
所有 raw SQL 参数类型转换用 CAST(:x AS uuid)，不用 :x::uuid。

### 4.2 asyncpg IS NULL 写法
在 Python 层判断，生成两条不同 SQL。

### 4.3 鉴权原则
global space 对所有登录用户开放。personal/course space 必须通过 SpaceService.require_space_access。

### 4.4 space_members owner 记录
space 创建时必须写 role=owner 记录。

### 4.5 Celery 任务规范
- 任务体必须是同步函数，内部用 asyncio.run() 执行异步逻辑
- 新增任务必须在 task_routes 中注册队列
- knowledge 队列任务必须加 `--prefetch-multiplier=1`

### 4.6 前端构建部署流程
```powershell
# web 无 volume 挂载，必须重建镜像（PowerShell，在项目目录）
docker compose up -d --no-deps --build web
# 后端有改动时
docker compose up -d --no-deps --build api
```
详见 4.24 节。

### 4.7 Phase 3 之后新接口规范
所有涉及 topic_key 的接口必须同时接受 space_id query 参数并透传。

### 4.8 resolve_space_id 使用原则
仅在调用方完全没有 space_id 来源时使用。

### 4.9 知识库推荐业务规则
只有 global space + review_status=approved 的知识点可提交推荐。重复提交幂等：rejected 重置为 pending。

### 4.10 密码强度校验规则
至少 8 位，大写/小写/数字/特殊字符中至少三种。后端前端保持同步。

### 4.11 axios 响应拦截器层级
`res.data` = 实际 payload，不要写 `res.data.data`。

### 4.12 账号软删除规则
注销账号将 users.status 置为 'deleted'（Migration 010）。登录时 status != 'active' 即拒绝。

### 4.13 头像上传规范
接口：POST /api/users/me/avatar，multipart/form-data，MinIO 路径 `avatars/{user_id}.{ext}`，限 5MB。

### 4.14 blueprint 就绪轮询规范
上传成功后每 5 秒调 `GET /api/blueprints/{topic_key}/status`，最多 36 次（3分钟），超时标记失败。

### 4.15 AI 批改 rubric 规范
- rubric prompt 用 `.replace()` 不用 `.format()`
- LLM 返回的 JSON 解析前先 unescape：`.replace("{{","{").replace("}}","}")`
- score 强制 `float()` 转换，is_correct 用 `score >= 0.6`

### 4.16 测验题目缓存规范
题目存在 `chapter_quizzes` 表，blueprint 发布后由 `pregen_chapter_quizzes` 预生成。清空缓存：`DELETE FROM chapter_quizzes`。

### 4.17 SQL 参数名必须一致
SQL 里 `:user_id` 对应参数字典 key 必须是 `"user_id"`，不能用 `"uid"` 等别名。

### 4.18 Worker 稳定性配置（重要，禁止违反）
```yaml
# celery_worker_knowledge
command: ... --heartbeat-interval=10 --prefetch-multiplier=1
restart: unless-stopped

# rabbitmq
environment:
  RABBITMQ_SERVER_ADDITIONAL_ERL_ARGS: "-rabbit consumer_timeout 28800000"
```
`--without-heartbeat` 绝对禁用。新增 worker 必须遵循此规范。

### 4.19 getDomains 接口规范
admin/router.py 第 49 行，SQL 里统计字段必须真实查询，禁止硬编码为 0。

### 4.20 auto_review 续接机制
`resume_pending_review` 由 celery_beat 每 5 分钟触发，自动检查 pending 实体并续接审核。任务链不依赖人工干预。如需手动触发：
```python
from apps.api.tasks.auto_review_tasks import auto_review_entities
auto_review_entities.apply_async(args=['SPACE_ID'], queue='knowledge')
```

### 4.21 Vue 组件 TypeScript 规范
- `ref()` 初始值为 null 时必须显式泛型：`ref<any>(null)` 或具体类型
- 计算属性返回数组需显式声明：`computed<SomeType[]>(() => ...)`
- filter/some/forEach 回调参数必须有类型注解，不依赖 TS 推断
- 字面量对象做映射表时使用 `Record<string, string>` 而非字面量类型，避免 any key 索引报错
- 事件处理函数参数中 `act` 类型未知时用 `any`，`queueName` 等明确用 `string`

### 4.22 Admin 组件 axios 规范

Admin 页面组件**禁止**直接 `import axios` 发请求，必须使用带 Authorization 拦截器的局部实例（或从 `src/api/index.ts` 导出的 `http`），否则 `HTTPBearer()` 返回 403（不触发登录跳转，难以定位）：

```javascript
// 正确：组件内局部实例（或 import http from '@/api'）
const http = axios.create({ baseURL: '/api', timeout: 30000 })
http.interceptors.request.use(cfg => {
  const tk = localStorage.getItem('access_token')
  if (tk) cfg.headers.Authorization = `Bearer ${tk}`
  return cfg
})
```

URL 路径不带 `/api` 前缀（baseURL 已含）。

### 4.23 LLM 超时配置规范

`llm_gateway.py` 按 `model_route` 区分超时：
- `tutorial_content` / `blueprint_synthesis` / `coherence_eval`：120s
- 其他：30s

新增耗时路由时，把 route name 加入 `_LONG_TIMEOUT_ROUTES` 集合，不要修改全局默认值。

### 4.24 前端重新构建部署方式（Docker 镜像模式）

web 容器无源码 volume 挂载，修改前端文件后必须重建镜像：
```powershell
# 在项目目录 D:\studystudio 的 PowerShell 中运行
docker compose up -d --no-deps --build web
```
旧方式 `npm run build + docker compose cp` 仅适用于有 volume 挂载的场景，当前环境**不适用**。



```bash
# 查看某空间处理进度
docker compose exec postgres psql -U user -d adaptive_learning -c "
  SELECT d.document_status,
    (SELECT COUNT(*) FROM knowledge_entities ke WHERE ke.space_id=d.space_id) AS total,
    (SELECT COUNT(*) FROM knowledge_entities ke WHERE ke.space_id=d.space_id AND review_status='approved') AS approved,
    (SELECT status FROM skill_blueprints sb WHERE sb.space_id=d.space_id LIMIT 1) AS bp_status
  FROM documents d WHERE d.space_id = 'SPACE_ID';
"

# 知识点审核进度
docker compose exec postgres psql -U user -d adaptive_learning -c "
  SELECT review_status, COUNT(*) FROM knowledge_entities
  WHERE space_id='SPACE_ID' GROUP BY review_status;
"

# RabbitMQ 队列积压检查
docker compose exec rabbitmq rabbitmqctl list_queues name messages consumers

# 清空测验题目缓存
docker compose exec postgres psql -U user -d adaptive_learning -c "DELETE FROM chapter_quizzes;"

# 查看 API 错误日志
docker compose logs api --tail=50 | grep -E "error|Error|500"

# knowledge worker 实时日志
docker compose logs celery_worker_knowledge -f | grep -E "start|done|error|approved|resume"
```

---

## 六、下次会话如何开始

1. 查 python编程空间审核状态（见第三节），blueprint 生成后验证完整上传→课程流程
2. 在 `/admin/courses` 验证课程管理页面端到端（课程列表 → 章节详情 → 单章重生成）
3. 推进首页课程卡片化

直接说想做哪个，先勘察相关代码再动手。
