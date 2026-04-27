<div align="center">

# 📚 StudyStudio

**基于 AI 的自适应学习平台**

上传资料 → AI 提取知识点 → 自动生成课程 → 个性化学习路径

<br/>

![Version](https://img.shields.io/badge/Version-2.7.0-blue?style=flat-square)
![Python](https://img.shields.io/badge/Python-3.11-3776AB?style=flat-square&logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.110-009688?style=flat-square&logo=fastapi&logoColor=white)
![Vue](https://img.shields.io/badge/Vue-3.4-4FC08D?style=flat-square&logo=vue.js&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-15+pgvector-336791?style=flat-square&logo=postgresql&logoColor=white)
![Celery](https://img.shields.io/badge/Celery-5.3-37814A?style=flat-square&logo=celery&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?style=flat-square&logo=docker&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-yellow?style=flat-square)

</div>

---

## ✨ 核心功能

<div align="center">

<table>
<tr>
<td width="50%">

### 🧠 自适应学习路径
- 分级测验冷启动，评估初始水平
- 漏洞扫描，定位薄弱知识点
- 依赖关系排序，生成最优补洞路径
- 章节完成后实时更新掌握度

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

### 🎓 AI 教程自动生成
- 知识点聚类生成技能蓝图
- 阶段化学习路径规划
- 逐章节 AI 自动编写内容
- 质量评估器（连贯性 / 完整性 / 准确性）

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
- 多人知识空间 + 邀请码
- 课程讨论区（话题 / 问答 / 笔记）
- 社区发现公开课程
- 学习进度共享

</td>
</tr>
</table>

</div>

---

## 🏗️ 系统架构

<div align="center">

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

### 事件驱动流水线

<pre>
文件上传  ──►  解析文档  ──►  提取知识点  ──►  AI 双轮审核
                                                    │
                                           ┌────────▼────────┐
                                           │  Embedding 向量化 │
                                           └────────┬────────┘
                                                    │
                                           ┌────────▼────────┐
                                           │  生成技能蓝图     │
                                           └────────┬────────┘
                                                    │
                                           ┌────────▼────────┐
                                           │  编写章节内容     │
                                           └─────────────────┘
</pre>

</div>

---

## 🛠️ 技术栈

<div align="center">

| 层级 | 技术 | 说明 |
|:---|:---|:---|
| **前端** | Vue 3 + TypeScript · Vite · Element Plus · Pinia | SPA 单页应用 |
| **后端** | FastAPI · SQLAlchemy 2.0 (async) · Pydantic v2 | 异步 Web 框架 |
| **数据库** | PostgreSQL 15 + pgvector | 关系型 + 向量检索 |
| **缓存** | Redis 7 | KV 存储 + 分布式锁 |
| **消息队列** | RabbitMQ 3.12 + aio-pika | 事件总线 + 任务分发 |
| **异步任务** | Celery 5 + Celery Beat | 后台任务 + 定时巡检 |
| **文件存储** | MinIO | S3 兼容对象存储 |
| **LLM** | OpenAI API + LangChain | 大模型集成（可替换接口） |
| **日志** | structlog | 结构化日志 |
| **容器化** | Docker + Docker Compose | 一键启动 |

</div>

---

## 🚀 快速开始

### 前置要求

- Docker 20.10+
- Docker Compose 2.0+
- OpenAI API Key（或兼容接口）

### 1. 克隆仓库

```bash
git clone https://github.com/mj567890/studystudio.git
cd studystudio
```

### 2. 配置环境变量

```bash
# 复制环境变量模板
cp .env.example .env

# 编辑 .env，填写以下必填项：
#   - OPENAI_API_KEY         你的 API Key
#   - JWT_SECRET_KEY         生成方式：openssl rand -hex 32
#   - AI_CONFIG_ENCRYPTION_KEY  生成方式见 .env.example 内注释
```

### 3. 启动服务

```bash
# 方式 A：一键安装脚本（交互式配置，含管理员账号创建）
bash fresh_install_selfextract.sh

# 方式 B：Docker Compose 直接启动（需先完成步骤 2 的 .env 配置）
docker compose up -d
```

> Windows 用户：启动前确保 Docker Desktop 已运行（任务栏鲸鱼图标就绪）。详见 [INSTALL.md](INSTALL.md)。

### 4. 访问

| 服务 | 地址 |
|:---|:---|
| 🌐 前端应用 | http://localhost:3000 |
| 📖 API 文档 | http://localhost:8000/docs |
| 🗄️ MinIO 控制台 | http://localhost:9001 |
| 🐰 RabbitMQ 管理 | http://localhost:15672 |

---

## 📁 项目结构

```
studystudio/
├── apps/
│   ├── api/                        # FastAPI 后端
│   │   ├── main.py                 # 应用入口 + 事件订阅
│   │   ├── core/                   # 核心组件
│   │   │   ├── db.py               # 数据库 + pgvector
│   │   │   ├── llm_gateway.py      # LLM 网关（RRF 融合检索）
│   │   │   ├── events.py           # 事件总线（aio-pika）
│   │   │   ├── storage.py          # MinIO 客户端
│   │   │   └── crypto.py           # AI 配置加密
│   │   ├── modules/                # 业务模块（12 个）
│   │   │   ├── auth/               # 认证 & 用户
│   │   │   ├── knowledge/          # 文件上传 / 解析 / 知识提取
│   │   │   ├── learner/            # 学习者画像 / 进度 / 测验
│   │   │   ├── tutorial/           # 教程内容生成
│   │   │   ├── teaching/           # AI 教学对话
│   │   │   ├── skill_blueprint/    # 技能蓝图
│   │   │   ├── space/              # 知识空间
│   │   │   ├── community/          # 社区策展
│   │   │   ├── discuss/            # 课程讨论区
│   │   │   └── admin/              # 后台管理
│   │   └── tasks/                  # Celery 异步任务
│   │       ├── knowledge_tasks.py  # 解析 / 提取 / embedding
│   │       ├── tutorial_tasks.py   # 教程骨架 / 章节生成
│   │       ├── blueprint_tasks.py  # 技能蓝图合成
│   │       ├── auto_review_tasks.py# AI 双轮自动审核
│   │       └── embedding_tasks.py  # 向量化任务
│   └── web/                        # Vue 3 前端
│       └── src/
│           ├── views/              # 页面组件（27 个）
│           ├── components/         # 通用组件
│           ├── api/                # API 调用封装
│           ├── stores/             # Pinia 状态管理
│           └── router/             # 路由配置
├── migrations/                     # 数据库迁移 SQL（23 个版本）
├── scripts/                        # 工具脚本
├── devdocs/                        # 开发文档 & 架构说明
└── docker-compose.yml
```

---

## ⚙️ Celery 队列架构

| Worker | 队列 | 职责 | 并发 |
|:---|:---|:---|:---:|
| `celery_worker` | `tutorial` · `low_priority` | 教程生成 | 4 |
| `celery_worker_knowledge` | `knowledge` · `blueprint.synthesis` | 知识提取 / 蓝图生成 | 8 |
| `celery_worker_review` | `knowledge.review` | 知识点 AI 审核（专用隔离）| 2 |
| `celery_beat` | — | 定时巡检（每 5 分钟自动续接中断任务）| — |

---

## 🔒 安全

- **全栈安全审计**：2026-04 完成，4 CRITICAL + 10 HIGH + 14 MEDIUM 项已修复
- **认证强化**：JWT 启动强制校验、bcrypt 密码哈希、IP 级速率限制（登录 20/min，注册 5/min）
- **前端防护**：DOMPurify XSS 净化、CSP / X-Frame-Options / HSTS 等 8 个安全响应头
- **容器加固**：API 非 root 用户运行、凭据全部 `.env` 变量化、SQL 参数化查询
- **依赖升级**：axios 1.6.0 → 1.7.9（修复 CVE-2023-45857）

详见 [安全审计报告](devdocs/security/SECURITY_AUDIT_REPORT_20260427.md)。

---

## 🔧 开发常用命令

```bash
# 重建并重启特定服务
docker-compose build api && docker-compose up -d api
docker-compose build web && docker-compose up -d web

# 查看异步任务日志
docker-compose logs -f celery_worker_knowledge
docker-compose logs -f celery_worker_review

# 本地前端热更新
cd apps/web && npm install && npm run dev
```

---

## 📄 License

[MIT](LICENSE)
