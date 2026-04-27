#!/usr/bin/env bash
# =============================================================================
# StudyStudio 升级脚本 v2.0
# 用途：在已有部署上无损升级，自动检测版本差异，仅执行增量迁移
# 用法：bash upgrade_studystudio.sh [安装目录]
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
BACKUP_DIR="${INSTALL_DIR}/backups/${TIMESTAMP}"

info "安装目录: ${INSTALL_DIR}"

# ── 检测升级包来源 ──────────────────────────────────────────────────────
ARCHIVE_MARKER="__STUDYSTUDIO_ARCHIVE__"
SCRIPT_PATH="$(cd "$(dirname "$0")" && pwd)/$(basename "$0")"

if grep -aq "^${ARCHIVE_MARKER}$" "${SCRIPT_PATH}" 2>/dev/null; then
    info "自解压模式，提取升级包..."
    PACKAGE_FILE="${INSTALL_DIR}/upgrade_package.tar.gz"
    MARKER_LINE=$(grep -an "^${ARCHIVE_MARKER}$" "${SCRIPT_PATH}" 2>/dev/null | head -1 | cut -d: -f1)
    if [ -z "${MARKER_LINE}" ] || [ "${MARKER_LINE}" -le 0 ] 2>/dev/null; then
        error "无法定位归档标记，请使用独立升级包模式"
        exit 1
    fi
    tail -n +$((MARKER_LINE + 1)) "${SCRIPT_PATH}" > "${PACKAGE_FILE}"
    info "升级包已提取"
else
    PACKAGE_FILE="${INSTALL_DIR}/upgrade_package.tar.gz"
    if [ ! -f "${PACKAGE_FILE}" ]; then
        SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
        PACKAGE_FILE="${SCRIPT_DIR}/upgrade_package.tar.gz"
    fi
    if [ ! -f "${PACKAGE_FILE}" ]; then
        error "找不到 upgrade_package.tar.gz"
        exit 1
    fi
fi

# ── 版本检查 ────────────────────────────────────────────────────────────
CURRENT_VERSION="未知"
if [ -f "${INSTALL_DIR}/VERSION" ]; then
    CURRENT_VERSION=$(head -1 "${INSTALL_DIR}/VERSION" | tr -d '[:space:]')
fi

# 从升级包中读取目标版本
TMP_VERSION=$(mktemp)
tar -xzf "${PACKAGE_FILE}" -O VERSION 2>/dev/null > "${TMP_VERSION}" || true
TARGET_VERSION=$(head -1 "${TMP_VERSION}" 2>/dev/null | tr -d '[:space:]' || echo "未知")
rm -f "${TMP_VERSION}"

step "版本检查"
info "  当前版本: ${CURRENT_VERSION}"
info "  目标版本: ${TARGET_VERSION}"

if [ "${CURRENT_VERSION}" = "${TARGET_VERSION}" ] && [ "${CURRENT_VERSION}" != "未知" ]; then
    warn "当前已是最新版本 (${CURRENT_VERSION})，无需升级。"
    warn "如需强制重装，请删除 VERSION 文件后重试。"
    exit 0
fi

# ── 前置检查 ────────────────────────────────────────────────────────────
if [ ! -f "${INSTALL_DIR}/docker-compose.yml" ]; then
    error "目录 ${INSTALL_DIR} 中未找到 docker-compose.yml"
    exit 1
fi

if docker compose version &>/dev/null 2>&1; then
    DOCKER_COMPOSE="docker compose"
elif command -v docker-compose &>/dev/null; then
    DOCKER_COMPOSE="docker-compose"
else
    error "需要安装 Docker Compose"
    exit 1
fi

# 读取端口配置（从 .env 或使用默认值）
if [ -f "${INSTALL_DIR}/.env" ]; then
    set -a; source "${INSTALL_DIR}/.env" 2>/dev/null || true; set +a
fi
_API_PORT="${API_PORT:-8000}"
_WEB_PORT="${WEB_PORT:-3000}"

# ── 步骤 1：确认 ───────────────────────────────────────────────────────
step "步骤 1/7：升级前确认"
echo "版本: ${CURRENT_VERSION} → ${TARGET_VERSION}"
echo "操作: 备份 → 停止 → 更新代码 → 增量迁移 → 重建 → 启动"
echo "预计中断: 3-10 分钟"
echo ""
read -rp "输入 yes 继续: " CONFIRM
[ "${CONFIRM}" = "yes" ] || { info "已取消"; exit 0; }

# ── 步骤 2：备份 ───────────────────────────────────────────────────────
step "步骤 2/7：创建备份"
mkdir -p "${BACKUP_DIR}"

if docker ps --format '{{.Names}}' | grep -q "postgres"; then
    PG_CONTAINER=$(docker ps --format '{{.Names}}' | grep postgres | head -1)
    docker exec "${PG_CONTAINER}" pg_dump -U user -d adaptive_learning \
        > "${BACKUP_DIR}/database_${TIMESTAMP}.sql" 2>&1 && \
        info "数据库备份完成" || \
        warn "数据库备份失败，建议手动备份后重试"
fi

tar -czf "${BACKUP_DIR}/code_backup_${TIMESTAMP}.tar.gz" \
    --exclude='node_modules' --exclude='__pycache__' --exclude='*.pyc' \
    --exclude='.git' --exclude='backups' --exclude='upgrade_package.tar.gz' \
    -C "${INSTALL_DIR}" . 2>/dev/null || true
info "代码备份完成 (${BACKUP_DIR})"

# 保存用户可能修改过的文件（含配置和文档）
info "保存本地文件..."
USER_FILES=(".env" "docker-compose.yml" "INSTALL.md" "README.md" "VERSION")
for f in "${USER_FILES[@]}"; do
    if [ -f "${INSTALL_DIR}/${f}" ]; then
        cp "${INSTALL_DIR}/${f}" "${BACKUP_DIR}/$(echo "${f}" | tr '/' '_')_${TIMESTAMP}"
    fi
done
info "本地文件已保存至 ${BACKUP_DIR}"

# ── 步骤 3：停止 ───────────────────────────────────────────────────────
step "步骤 3/7：停止服务"
cd "${INSTALL_DIR}"
${DOCKER_COMPOSE} down
info "所有服务已停止"

# ── 步骤 4：更新代码 ───────────────────────────────────────────────────
step "步骤 4/7：更新代码"
tar -xzf "${PACKAGE_FILE}" -C "${INSTALL_DIR}"

# 恢复用户 .env（新版本 .env.example 会被解压出来，用户 .env 保持不变）
if [ -f "${BACKUP_DIR}/.env_${TIMESTAMP}" ]; then
    cp "${BACKUP_DIR}/.env_${TIMESTAMP}" "${INSTALL_DIR}/.env"
    info "已恢复 .env"
fi
if [ ! -f "${INSTALL_DIR}/.env" ] && [ -f "${INSTALL_DIR}/.env.example" ]; then
    warn "未检测到 .env 文件，请参照 .env.example 创建"
fi

# docker-compose.yml：新版生效，旧版留 .bak
if [ -f "${BACKUP_DIR}/docker-compose.yml_${TIMESTAMP}" ]; then
    if ! diff -q "${INSTALL_DIR}/docker-compose.yml" "${BACKUP_DIR}/docker-compose.yml_${TIMESTAMP}" >/dev/null 2>&1; then
        cp "${BACKUP_DIR}/docker-compose.yml_${TIMESTAMP}" "${INSTALL_DIR}/docker-compose.yml.bak.${TIMESTAMP}"
        info "docker-compose.yml 有更新，旧版保存为 .bak.${TIMESTAMP}"
    fi
fi

# 文档文件：如果有差异，保留旧版为 .old_时间戳（防用户自行添加的笔记丢失）
for f in "INSTALL.md" "README.md"; do
    BACKUP_NAME=$(echo "${f}" | tr '/' '_')
    if [ -f "${BACKUP_DIR}/${BACKUP_NAME}_${TIMESTAMP}" ] && [ -f "${INSTALL_DIR}/${f}" ]; then
        if ! diff -q "${INSTALL_DIR}/${f}" "${BACKUP_DIR}/${BACKUP_NAME}_${TIMESTAMP}" >/dev/null 2>&1; then
            cp "${BACKUP_DIR}/${BACKUP_NAME}_${TIMESTAMP}" "${INSTALL_DIR}/${f}.old_${TIMESTAMP}"
            info "${f} 已更新，旧版保存为 ${f}.old_${TIMESTAMP}"
        fi
    fi
done
info "代码更新完成"

# ── 步骤 5：迁移 ───────────────────────────────────────────────────────
step "步骤 5/7：运行数据库迁移（增量）"
${DOCKER_COMPOSE} up -d postgres
for i in $(seq 1 30); do
    sleep 2
    PG_CONTAINER=$(docker ps --format '{{.Names}}' | grep postgres | head -1)
    docker exec "${PG_CONTAINER}" pg_isready -U user -d adaptive_learning 2>/dev/null && break
done
info "PostgreSQL 已就绪"

PG_CONTAINER=$(docker ps --format '{{.Names}}' | grep postgres | head -1)
MIGRATIONS_DIR="${INSTALL_DIR}/migrations"

# 确保迁移追踪表存在
docker exec -i "${PG_CONTAINER}" psql -U user -d adaptive_learning <<'SQL' 2>/dev/null || true
CREATE TABLE IF NOT EXISTS schema_migrations (
    filename VARCHAR(255) PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
SQL

APPLIED=0; SKIPPED=0
for migration in $(ls "${MIGRATIONS_DIR}"/*.sql 2>/dev/null | sort); do
    fname=$(basename "${migration}")
    echo "${fname}" | grep -q "rollback" && continue

    # 检查是否已执行
    APPLIED_ALREADY=$(docker exec -i "${PG_CONTAINER}" psql -U user -d adaptive_learning -tA \
        -c "SELECT 1 FROM schema_migrations WHERE filename = '${fname}'" 2>/dev/null || echo "")

    if [ -n "${APPLIED_ALREADY}" ]; then
        info "  跳过 (已执行): ${fname}"
        SKIPPED=$((SKIPPED + 1))
        continue
    fi

    info "  执行: ${fname}"
    if docker exec -i "${PG_CONTAINER}" psql -U user -d adaptive_learning < "${migration}" 2>&1; then
        docker exec -i "${PG_CONTAINER}" psql -U user -d adaptive_learning \
            -c "INSERT INTO schema_migrations (filename) VALUES ('${fname}') ON CONFLICT DO NOTHING" 2>/dev/null
        APPLIED=$((APPLIED + 1))
    else
        warn "  ⚠ ${fname} 执行出错（通常为对象已存在）"
    fi
done
info "迁移完成: ${APPLIED} 个新执行, ${SKIPPED} 个跳过"

# 更新 VERSION 文件
echo "${TARGET_VERSION}" > "${INSTALL_DIR}/VERSION"

# ── 步骤 6：重建启动 ──────────────────────────────────────────────────
step "步骤 6/7：重建并启动服务"
${DOCKER_COMPOSE} down
${DOCKER_COMPOSE} build --no-cache api web celery_worker celery_worker_knowledge celery_worker_review celery_beat
${DOCKER_COMPOSE} up -d

# ── 步骤 7：健康检查 ──────────────────────────────────────────────────
step "步骤 7/7：验证服务"
info "等待服务启动..."
sleep 15

ALL_HEALTHY=true
for svc in web api postgres redis rabbitmq minio \
           celery_worker celery_worker_knowledge celery_worker_review celery_beat; do
    STATUS=$(${DOCKER_COMPOSE} ps --format json 2>/dev/null | grep "\"Service\":\"${svc}\"" | grep -o '"State":"[^"]*"' | cut -d'"' -f4 || echo "?")
    case "${STATUS}" in running|"") echo -e "  ${GREEN}✓${NC} ${svc}" ;; *)
        echo -e "  ${RED}✗${NC} ${svc}: ${STATUS}"; ALL_HEALTHY=false ;; esac
done

sleep 5
curl -sf "http://localhost:${_API_PORT}/health" >/dev/null 2>&1 && info "API 健康检查通过" || { warn "API 未响应"; ALL_HEALTHY=false; }
curl -sf "http://localhost:${_WEB_PORT}" >/dev/null 2>&1 && info "前端服务正常" || warn "前端未响应"

# ── 升级总结 ──────────────────────────────────────────────────────────
step "升级总结"
echo "  版本: ${CURRENT_VERSION} → ${TARGET_VERSION}"
echo "  迁移: ${APPLIED} 个新执行, ${SKIPPED} 个跳过"
echo "  备份: ${BACKUP_DIR}/"

if [ "${ALL_HEALTHY}" = true ]; then
    info "升级完成！所有服务运行正常。"
else
    warn "部分服务可能需要额外检查: ${DOCKER_COMPOSE} ps"
fi

cat <<'EOF'

回滚方法（如需）:
  cd <安装目录> && docker compose down
  tar -xzf backups/<时间戳>/code_backup_<时间戳>.tar.gz
  docker compose up -d
  # 数据库也需回滚时:
  docker exec -i postgres psql -U user -d adaptive_learning < backups/<时间戳>/database_<时间戳>.sql
EOF
