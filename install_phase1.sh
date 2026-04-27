#!/usr/bin/env bash
# install_phase1.sh — Phase 1 embedding 管线部署
#
# 上传方式：
#   把下面 4 个文件全部上传到 ~/studystudio/ 根目录：
#     install_phase1.sh
#     embedding_tasks.py
#     patch_ai_config_router.py
#     patch_hooks.py
#
# 用法：
#   cd ~/studystudio
#   bash install_phase1.sh
#
# 做的事：
#   1. 拷贝 embedding_tasks.py → apps/api/tasks/
#   2. 跑 patch_ai_config_router.py（加 /admin/ai/embeddings/backfill 接口）
#   3. 跑 patch_hooks.py（加 4 处审核 hook + 注册新任务模块）
#   4. 自动语法检查
#   5. 重启 celery_worker_knowledge 让新任务生效（api 是 hot reload 自动）
#   6. 提示首次回填命令

# ─── 颜色 ──────────────────────────────────────────
RED=$'\033[0;31m'
GREEN=$'\033[0;32m'
YELLOW=$'\033[1;33m'
BLUE=$'\033[0;34m'
NC=$'\033[0m'

info()  { printf "%s[INFO]%s  %s\n" "$BLUE"   "$NC" "$*"; }
ok()    { printf "%s[OK]%s    %s\n" "$GREEN"  "$NC" "$*"; }
warn()  { printf "%s[WARN]%s  %s\n" "$YELLOW" "$NC" "$*"; }
err()   { printf "%s[ERR]%s   %s\n" "$RED"    "$NC" "$*" >&2; }

TARGET_ROOT="$(pwd)"
if [ ! -f "$TARGET_ROOT/apps/api/main.py" ]; then
    err "当前目录不是 studystudio 根：$TARGET_ROOT"
    exit 1
fi
info "工作目录：$TARGET_ROOT"

TS="$(date +%Y%m%d_%H%M%S)"

# ─── 预检 ────────────────────────────────────────
for f in embedding_tasks.py patch_ai_config_router.py patch_hooks.py; do
    if [ ! -f "$f" ]; then
        err "缺失源文件：$f"
        exit 1
    fi
done
ok "3 个源文件就位"

ERRORS=0

# ═══════════════════════════════════════════════════════════════
# 1. 拷贝 embedding_tasks.py
# ═══════════════════════════════════════════════════════════════
echo
info "[1/5] 拷贝 embedding_tasks.py → apps/api/tasks/"

TGT="apps/api/tasks/embedding_tasks.py"
if [ -f "$TGT" ]; then
    cp "$TGT" "$TGT.bak.$TS"
    info "备份旧版 → $TGT.bak.$TS"
fi
cp embedding_tasks.py "$TGT"
ok "拷贝完成"

python3 -c "import ast; ast.parse(open('$TGT').read())" \
    && ok "语法 OK" \
    || { err "语法错误"; ERRORS=$((ERRORS + 1)); }

# ═══════════════════════════════════════════════════════════════
# 2. patch ai_config_router.py
# ═══════════════════════════════════════════════════════════════
echo
info "[2/5] patch ai_config_router.py（加 /embeddings/backfill 接口）"

# 备份
cp apps/api/modules/admin/ai_config_router.py \
   apps/api/modules/admin/ai_config_router.py.bak.$TS

python3 patch_ai_config_router.py
if [ $? -ne 0 ]; then
    err "patch 失败"
    ERRORS=$((ERRORS + 1))
fi

# ═══════════════════════════════════════════════════════════════
# 3. patch hooks（4 处）
# ═══════════════════════════════════════════════════════════════
echo
info "[3/5] patch hooks（tutorial_tasks + auto_review_tasks + admin/router 共 4 处）"

# 备份要改的文件
cp apps/api/tasks/tutorial_tasks.py     apps/api/tasks/tutorial_tasks.py.bak.$TS
cp apps/api/tasks/auto_review_tasks.py  apps/api/tasks/auto_review_tasks.py.bak.$TS
cp apps/api/modules/admin/router.py     apps/api/modules/admin/router.py.bak.$TS

python3 patch_hooks.py
if [ $? -ne 0 ]; then
    err "hooks patch 失败"
    ERRORS=$((ERRORS + 1))
fi

# ═══════════════════════════════════════════════════════════════
# 4. 全量语法检查
# ═══════════════════════════════════════════════════════════════
echo
info "[4/5] 全量语法检查"

for f in \
    apps/api/tasks/embedding_tasks.py \
    apps/api/tasks/tutorial_tasks.py \
    apps/api/tasks/auto_review_tasks.py \
    apps/api/modules/admin/router.py \
    apps/api/modules/admin/ai_config_router.py
do
    if python3 -c "import ast; ast.parse(open('$f').read())" 2>/dev/null; then
        ok "$f"
    else
        err "$f 语法错误"
        ERRORS=$((ERRORS + 1))
    fi
done

# ═══════════════════════════════════════════════════════════════
# 5. 重启服务
# ═══════════════════════════════════════════════════════════════
echo
info "[5/5] 重启 worker（api 是 hot reload 自动生效，worker 必须重启）"

if [ $ERRORS -gt 0 ]; then
    warn "之前有 $ERRORS 处错误，跳过重启。修复后手动跑："
    warn "  docker compose restart celery_worker celery_worker_knowledge api"
else
    docker compose restart celery_worker celery_worker_knowledge
    info "等待 60 秒让 worker 起来（healthcheck start_period）"
    sleep 60
    docker compose ps celery_worker celery_worker_knowledge api
fi

# ═══════════════════════════════════════════════════════════════
# 总结
# ═══════════════════════════════════════════════════════════════
echo
echo "════════════════════════════════════════════════════════════════════"
if [ $ERRORS -eq 0 ]; then
    ok "Phase 1 部署完成"
else
    warn "有 $ERRORS 处问题，请看上面的错误"
fi
echo "════════════════════════════════════════════════════════════════════"

cat <<'TIPS'

═══ 验证步骤 ═══

# 1. 看 worker 有没有加载 embedding_tasks
docker compose logs celery_worker_knowledge --tail=50 2>&1 | grep -i "embedding"
# 预期看到 "[tasks]" 列表里有 apps.api.tasks.embedding_tasks.embed_single_entity 和 backfill

# 2. 触发首次批量回填（全库）
TOKEN=$(grep "^TOKEN=" /tmp/admin_token 2>/dev/null | cut -d= -f2)  # 如有保存
curl -X POST http://localhost:8000/api/admin/ai/embeddings/backfill \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN" \
  -d '{"space_id": null, "batch_size": 32}'

# 没有 token 的话，去浏览器 F12 → Application → Local Storage → access_token，
# 复制粘贴到 Bearer 后面

# 3. 看回填进度
docker compose logs celery_worker_knowledge --tail=50 -f | grep -i "backfill\|batch committed\|embed"

# 4. 验收 SQL（回填完成后）
docker compose exec -T postgres psql -U user -d adaptive_learning <<'SQL'
SELECT 
  count(*) FILTER (WHERE embedding IS NULL) AS null_cnt,
  count(*) AS total,
  round(100.0 * count(*) FILTER (WHERE embedding IS NULL) / nullif(count(*),0), 1) AS null_pct
FROM knowledge_entities WHERE review_status='approved';
SQL

TIPS
