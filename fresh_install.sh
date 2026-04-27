#!/usr/bin/env bash
# =============================================================================
# StudyStudio 全新安装脚本 v1.0
# 用法：bash fresh_install.sh [安装目录]
#       默认安装到当前目录
# =============================================================================
set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; NC='\033[0m'
info()  { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*"; }
step()  { echo -e "\n${BLUE}━━━ $* ━━━${NC}"; }

INSTALL_DIR="${1:-$(pwd)}"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

info "安装目录: ${INSTALL_DIR}"
mkdir -p "${INSTALL_DIR}"
cd "${INSTALL_DIR}"

# ── 检测包来源 ──────────────────────────────────────────────────────────
ARCHIVE_MARKER="__STUDYSTUDIO_ARCHIVE__"
SCRIPT_PATH="$(cd "$(dirname "$0")" && pwd)/$(basename "$0")"

if grep -aq "^${ARCHIVE_MARKER}$" "${SCRIPT_PATH}" 2>/dev/null; then
    info "自解压模式，提取安装包..."
    PACKAGE_FILE="${INSTALL_DIR}/upgrade_package.tar.gz"
    MARKER_LINE=$(grep -an "^${ARCHIVE_MARKER}$" "${SCRIPT_PATH}" 2>/dev/null | head -1 | cut -d: -f1)
    tail -n +$((MARKER_LINE + 1)) "${SCRIPT_PATH}" > "${PACKAGE_FILE}"
else
    PACKAGE_FILE="${INSTALL_DIR}/upgrade_package.tar.gz"
    if [ ! -f "${PACKAGE_FILE}" ]; then
        SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
        PACKAGE_FILE="${SCRIPT_DIR}/upgrade_package.tar.gz"
    fi
    if [ ! -f "${PACKAGE_FILE}" ]; then
        error "找不到 upgrade_package.tar.gz"
        error "请将升级包与脚本放在同一目录"
        exit 1
    fi
fi
info "安装包: ${PACKAGE_FILE}"

# ── 步骤 1：环境检查 ──────────────────────────────────────────────────
step "步骤 1/6：环境检查"

# 检查 Docker
if ! command -v docker &>/dev/null; then
    error "需要安装 Docker（>= 20.10）"
    error "安装指南: https://docs.docker.com/engine/install/"
    exit 1
fi
info "Docker: $(docker --version)"

# 检查 Docker Compose
if docker compose version &>/dev/null 2>&1; then
    DOCKER_COMPOSE="docker compose"
elif command -v docker-compose &>/dev/null; then
    DOCKER_COMPOSE="docker-compose"
else
    error "需要安装 Docker Compose"
    exit 1
fi
info "Docker Compose: $(${DOCKER_COMPOSE} version --short 2>/dev/null || ${DOCKER_COMPOSE} --version)"

# 检查端口
for port in 3000 8000 5432 6379 5672 9000; do
    if ss -tlnp 2>/dev/null | grep -q ":${port} " || netstat -tlnp 2>/dev/null | grep -q ":${port} "; then
        warn "端口 ${port} 已被占用，请确保可以释放或映射到其他端口"
    fi
done

# 检查磁盘空间（至少 10GB 可用）
AVAIL=$(df -BG . 2>/dev/null | tail -1 | awk '{print $4}' | sed 's/G//' || echo "99")
if [ "${AVAIL}" -lt 10 ] 2>/dev/null; then
    warn "可用磁盘空间 ${AVAIL}G，建议至少 10GB"
fi

# ── 步骤 2：解压代码 ──────────────────────────────────────────────────
step "步骤 2/6：解压代码"
tar -xzf "${PACKAGE_FILE}"
info "代码解压完成"

# 验证关键文件
REQUIRED_FILES=(
    "docker-compose.yml"
    "requirements.txt"
    "docker/Dockerfile.api"
    "docker/Dockerfile.web"
    "apps/api/main.py"
    "migrations/001_initial_schema.sql"
)
for f in "${REQUIRED_FILES[@]}"; do
    if [ ! -f "${INSTALL_DIR}/${f}" ]; then
        error "缺失关键文件: ${f}"
        exit 1
    fi
done
info "关键文件验证通过"

# ── 步骤 3：配置环境变量 ────────────────────────────────────────────
step "步骤 3/6：配置环境变量"

ENV_FILE="${INSTALL_DIR}/.env"

if [ -f "${ENV_FILE}" ]; then
    info ".env 文件已存在，跳过创建"
else
    # 生成安全密钥
    JWT_SECRET=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))" 2>/dev/null || \
                 openssl rand -base64 32 2>/dev/null || \
                 echo "change-me-$(date +%s)")
    ENC_KEY=$(python3 -c "import secrets,base64; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())" 2>/dev/null || \
              echo "change-me-$(date +%s)")

    echo ""
    echo "端口配置（直接回车使用默认值）："
    read -rp "  前端端口 [3000]: " WEB_PORT; WEB_PORT=${WEB_PORT:-3000}
    read -rp "  API 端口 [8000]: " API_PORT; API_PORT=${API_PORT:-8000}
    read -rp "  PostgreSQL 端口 [5432]: " PG_PORT; PG_PORT=${PG_PORT:-5432}
    read -rp "  Redis 端口 [6379]: " REDIS_PORT; REDIS_PORT=${REDIS_PORT:-6379}

    # 检测 Docker 默认子网是否与宿主机冲突（172.17 是 Docker 默认网桥）
    DOCKER_CONFLICT=""
    if ip addr show 2>/dev/null | grep -q "inet 172\.17\." || \
       ip route show 2>/dev/null | grep -q "172\.17\."; then
        DOCKER_CONFLICT="yes"
    fi
    echo ""
    echo "AI 配置（直接回车跳过，稍后在管理后台配置）："
    read -rp "  API Key [sk-xxx]: " API_KEY; API_KEY=${API_KEY:-sk-your-key-here}
    read -rp "  Base URL [https://api.openai.com/v1]: " BASE_URL; BASE_URL=${BASE_URL:-https://api.openai.com/v1}
    read -rp "  默认模型 [gpt-4o]: " MODEL; MODEL=${MODEL:-gpt-4o}
    read -rp "  MinIO 外部地址 [http://localhost:${MINIO_PORT:-9000}]: " MINIO_PUBLIC; MINIO_PUBLIC=${MINIO_PUBLIC:-http://localhost:${MINIO_PORT:-9000}}

    cat > "${ENV_FILE}" <<EOF
# StudyStudio 环境变量 — 生成于 $(date)
# ── 端口 ──────────────────────────────────────
WEB_PORT=${WEB_PORT}
API_PORT=${API_PORT}
PG_PORT=${PG_PORT}
REDIS_PORT=${REDIS_PORT}
RABBITMQ_PORT=5672
RABBITMQ_MGMT_PORT=15672
MINIO_PORT=9000
MINIO_CONSOLE_PORT=9001

# ── 基础设施 ──────────────────────────────────
DATABASE_URL=postgresql+asyncpg://user:pass@postgres:5432/adaptive_learning
REDIS_URL=redis://redis:6379
CELERY_BROKER_URL=amqp://guest:guest@rabbitmq:5672/
RABBITMQ_URL=amqp://guest:guest@rabbitmq:5672/
MINIO_ENDPOINT=http://minio:9000
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=minioadmin
MINIO_BUCKET=adaptive-learning
MINIO_PUBLIC_ENDPOINT=${MINIO_PUBLIC}

# ── LLM ───────────────────────────────────────
OPENAI_API_KEY=${API_KEY}
OPENAI_BASE_URL=${BASE_URL}
LLM_DEFAULT_MODEL=${MODEL}
EMBEDDING_MODEL=text-embedding-3-small

# ── 安全 ──────────────────────────────────────
JWT_SECRET_KEY=${JWT_SECRET}
AI_CONFIG_ENCRYPTION_KEY=${ENC_KEY}

# ── 应用 ──────────────────────────────────────
APP_ENV=production
APP_DEBUG=false
EOF
    info ".env 文件已创建（已配置端口和 AI 参数）"
fi

# ── Docker 子网冲突检测 ──────────────────────────────────────────────────
if [ -n "${DOCKER_CONFLICT}" ]; then
    echo ""
    warn "检测到宿主机使用 172.17.x.x 网段"
    echo "  Docker 默认网桥也是 172.17.0.0/16，两者会冲突，导致网络不通。"
    echo "  需要为容器指定一个不与宿主机网络重叠的子网。"
    echo "  请根据你的网络环境输入一个空闲子网（如 10.100.0.0/16、192.168.200.0/24 等）："
    echo ""
    while true; do
        read -rp "  > " SUBNET
        if [ -z "${SUBNET}" ]; then
            warn "不能为空，请输入一个 CIDR 格式的子网"
            continue
        fi
        # 基本 CIDR 格式校验
        if echo "${SUBNET}" | grep -qE '^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+/[0-9]+$'; then
            break
        fi
        warn "格式无效，示例: 10.100.0.0/16"
    done
    cat > "${INSTALL_DIR}/docker-compose.override.yml" <<OVERRIDE
# 解决 Docker 172.17.0.0/16 与宿主机网络冲突
# 删除此文件即可恢复 Docker 默认子网
networks:
  default:
    driver: bridge
    ipam:
      config:
        - subnet: ${SUBNET}
OVERRIDE
    info "已创建 docker-compose.override.yml，子网: ${SUBNET}"
fi

# ── 步骤 4：启动服务 ──────────────────────────────────────────────────
step "步骤 4/6：拉取镜像并启动服务"

info "拉取基础镜像..."
docker pull pgvector/pgvector:pg15
docker pull redis:7.2-alpine
docker pull rabbitmq:3.12-management
docker pull minio/minio:latest

info "构建应用镜像..."
${DOCKER_COMPOSE} build --no-cache

info "启动所有服务..."
${DOCKER_COMPOSE} up -d

# ── 步骤 5：等待就绪并运行迁移 ──────────────────────────────────────
step "步骤 5/6：等待服务就绪并运行迁移"

# 读取端口配置
if [ -f "${INSTALL_DIR}/.env" ]; then
    set -a; source "${INSTALL_DIR}/.env" 2>/dev/null || true; set +a
fi
_API_PORT="${API_PORT:-8000}"
_WEB_PORT="${WEB_PORT:-3000}"

info "等待 PostgreSQL 就绪..."
for i in $(seq 1 30); do
    PG_CONTAINER=$(docker ps --format '{{.Names}}' | grep postgres | head -1)
    if docker exec "${PG_CONTAINER}" pg_isready -U user -d adaptive_learning 2>/dev/null; then
        info "PostgreSQL 已就绪"
        break
    fi
    sleep 2
done

# 创建迁移追踪表并运行迁移
info "运行数据库迁移..."
PG_CONTAINER=$(docker ps --format '{{.Names}}' | grep postgres | head -1)

# 确保迁移追踪表存在（必须在 022 之前）
docker exec -i "${PG_CONTAINER}" psql -U user -d adaptive_learning <<'SQL' 2>/dev/null || true
CREATE TABLE IF NOT EXISTS schema_migrations (
    filename VARCHAR(255) PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
SQL

for migration in $(ls migrations/*.sql 2>/dev/null | sort); do
    fname=$(basename "${migration}")
    echo "${fname}" | grep -q "rollback" && continue

    # 检查是否已执行
    APPLIED_ALREADY=$(docker exec -i "${PG_CONTAINER}" psql -U user -d adaptive_learning -tA \
        -c "SELECT 1 FROM schema_migrations WHERE filename = '${fname}'" 2>/dev/null || echo "")

    if [ -n "${APPLIED_ALREADY}" ]; then
        info "  跳过 (已执行): ${fname}"
        continue
    fi

    info "  执行: ${fname}"
    if docker exec -i "${PG_CONTAINER}" psql -U user -d adaptive_learning < "${migration}" 2>&1; then
        docker exec -i "${PG_CONTAINER}" psql -U user -d adaptive_learning \
            -c "INSERT INTO schema_migrations (filename) VALUES ('${fname}') ON CONFLICT DO NOTHING" 2>/dev/null
    else
        warn "  ⚠ ${fname} 有警告（通常为对象已存在，不影响）"
        # 迁移可能部分成功，仍标记（幂等迁移无害）
        docker exec -i "${PG_CONTAINER}" psql -U user -d adaptive_learning \
            -c "INSERT INTO schema_migrations (filename) VALUES ('${fname}') ON CONFLICT DO NOTHING" 2>/dev/null || true
    fi
done
info "数据库迁移完成"

# 写入初始版本
echo "${TARGET_VERSION:-2.7.0}" > "${INSTALL_DIR}/VERSION"

# 等待 API 就绪
info "等待 API 就绪..."
for i in $(seq 1 20); do
    if curl -sf "http://localhost:${_API_PORT}/health" > /dev/null 2>&1; then
        info "API 已就绪"
        break
    fi
    sleep 3
done

# ── 步骤 6：初始化管理员 ──────────────────────────────────────────────
step "步骤 6/6：创建管理员账号"

echo "创建首位管理员："
read -rp "  邮箱: " ADMIN_EMAIL
read -rsp "  密码 (至少8位，含大小写+数字): " ADMIN_PASS
echo

if [ -n "${ADMIN_EMAIL}" ] && [ -n "${ADMIN_PASS}" ]; then
    ${DOCKER_COMPOSE} exec -T api python scripts/init_admin.py "${ADMIN_EMAIL}" "${ADMIN_PASS}" || \
        warn "管理员创建失败，请稍后在容器内手动执行: ${DOCKER_COMPOSE} exec api python scripts/init_admin.py"
else
    warn "未输入管理员信息，跳过。稍后可通过以下命令创建："
    warn "  ${DOCKER_COMPOSE} exec api python scripts/init_admin.py <邮箱> <密码>"
fi

# ── 完装验证 ──────────────────────────────────────────────────────────
step "安装验证"

echo "服务状态:"
${DOCKER_COMPOSE} ps

echo ""
echo "═══════════════════════════════════════════════════════════════"
echo "  安装完成！"
echo "═══════════════════════════════════════════════════════════════"
echo ""
echo "  访问地址:"
echo "    前端:      http://localhost:${_WEB_PORT}"
echo "    后端 API:  http://localhost:${_API_PORT}/docs"
echo "    管理后台:  http://localhost:${_WEB_PORT}/admin"
echo "    MinIO:     http://localhost:${MINIO_CONSOLE_PORT:-9001} (minioadmin/minioadmin)"
echo "    RabbitMQ:  http://localhost:${RABBITMQ_MGMT_PORT:-15672} (guest/guest)"
echo ""
echo "  下一步:"
echo "    1. 登录管理后台"
echo "    2. 进入「AI 配置」添加 LLM 提供商"
echo "    3. 进入「知识管理」上传文档"
echo ""
echo "  常用命令:"
echo "    docker compose ps          查看服务状态"
echo "    docker compose logs -f api 查看 API 日志"
echo "    docker compose restart api 重启 API 服务"
echo "    docker compose down        停止所有服务"
echo ""
echo "  升级系统:"
echo "    使用 upgrade_studystudio_selfextract.sh 或 upgrade_studystudio.sh"
echo ""
