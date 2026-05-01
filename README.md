<div align="center">

# StudyStudio

**企业级 AI 课程生成平台**

上传材料 → AI 教学设计 → 教师经验校准 → 自动生成课程 → 自适应学习

![Version](https://img.shields.io/badge/Version-2.2-blue?style=flat-square)
![Python](https://img.shields.io/badge/Python-3.11-3776AB?style=flat-square&logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.110-009688?style=flat-square&logo=fastapi&logoColor=white)
![Vue](https://img.shields.io/badge/Vue-3.4-4FC08D?style=flat-square&logo=vue.js&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-15+pgvector-336791?style=flat-square&logo=postgresql&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?style=flat-square&logo=docker&logoColor=white)
![Tests](https://img.shields.io/badge/Tests-473_passed-green?style=flat-square)
![License](https://img.shields.io/badge/License-MIT-yellow?style=flat-square)

</div>

---

## 核心设计理念

> AI 的角色是"在教学框架、企业材料证据、教师隐性经验约束下，生成可学习、可练习、可评估的课程体验"。

**教师永远只做选择题和填空题，不做论述题。** AI 出选项，教师做选择，隐性知识结构化——这是 StudyStudio 区别于其他 AI 生成工具的根本差异。

---

## 核心功能

<div align="center">

<table>
<tr>
<td width="50%">

### 🎯 课程生成（v2.2 核心）
- 材料分析 → 5 种维度 × 3 套方案
- **经验校准**：5 道选择题抽取教师隐性知识
- Course Map 路由分发，防 Context Bleed
- 3 种 MVP 教学模板（理论/任务/合规）
- 6 维自动化质量检查

</td>
<td width="50%">

### 📂 智能知识管理
- 支持 PDF / Word / 文本上传
- LLM 四步管线自动提取知识点
- 两轮 AI 全自动审核，清洗噪声
- pgvector 向量化，支持语义检索

</td>
</tr>
<tr>
<td width="50%">

### 🧠 自适应学习路径
- 分级测验冷启动，评估初始水平
- 漏洞扫描，定位薄弱知识点
- 依赖关系排序，生成最优补洞路径
- 章节完成后实时更新掌握度

</td>
<td width="50%">

### 💬 AI 辅助教学对话
- BM25 + 向量融合检索（RRF）
- 诊断学习者理解薄弱点
- 个性化补充解释
- 章节源文档溯源

</td>
</tr>
<tr>
<td width="50%">

### 📝 测验与评估
- 章节测验自动生成（单选 / 判断 / 填空）
- AI 评分标准（ai_rubric）
- 错题记录与分析
- 答题后自动更新掌握度

</td>
<td width="50%">

### 👥 社交学习
- 多人知识空间 + 邀请码 + 公开分级
- Fork 课程空间，引用源课程讨论
- 课程讨论区（话题 / 问答 / 笔记）
- 社区发现公开课程

</td>
</tr>
<tr>
<td width="50%">

### 🎓 教师引导式课程迭代
- 选择题式精调（拒绝论述题）
- AI 定向重写 + 章节隔离
- 内容版本备份与回滚
- 测验/讨论自动联动刷新

</td>
<td width="50%">

### 🔒 安全与合规
- 3 项 P1 安全修复（v2.2）+ 红队测试
- JWT 强制校验 + bcrypt 密码哈希
- IP 级速率限制（5 级限流器）
- Nginx CSP + 安全响应头

</td>
</tr>
</table>

</div>

---

## v2.2 课程生成流水线

```
阶段 1              阶段 2                              阶段 3           阶段 4         阶段 5
材料分析      →   课程设计对话                        →  Course Map   →  课程生成   →  审阅+反馈
(全自动)          ├ 2a: 方案选择（5 种维度 × 3 套方案）   (自动校验)      (全自动)       (选择题式精调)
                  ├ 2b: 经验校准（5 道结构化选择题）
                  └ 2c: Course Map 预览确认
```

### 阶段 2b — 经验校准（核心差异化）

通过 5 道动态选择题抽取教师脑中的隐性知识——真痛点、真实案例、常见误区、优先级排序、红线禁忌。这些数据经 Course Map 路由分发，精确注入各章节生成 prompt，防止 Context Bleed。

### 5 种教学模板

| 课型 | 教学模式 | 适用场景 |
|------|----------|----------|
| **theory** | 概念建构模式 | 概念、原理、基础认知 |
| **task** | 技能习得模式 | SOP、操作手册、工作流程 |
| **compliance** | 制度内化模式 | 管理制度、红线规范、合规审计 |
| case | 案例复盘模式 | 事故复盘、管理案例（第二轮） |
| project | 实战演练模式 | 综合项目（第二轮） |

---

## 系统架构

<pre>
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
│  /community  /admin  /quiz  /install          │
└─────┬──────────────┬──────────────┬───────────┘
      │              │              │
 ┌────▼─────┐   ┌────▼────┐   ┌────▼──────┐
 │PostgreSQL│   │  Redis  │   │ RabbitMQ  │
 │ pgvector │   │  Cache  │   │ EventBus  │
 └──────────┘   └─────────┘   └─────┬─────┘
                                    │ Tasks
          ┌─────────────────────────┼────────────────────────┐
          │                         │                        │
   ┌──────▼──────┐          ┌───────▼──────┐       ┌────────▼──────┐
   │   Worker    │          │    Worker    │       │    Worker     │
   │  tutorial   │          │  knowledge   │       │    review     │
   │  low_prio   │          │  blueprint   │       │  (AI 审核专用) │
   └─────────────┘          └─────────────┘       └───────────────┘
</pre>

---

## 技术栈

| 层级 | 技术 | 说明 |
|:---|:---|:---|
| **前端** | Vue 3 · TypeScript · Vite · Element Plus · Pinia | SPA，chunk 拆分优化 |
| **后端** | FastAPI · SQLAlchemy 2.0 (async) · Pydantic v2 | 异步 Web 框架 |
| **数据库** | PostgreSQL 15 + pgvector | 关系型 + 向量检索 |
| **缓存** | Redis 7 | KV 存储 + 分布式锁 |
| **消息队列** | RabbitMQ 3.12 + aio-pika | 事件总线 + 任务分发 |
| **异步任务** | Celery 5 + Celery Beat | 后台任务 + 定时巡检 |
| **文件存储** | MinIO | S3 兼容对象存储 |
| **LLM** | OpenAI API + LangChain | 大模型集成 |
| **日志** | structlog | 结构化日志 |
| **部署** | Docker + Docker Compose | 9 服务一键启动 |

---

## 快速开始

### 前置要求

- Docker 20.10+
- Docker Compose 2.0+
- OpenAI API Key

### 1. 克隆仓库

```bash
git clone git@github.com:mj567890/studystudio.git
cd studystudio
```

### 2. 配置环境变量

```bash
cp .env.example .env
# 编辑 .env，填写：
#   OPENAI_API_KEY          必填
#   JWT_SECRET_KEY          生成方式: openssl rand -hex 32
#   AI_CONFIG_ENCRYPTION_KEY
```

### 3. 启动服务

```bash
docker compose up -d
```

### 4. 访问

| 服务 | 地址 |
|:---|:---|
| 前端应用 | http://localhost:3000 |
| API 文档 | http://localhost:8000/docs |
| MinIO 控制台 | http://localhost:9001 |
| RabbitMQ 管理 | http://localhost:15672 |

---

## 项目结构

```
studystudio/
├── apps/
│   ├── api/                           # FastAPI 后端
│   │   ├── main.py                    # 应用入口 + 事件订阅
│   │   ├── core/                      # 核心组件
│   │   │   ├── db.py                  # 数据库 + pgvector
│   │   │   ├── llm_gateway.py         # LLM 网关（RRF 融合检索）
│   │   │   ├── rate_limit.py          # 速率限制（滑动窗口，IP 维度）
│   │   │   ├── media_gateway.py       # 媒体资源网关
│   │   │   ├── events.py              # 事件总线（aio-pika）
│   │   │   ├── storage.py             # MinIO 客户端
│   │   │   └── crypto.py              # AI 配置加密
│   │   ├── modules/                   # 业务模块（13 个）
│   │   │   ├── auth/                  # 认证 & 用户
│   │   │   ├── knowledge/             # 文件上传 / 解析 / 知识提取
│   │   │   ├── learner/               # 学习者画像 / 进度 / 测验
│   │   │   ├── tutorial/              # 教程内容生成
│   │   │   ├── teaching/              # AI 教学对话
│   │   │   ├── skill_blueprint/       # 技能蓝图 + 经验校准
│   │   │   ├── course_template/       # 课程模板（5 种教学模式）
│   │   │   ├── quiz/                  # 测验与评估
│   │   │   ├── space/                 # 知识空间
│   │   │   ├── community/             # 社区策展
│   │   │   ├── discuss/               # 课程讨论区
│   │   │   ├── admin/                 # 后台管理
│   │   │   └── install/               # 安装向导
│   │   └── tasks/                     # Celery 异步任务
│   │       ├── knowledge_tasks.py     # 解析 / 提取 / embedding
│   │       ├── tutorial_tasks.py      # 教程骨架 / 章节生成
│   │       ├── blueprint_tasks.py     # 技能蓝图合成 + 经验校准
│   │       ├── auto_review_tasks.py   # AI 双轮自动审核
│   │       └── embedding_tasks.py     # 向量化任务
│   └── web/                           # Vue 3 前端
│       ├── nginx.conf                 # Nginx 安全配置（CSP + 安全头）
│       └── src/
│           ├── views/                 # 页面组件
│           ├── components/            # 通用组件
│           ├── composables/           # 组合式函数
│           ├── api/                   # API 调用封装
│           ├── stores/                # Pinia 状态管理
│           └── router/                # 路由配置
├── migrations/                        # 数据库迁移 SQL（39 个版本）
├── tests/                             # pytest 测试套件（473 tests）
│   ├── api/                           # 端点行为 + 权限测试
│   ├── unit/                          # 核心模块单元测试
│   ├── integration/                   # 文档管线集成测试
│   └── security/                      # 红队安全测试（136 tests, 7 攻击向量）
├── scripts/                           # 工具脚本
├── devdocs/                           # 开发文档 & 架构设计
└── docker-compose.yml
```

---

## Celery 队列架构

| Worker | 队列 | 职责 | 并发 |
|:---|:---|:---|:---:|
| `celery_worker` | `tutorial` · `low_priority` | 教程生成 | 4 |
| `celery_worker_knowledge` | `knowledge` · `blueprint.synthesis` | 知识提取 / 蓝图生成 | 8 |
| `celery_worker_review` | `knowledge.review` | 知识点 AI 审核（专用隔离） | 2 |
| `celery_beat` | — | 定时巡检（每 5 分钟自动续接中断任务） | — |

---

## 安全

### 认证与授权
- JWT Bearer Token 强制校验，启动时验证密钥强度
- bcrypt 密码哈希，密码强度策略（3/4 字符类型 + 弱密码黑名单）
- `require_role()` 角色检查（admin / learner）
- `SpaceService.require_space_access()` 空间级权限控制

### 速率限制（v2.2 新增）
- 共享模块 `apps/api/core/rate_limit.py`，滑动窗口算法，IP 维度
- `rate_limit_llm_heavy`（5/min）：课程生成、经验校准
- `rate_limit_llm_standard`（20/min）：AI 教学对话、测验生成
- `rate_limit_celery`（10/min）：后台任务触发
- 超限返回 429 + `Retry-After` header + 结构化错误体

### 前端防护
- DOMPurify XSS 净化
- CSP / X-Frame-Options / X-Content-Type-Options / Referrer-Policy 安全响应头

### 容器加固
- API 非 root 运行、凭据全部 `.env` 变量化、SQL 参数化查询
- 文件上传：扩展名白名单 + MinIO key 前缀约束

### 测试覆盖
- 全量回归：**473 tests / 0 failed**
- 红队安全测试套件：**136 tests / 7 攻击向量**（认证绕过、IDOR、注入、错误泄露、Rate Limit、LLM Prompt 注入、Celery 滥用）
- `tests/security/` → CI 可集成

详见：
- [安全审计报告](devdocs/security/SECURITY_AUDIT_REPORT_20260427.md)
- [红队安全测试报告](devdocs/security/SECURITY_RED_TEAM_REPORT.md)
- [速率限制与权限技术参考](devdocs/security/rate-limit-and-permissions.md)

---

## 开发常用命令

```bash
# 重建并重启特定服务
docker compose build api && docker compose up -d api
docker compose build web && docker compose up -d web

# 查看异步任务日志
docker compose logs -f celery_worker_knowledge

# 本地前端热更新
cd apps/web && npm install && npm run dev

# 运行测试
pytest tests/ -q                          # 全量回归
pytest tests/security/ -v                 # 安全测试
pytest tests/security/ test_smoke.py -q   # 快速冒烟
```

---

## 相关文档

| 文档 | 说明 |
|:---|:---|
| [课程生成架构设计](devdocs/course_generation_architecture_v2.2-final.md) | v2.2 完整架构方案 |
| [架构变更日志](devdocs/course_generation_architecture_changelog.md) | 版本演进记录 |
| [教师使用指南](devdocs/teacher_guide_v2.2.md) | 教师端操作说明 |
| [交付报告](DELIVERY_REPORT.md) | v2.2 硬化审查结果 |
| [pytest 测试套件](devdocs/testing/pytest_api_suite.md) | 测试架构说明 |

---

## License

[MIT](LICENSE)
