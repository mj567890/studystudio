#!/usr/bin/env bash
# create_snapshot.sh — 生成项目完整快照

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_ROOT"

TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
OUT_DIR="devdocs/snapshots"
OUT_FILE="$OUT_DIR/snapshot_${TIMESTAMP}.txt"
mkdir -p "$OUT_DIR"

DB_URL=""
if [[ -f .env ]]; then
    DB_URL=$(grep -E "^DATABASE_URL=" .env | head -1 | cut -d= -f2- || true)
fi
if [[ -z "$DB_URL" ]]; then
    echo "WARN: .env 里没找到 DATABASE_URL,DB 相关段落会留空" >&2
    DB_USER=""
    DB_NAME=""
else
    DB_USER=$(echo "$DB_URL" | sed -E 's|^[a-z+]+://([^:]+):.*$|\1|')
    DB_NAME=$(echo "$DB_URL" | sed -E 's|^.*/([^/?]+)(\?.*)?$|\1|')
fi

EXCLUDE_DIRS=(
    ".git"
    ".venv"
    "venv"
    "node_modules"
    "__pycache__"
    "devdocs/snapshots"
    "devdocs/archive"
    "devdocs/patches"
    "_backups"
    "apps/api/assets/fonts"
    "apps/web/dist"
    "apps/web/node_modules"
    ".mypy_cache"
    ".pytest_cache"
)

build_find_excludes() {
    local args=()
    for d in "${EXCLUDE_DIRS[@]}"; do
        args+=("-path" "./$d" "-prune" "-o")
    done
    printf '%s ' "${args[@]}"
}

section() {
    echo "" >> "$OUT_FILE"
    echo "================================================================================" >> "$OUT_FILE"
    echo "== $1" >> "$OUT_FILE"
    echo "================================================================================" >> "$OUT_FILE"
    echo "" >> "$OUT_FILE"
}

echo "[1/5] 写入元信息..."
> "$OUT_FILE"
cat >> "$OUT_FILE" <<EOF
================================================================================
== StudyStudio Project Snapshot
================================================================================

生成时间: $(date '+%Y-%m-%d %H:%M:%S %z')
主机名:   $(hostname)
项目根:   $PROJECT_ROOT
脚本版本: create_snapshot.sh v1.0

Git 状态:
$(git -C "$PROJECT_ROOT" log -1 --pretty='  commit: %H%n  作者:   %an <%ae>%n  日期:   %ai%n  信息:   %s' 2>/dev/null || echo "  (非 git 仓库)")
$(git -C "$PROJECT_ROOT" status --short 2>/dev/null | sed 's/^/  /' || echo "")

排除规则:
$(printf '  - %s\n' "${EXCLUDE_DIRS[@]}")

DB 连接(从 .env 解析):
  user: ${DB_USER:-<未解析>}
  db:   ${DB_NAME:-<未解析>}
EOF

echo "[2/5] 生成目录树..."
section "2. 项目目录树"

eval "find . $(build_find_excludes) -type f -print" 2>/dev/null | \
    grep -v "\.pyc$" | \
    grep -v "\.bak" | \
    sort >> "$OUT_FILE"

echo "[3/5] 导出源代码..."
section "3. 源代码全文"

INCLUDE_EXTS=(py vue ts js yaml yml sh sql toml conf cfg ini md html css)

dump_file() {
    local f="$1"
    if [[ -f "$f" ]]; then
        local size
        size=$(stat -c%s "$f" 2>/dev/null || stat -f%z "$f" 2>/dev/null || echo 0)
        if [[ "$size" -gt 204800 ]]; then
            echo "" >> "$OUT_FILE"
            echo ">>>>> FILE: $f ($size bytes, SKIPPED - too large) <<<<<" >> "$OUT_FILE"
            return
        fi
        echo "" >> "$OUT_FILE"
        echo ">>>>> FILE: $f <<<<<" >> "$OUT_FILE"
        cat "$f" >> "$OUT_FILE"
        echo "" >> "$OUT_FILE"
        echo "<<<<< END: $f <<<<<" >> "$OUT_FILE"
    fi
}

# 构造 find 的 -name 参数数组(避免 eval 的通配符展开问题)
name_args=()
first=1
for ext in "${INCLUDE_EXTS[@]}"; do
    if [[ $first -eq 1 ]]; then
        name_args+=(-name "*.$ext")
        first=0
    else
        name_args+=(-o -name "*.$ext")
    fi
done

# 构造 -path ... -prune 的排除数组
prune_args=()
for d in "${EXCLUDE_DIRS[@]}"; do
    prune_args+=(-path "./$d" -prune -o)
done

mapfile -t files < <(find . "${prune_args[@]}" -type f \( "${name_args[@]}" \) -print 2>/dev/null | \
    grep -v "\.bak" | \
    grep -v "package-lock\.json" | \
    sort)

echo "  收录 ${#files[@]} 个源文件"
for f in "${files[@]}"; do
    dump_file "$f"
done

echo "[4/5] 导出 DB schema..."
section "4. DB Schema (所有表结构)"

if [[ -n "$DB_USER" && -n "$DB_NAME" ]] && docker ps --format '{{.Names}}' | grep -q studystudio-postgres-1; then
    tables=$(docker exec studystudio-postgres-1 psql -U "$DB_USER" -d "$DB_NAME" -tA -c \
        "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename;")

    for t in $tables; do
        echo "" >> "$OUT_FILE"
        echo ">>>>> TABLE: $t <<<<<" >> "$OUT_FILE"
        docker exec studystudio-postgres-1 psql -U "$DB_USER" -d "$DB_NAME" -c "\d $t" >> "$OUT_FILE" 2>&1
    done
else
    echo "  (DB 不可用或未配置,跳过)" >> "$OUT_FILE"
fi

echo "[5/5] 导出关键配置数据..."
section "5. 关键配置表数据"

if [[ -n "$DB_USER" && -n "$DB_NAME" ]] && docker ps --format '{{.Names}}' | grep -q studystudio-postgres-1; then

    run_sql() {
        local label="$1"
        local sql="$2"
        echo "" >> "$OUT_FILE"
        echo ">>>>> QUERY: $label <<<<<" >> "$OUT_FILE"
        docker exec studystudio-postgres-1 psql -U "$DB_USER" -d "$DB_NAME" -c "$sql" >> "$OUT_FILE" 2>&1
    }

    run_sql "ai_providers (不含 api_key)" "
        SELECT provider_id, name, kind, base_url, enabled, last_test_ok, created_at
        FROM ai_providers ORDER BY created_at;"

    run_sql "ai_capability_bindings + providers" "
        SELECT b.capability, p.name AS provider, b.model_name, b.priority, b.enabled
        FROM ai_capability_bindings b
        JOIN ai_providers p ON p.provider_id = b.provider_id
        ORDER BY b.capability, b.priority;"

    run_sql "knowledge_spaces" "
        SELECT space_id, space_type, name, description, created_at
        FROM knowledge_spaces ORDER BY space_type, created_at;"

    run_sql "knowledge_entities 按 domain_tag 聚合" "
        SELECT domain_tag, space_type, review_status, COUNT(*)
        FROM knowledge_entities
        GROUP BY domain_tag, space_type, review_status
        ORDER BY domain_tag, review_status;"

    run_sql "skill_blueprints" "
        SELECT b.topic_key, b.title, b.version, b.status, b.updated_at,
               (SELECT COUNT(*) FROM skill_chapters WHERE blueprint_id = b.blueprint_id) AS chapters,
               (SELECT COUNT(*) FROM skill_stages   WHERE blueprint_id = b.blueprint_id) AS stages
        FROM skill_blueprints b
        ORDER BY b.updated_at DESC;"

    run_sql "skill_stages (所有蓝图的 stage 列表)" "
        SELECT b.topic_key, s.stage_order, s.title, s.stage_type,
               (SELECT COUNT(*) FROM skill_chapters WHERE stage_id = s.stage_id) AS chapters
        FROM skill_blueprints b
        JOIN skill_stages s ON s.blueprint_id = b.blueprint_id
        ORDER BY b.topic_key, s.stage_order;"

else
    echo "  (DB 不可用或未配置,跳过)" >> "$OUT_FILE"
fi

echo ""
echo "✓ Snapshot 生成完毕"
echo "  文件: $OUT_FILE"
echo "  大小: $(du -h "$OUT_FILE" | cut -f1)"
echo "  行数: $(wc -l < "$OUT_FILE") 行"
