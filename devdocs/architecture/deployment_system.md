# 部署系统架构

**设计日期：** 2026-04-27
**版本：** v1.0

---

## 一、设计目标

- **单文件部署**：用户上传一个 `.sh` 文件到服务器，执行即可
- **无损升级**：升级不丢失数据（数据库/文件/MinIO）、不破坏用户配置
- **幂等迁移**：迁移可重复执行不报错，支持增量
- **版本可追踪**：知道当前运行版本，知道升级后版本
- **端口可配置**：不硬编码，避免与宿主机端口冲突
- **子网冲突可解**：不替用户做默认选择，仅在必要时提供机制

---

## 二、文件关系

```
upgrade_studystudio_selfextract.sh  (380K)
  │
  ├── Shell 脚本部分（~10KB）
  │     ├── 版本检测
  │     ├── 备份（pg_dump + tar）
  │     ├── 停止/启动服务
  │     ├── 增量迁移
  │     └── 健康检查
  │
  └── 嵌入的 upgrade_package.tar.gz (369K)
        ├── apps/          后端 + 前端源码
        ├── migrations/    001~022 SQL 迁移
        ├── docker/        Dockerfile.api / Dockerfile.web
        ├── scripts/       init_admin.py 等工具
        ├── docker-compose.yml
        ├── requirements.txt
        ├── VERSION
        ├── .env.example
        └── INSTALL.md

fresh_install_selfextract.sh  (383K) — 同上结构，功能为新装
```

## 三、自解压机制

脚本末尾结构：
```
  ... shell 脚本 ...
  exit 0
  __STUDYSTUDIO_ARCHIVE__
  <tar.gz 二进制数据>
```

提取逻辑：
```bash
MARKER="__STUDYSTUDIO_ARCHIVE__"
MARKER_LINE=$(grep -an "^${MARKER}$" "$0" | head -1 | cut -d: -f1)
tail -n +$((MARKER_LINE + 1)) "$0" > upgrade_package.tar.gz
```

- `grep -a` 强制文本模式（脚本含二进制尾部）
- 标记 `__STUDYSTUDIO_ARCHIVE__` 在二进制中误匹配概率极低（已实测确认唯一）

## 四、升级流程

```
步骤 1 ─ 版本检查
  │   对比 VERSION 文件，同版本退出
  │
步骤 2 ─ 备份
  │   pg_dump → backups/<ts>/database_<ts>.sql
  │   tar 代码 → backups/<ts>/code_backup_<ts>.tar.gz
  │   保存 .env, docker-compose.yml, INSTALL.md, README.md
  │
步骤 3 ─ 停止
  │   docker compose down
  │
步骤 4 ─ 更新代码
  │   tar -xzf 解压新包
  │   恢复 .env（不可覆盖）
  │   docker-compose.yml 新版生效，旧版 → .bak.<ts>
  │   文档新版生效，旧版 → .old_<ts>
  │
步骤 5 ─ 增量迁移
  │   启动 postgres
  │   创建 schema_migrations（如不存在）
  │   遍历 migrations/*.sql
  │     ├── 已记录 → 跳过
  │     └── 未记录 → 执行 → 标记
  │   更新 VERSION
  │
步骤 6 ─ 重建
  │   docker compose build --no-cache
  │   docker compose up -d
  │
步骤 7 ─ 验证
      健康检查 + API/前端可达性
```

## 五、文件保护策略

| 文件 | 策略 | 理由 |
|------|------|------|
| `.env` | 备份→恢复（不可覆盖） | 含密钥和用户配置 |
| `docker-compose.yml` | 新版生效，旧版 → `.bak.<ts>` | 结构可能变化，旧版保留供参考 |
| `INSTALL.md` / `README.md` | 新版生效，旧版 → `.old_<ts>` | 用户可能在服务器上添加了笔记 |
| `docker-compose.override.yml` | 不解压不触及 | 用户为解决子网冲突手动创建 |
| 其他代码文件 | 直接覆盖 | 这些应由升级包控制 |

## 六、迁移追踪

`schema_migrations` 表（Migration 022）：

```sql
CREATE TABLE IF NOT EXISTS schema_migrations (
    filename   VARCHAR(255) PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

- 新装时：001 由 postgres initdb 自动执行，002~021 由脚本执行并全部标记
- 升级时：只执行不在表中的迁移文件
- 旧服务器首次升级：创建表 + 标记 001~021 为已应用

## 七、端口配置

`docker-compose.yml` 中所有宿主机端口使用变量：

```yaml
ports:
  - "${WEB_PORT:-3000}:3000"
  - "${API_PORT:-8000}:8000"
  - "${PG_PORT:-5432}:5432"
  # ...
```

- 容器内部端口（`:3000` 部分）不变，容器间通信用容器名（`postgres:5432`）
- 用户修改 `.env` 后 `docker compose down && up -d` 生效

## 八、Docker 子网冲突

问题：Docker 默认网桥 `172.17.0.0/16` 与校园/企业网段冲突。

方案：不在 `docker-compose.yml` 中硬编码网络。安装脚本检测冲突后由用户输入子网，写入 `docker-compose.override.yml`：

```yaml
networks:
  default:
    driver: bridge
    ipam:
      config:
        - subnet: <用户输入的CIDR>
```

- 无冲突：零影响，Docker 默认行为
- 有冲突：用户自行判断安全子网
- 升级：override 文件在升级包外，不触及

## 九、LLM 公有 API

已确认兼容，通过 `ai_providers` 表管理：

```sql
INSERT INTO ai_providers (name, kind, base_url, api_key, default_model, is_active)
VALUES ('DeepSeek', 'openai_compatible', 'https://api.deepseek.com/v1', 'sk-xxx', 'deepseek-chat', true);
```

支持的 `kind`：`openai_compatible` · `anthropic` · `gemini` · `ollama` · `azure_openai`
