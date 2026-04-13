#!/usr/bin/env bash
# install.sh — 把 Phase 0 文件从扁平上传目录分发到 studystudio 对应位置
#
# 上传方式：
#   把下面 6 个文件全部上传到 studystudio 服务器的同一个目录（推荐 ~/studystudio/_phase0/）：
#     install.sh
#     002_ai_config.sql
#     crypto.py
#     llm_gateway.py
#     ai_config_router.py
#     AiConfigView.vue
#
# 用法：
#   cd ~/studystudio           # 必须在项目根目录（含 apps/ 和 docker-compose.yml）
#   bash _phase0/install.sh    # 或任何你放脚本的位置
#
# 脚本会按文件名自动匹配目标路径。

set -euo pipefail

# ─── 颜色 ──────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
info()  { echo -e "${BLUE}[INFO]${NC}  $*"; }
ok()    { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
err()   { echo -e "${RED}[ERR]${NC}   $*" >&2; }

# ─── 源目录 = 脚本所在目录 ────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC="${1:-$SCRIPT_DIR}"
info "源目录：$SRC"

# ─── 目标根 = 当前工作目录 ────────────────────────
TARGET_ROOT="$(pwd)"
if [[ ! -f "$TARGET_ROOT/apps/api/core/llm_gateway.py" ]]; then
    err "当前目录不像 studystudio 项目根：$TARGET_ROOT"
    err "请先 cd 到含 apps/api/core/llm_gateway.py 的目录再跑脚本"
    exit 1
fi
if [[ ! -f "$TARGET_ROOT/docker-compose.yml" ]]; then
    warn "当前目录没有 docker-compose.yml，请确认这是 studystudio 根"
fi
info "目标根：$TARGET_ROOT"

# ─── 文件名 → 目标路径 映射 ───────────────────────
# 格式：文件名|目标相对路径|动作（NEW=新建/REPLACE=替换）
declare -a MAPPING=(
    "002_ai_config.sql|migrations/002_ai_config.sql|NEW"
    "crypto.py|apps/api/core/crypto.py|NEW"
    "llm_gateway.py|apps/api/core/llm_gateway.py|REPLACE"
    "ai_config_router.py|apps/api/modules/admin/ai_config_router.py|NEW"
    "AiConfigView.vue|apps/web/src/views/admin/AiConfigView.vue|NEW"
)

# ─── 预检 ────────────────────────────────────────
info "预检源文件…"
missing=0
for line in "${MAPPING[@]}"; do
    fname="${line%%|*}"
    if [[ ! -f "$SRC/$fname" ]]; then
        err "缺失源文件：$SRC/$fname"
        missing=$((missing + 1))
    fi
done
if (( missing > 0 )); then
    err "共缺失 $missing 个文件，请把它们补齐到 $SRC 再重跑"
    exit 1
fi
ok "5 个源文件全部就位"

# ─── 确认 ────────────────────────────────────────
echo
info "将执行以下操作："
for line in "${MAPPING[@]}"; do
    fname="${line%%|*}"
    rest="${line#*|}"
    tgt="${rest%|*}"
    kind="${rest##*|}"
    if [[ "$kind" == "REPLACE" ]]; then
        echo -e "  ${YELLOW}替换${NC}  $fname  →  $tgt  (自动备份)"
    else
        echo -e "  ${GREEN}新建${NC}  $fname  →  $tgt"
    fi
done
echo
read -rp "确认执行？[y/N] " ans
if [[ ! "$ans" =~ ^[Yy]$ ]]; then
    warn "用户取消"
    exit 0
fi

# ─── 执行 ────────────────────────────────────────
TS="$(date +%Y%m%d_%H%M%S)"
BACKED_UP=""
echo
for line in "${MAPPING[@]}"; do
    fname="${line%%|*}"
    rest="${line#*|}"
    tgt="${rest%|*}"
    kind="${rest##*|}"

    src_file="$SRC/$fname"
    tgt_file="$TARGET_ROOT/$tgt"
    tgt_dir="$(dirname "$tgt_file")"

    if [[ ! -d "$tgt_dir" ]]; then
        mkdir -p "$tgt_dir"
        info "创建目录：$tgt_dir"
    fi

    if [[ "$kind" == "REPLACE" && -f "$tgt_file" ]]; then
        bak="$tgt_file.bak.$TS"
        cp "$tgt_file" "$bak"
        info "已备份旧文件 → $(basename "$bak")"
        BACKED_UP="$bak"
    fi

    if [[ "$kind" == "NEW" && -f "$tgt_file" ]]; then
        warn "目标已存在，跳过不覆盖：$tgt"
        warn "  如确需覆盖，先手动删除后重跑脚本"
        continue
    fi

    cp "$src_file" "$tgt_file"
    ok "$tgt"
done

echo
ok "文件拷贝完成"

# ─── 校验 ────────────────────────────────────────
info "Python 语法校验…"
python3 -c "import ast; ast.parse(open('$TARGET_ROOT/apps/api/core/crypto.py').read())" \
    && ok "crypto.py 语法 OK"
python3 -c "import ast; ast.parse(open('$TARGET_ROOT/apps/api/core/llm_gateway.py').read())" \
    && ok "llm_gateway.py 语法 OK"
python3 -c "import ast; ast.parse(open('$TARGET_ROOT/apps/api/modules/admin/ai_config_router.py').read())" \
    && ok "ai_config_router.py 语法 OK"

# ─── 下一步提示 ──────────────────────────────────
cat <<EOF

════════════════════════════════════════════════════════════════════
 文件已就位。接下来还需要手动做这些：
════════════════════════════════════════════════════════════════════

1) 生成加密密钥并写入 .env（⚠️ 务必备份）
   python3 -c "import secrets,base64; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())"
   echo 'AI_CONFIG_ENCRYPTION_KEY=<粘贴上一步输出>' >> .env

2) 改 5 个现有文件（增量，不是整文件替换）：
   • apps/api/main.py              注册 ai_config_router
   • docker-compose.yml            给 api / celery_worker / celery_worker_knowledge
                                   加 AI_CONFIG_ENCRYPTION_KEY env
   • requirements.txt              加 cryptography>=42.0
   • apps/web/src/router/index.ts  加 /admin/ai-config 路由
   • admin 侧边栏组件              加菜单项

3) 跑数据库迁移
   docker compose exec -T postgres psql -U user -d adaptive_learning \\
       < migrations/002_ai_config.sql

4) rebuild & 重启（加了 cryptography 依赖，必须 rebuild）
   docker compose build api celery_worker celery_worker_knowledge web
   docker compose up -d api celery_worker celery_worker_knowledge web

5) 浏览器打开 /admin/ai-config 开始配置 provider

════════════════════════════════════════════════════════════════════
EOF

if [[ -n "$BACKED_UP" ]]; then
    warn "旧 llm_gateway.py 备份：$BACKED_UP"
    warn "如需回滚：cp '$BACKED_UP' '$TARGET_ROOT/apps/api/core/llm_gateway.py'"
fi
