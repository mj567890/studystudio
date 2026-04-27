# StudyStudio 安装与升级指南

## 环境要求

- Docker ≥ 20.10 + Docker Compose ≥ 2.0
- 磁盘 ≥ 10GB 可用
- 所需端口未被占用（默认 3000/8000/5432/6379/5672/9000/9001/15672）

---

## 一、全新安装

### 1. 上传

```bash
scp fresh_install_selfextract.sh user@server:/opt/studystudio/
```

### 2. 执行

```bash
ssh user@server
cd /opt/studystudio
chmod +x fresh_install_selfextract.sh
bash fresh_install_selfextract.sh
```

### 3. 交互式配置

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| WEB_PORT | 3000 | 前端页面 |
| API_PORT | 8000 | 后端 API |
| PG_PORT | 5432 | PostgreSQL |
| REDIS_PORT | 6379 | Redis |
| MINIO_PUBLIC_ENDPOINT | http://localhost:9000 | MinIO 外部下载地址 |
| OPENAI_API_KEY | sk-xxx | LLM API Key |
| OPENAI_BASE_URL | https://api.openai.com/v1 | LLM API 地址 |
| LLM_DEFAULT_MODEL | gpt-4o | 默认模型 |

所有配置写入 `.env`，后续修改生效需 `docker compose down && docker compose up -d`。

### 4. 访问

| 入口 | 地址 |
|------|------|
| 前端 | `http://<IP>:${WEB_PORT}` |
| 管理后台 | `http://<IP>:${WEB_PORT}/admin` |
| API 文档 | `http://<IP>:${API_PORT}/docs` |

### 5. 安装后必做

1. 登录管理后台
2. 进入 **AI 配置**，添加 LLM 提供商（`kind` 支持：`openai_compatible`、`anthropic`、`gemini`、`ollama`、`azure_openai`）
3. 进入 **知识管理**，上传文档启动知识管线

---

## 二、升级现有部署

### 1. 上传

```bash
scp upgrade_studystudio_selfextract.sh user@server:/opt/studystudio/
```

### 2. 执行

```bash
ssh user@server
cd /opt/studystudio
chmod +x upgrade_studystudio_selfextract.sh
bash upgrade_studystudio_selfextract.sh
```

### 3. 升级流程（自动）

| 步骤 | 操作 | 说明 |
|------|------|------|
| 版本检查 | 对比 VERSION 文件 | 已是最新则跳过 |
| 备份 | pg_dump + 代码打包 | 存入 `backups/时间戳/` |
| 停止 | `docker compose down` | |
| 更新 | 解压前保存 .env/文档，解压后恢复 | 旧版文档存 `.old_时间戳`，配置存 `.bak` |
| 迁移 | **仅执行未应用的迁移** | 通过 `schema_migrations` 表追踪 |
| 重建 | `build --no-cache` + `up -d` | |
| 验证 | 健康检查 + API/前端可达性 | 使用 .env 中配置的端口 |

### 4. 回滚

```bash
cd /opt/studystudio
docker compose down
tar -xzf backups/<时间戳>/code_backup_<时间戳>.tar.gz
docker compose up -d
# 如需回滚数据库
docker exec -i postgres psql -U user -d adaptive_learning < backups/<时间戳>/database_<时间戳>.sql
```

---

## 三、版本管理

- 版本号记录在 `VERSION` 文件中（当前：**2.7.0**）
- 数据库迁移通过 `schema_migrations` 表追踪，升级时仅执行新增迁移
- 迁移全部使用 `IF NOT EXISTS` / `IF EXISTS`，重复执行无害
- 旧服务器首次升级：迁移追踪表自动创建，已有迁移标记为已应用

---

## 四、Docker 子网冲突处理

Docker 默认网桥使用 `172.17.0.0/16`。如果宿主机网络恰好也在 172.17.x.x 段（常见于校园/企业内网），会导致容器网络与物理网络路由冲突。

### 自动检测（新装）

安装脚本自动检测宿主机是否有 172.17.x.x 地址。如检测到冲突：
1. 说明原因
2. 由你输入一个不冲突的子网（无预设默认值，需自行判断）
3. 自动创建 `docker-compose.override.yml`

无冲突则不做任何处理。

### 手动创建

如果已知存在冲突但脚本未检测到：

```bash
cat > docker-compose.override.yml <<'EOF'
networks:
  default:
    driver: bridge
    ipam:
      config:
        - subnet: <你的子网>
EOF
docker compose down && docker compose up -d
```

### 升级时

`docker-compose.override.yml` 不在升级包内，升级不触及。删除此文件即恢复默认。

---

## 五、端口自定义

端口在 `.env` 文件中配置，支持 8 个端口变量：

```bash
WEB_PORT=3000            # 前端页面
API_PORT=8000            # 后端 API
PG_PORT=5432             # PostgreSQL
REDIS_PORT=6379           # Redis
RABBITMQ_PORT=5672       # RabbitMQ AMQP
RABBITMQ_MGMT_PORT=15672 # RabbitMQ 管理界面
MINIO_PORT=9000           # MinIO API
MINIO_CONSOLE_PORT=9001   # MinIO 控制台
```

修改后执行 `docker compose down && docker compose up -d` 生效。

### MinIO 外部访问

如果服务器不可直连 MinIO 端口（如通过 Nginx 代理），配置：
```bash
MINIO_PUBLIC_ENDPOINT=https://files.example.com
```
此地址用于生成文件预签名下载 URL，不配置时浏览器可能无法下载 MinIO 内网地址。

---

## 五、常用运维命令

```bash
docker compose ps                  # 服务状态
docker compose logs -f api         # API 日志
docker compose restart api         # 重启 API
docker compose restart celery_worker_knowledge  # 重启 worker
docker compose down && docker compose up -d     # 重启全部服务（端口/配置变更后）
```

---

## 六、LLM 公有 API

系统通过 `ai_providers` 表管理 AI 提供商，支持的 `kind`：

`openai_compatible` · `anthropic` · `gemini` · `ollama` · `azure_openai`

### 管理后台配置

管理后台 → AI 配置 → 添加提供商

### SQL 直接配置

```sql
INSERT INTO ai_providers (name, kind, base_url, api_key, default_model, is_active)
VALUES ('DeepSeek', 'openai_compatible', 'https://api.deepseek.com/v1', 'sk-xxx', 'deepseek-chat', true);
```

---

## 七、文件清单

| 文件 | 大小 | 用途 |
|------|------|------|
| `fresh_install_selfextract.sh` | 379K | 新装单文件（推荐） |
| `upgrade_studystudio_selfextract.sh` | 378K | 升级单文件（推荐） |
| `fresh_install.sh` | — | 新装独立脚本（需搭配 tar.gz） |
| `upgrade_studystudio.sh` | — | 升级独立脚本（需搭配 tar.gz） |
| `upgrade_package.tar.gz` | 367K | 纯代码包 |
