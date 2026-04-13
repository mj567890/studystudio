#!/usr/bin/env bash
# patch.sh — Phase 0 集成改动自动化（安全版）
#
# 用法：
#   cd ~/studystudio
#   bash patch.sh
#
# 做 4 件事（前端 2 个文件不自动改，最后让你手动 cat 发给 Claude）：
#   1. 生成 AI_CONFIG_ENCRYPTION_KEY 写 .env
#   2. patch apps/api/main.py（加 import + include_router）
#   3. patch requirements.txt（加 cryptography）
#   4. patch docker-compose.yml（三个服务 env 加 AI_CONFIG_ENCRYPTION_KEY）
#
# 特点：
#   • 不用 set -e，每步独立检查
#   • Python 代码用 <<'EOF' 引号 heredoc，隔离 shell 替换
#   • 变量通过环境变量传给 Python
#   • 幂等：已做过的步骤会跳过
#   • 所有被改文件先备份 .bak.YYYYMMDD_HHMMSS

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
skip()  { printf "%s[SKIP]%s  %s\n" "$YELLOW" "$NC" "$*"; }

TARGET_ROOT="$(pwd)"
if [ ! -f "$TARGET_ROOT/apps/api/main.py" ]; then
    err "当前目录不像 studystudio 项目根：$TARGET_ROOT"
    err "请先 cd 到含 apps/api/main.py 的目录"
    exit 1
fi
info "工作目录：$TARGET_ROOT"

TS="$(date +%Y%m%d_%H%M%S)"
export TS TARGET_ROOT

ERRORS=0

echo
echo "════════════════════════════════════════════════════════════"
echo " Phase 0 自动集成补丁"
echo "════════════════════════════════════════════════════════════"

# ═══════════════════════════════════════════════════════════════
# 步骤 1：生成 .env 密钥
# ═══════════════════════════════════════════════════════════════
echo
info "[1/4] AI_CONFIG_ENCRYPTION_KEY → .env"

ENV_FILE="$TARGET_ROOT/.env"
touch "$ENV_FILE"

if grep -q "^AI_CONFIG_ENCRYPTION_KEY=" "$ENV_FILE" 2>/dev/null; then
    skip ".env 已有 AI_CONFIG_ENCRYPTION_KEY"
else
    cp "$ENV_FILE" "$ENV_FILE.bak.$TS" 2>/dev/null || true
    NEW_KEY="$(python3 -c 'import secrets,base64; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())')"
    if [ -z "$NEW_KEY" ]; then
        err "密钥生成失败"
        ERRORS=$((ERRORS + 1))
    else
        {
            echo ""
            echo "# ─ AI 配置加密密钥（Phase 0，切勿丢失）─"
            echo "AI_CONFIG_ENCRYPTION_KEY=$NEW_KEY"
        } >> "$ENV_FILE"
        ok "已写入 .env"
        echo
        echo "    ┌────────────────────────────────────────────────────────┐"
        echo "    │ ⚠️  立即备份这个密钥（丢了 = 所有加密 api_key 作废）：  │"
        echo "    └────────────────────────────────────────────────────────┘"
        echo "    $NEW_KEY"
        echo
    fi
fi

# ═══════════════════════════════════════════════════════════════
# 步骤 2：patch main.py
# ═══════════════════════════════════════════════════════════════
echo
info "[2/4] patch apps/api/main.py"

export PATCH_FILE="$TARGET_ROOT/apps/api/main.py"

python3 - <<'PYEOF'
import os
import sys
import ast
from pathlib import Path

path = Path(os.environ["PATCH_FILE"])
ts = os.environ["TS"]

try:
    content = path.read_text(encoding="utf-8")
except Exception as e:
    print(f"[ERR]  读取失败: {e}", file=sys.stderr)
    sys.exit(1)

original = content
changed = False

# ── 1. import ──
import_anchor = "from apps.api.modules.admin.router import router as admin_router"
new_import = "from apps.api.modules.admin.ai_config_router import router as ai_config_router"

if new_import in content:
    print("[SKIP] main.py 已有 ai_config_router import")
elif import_anchor in content:
    content = content.replace(
        import_anchor,
        import_anchor + "\n" + new_import,
        1,
    )
    changed = True
    print("[OK]   添加 ai_config_router import")
else:
    print("[ERR]  找不到 admin router import 锚点", file=sys.stderr)
    sys.exit(2)

# ── 2. include_router ──
if "include_router(ai_config_router)" in content:
    print("[SKIP] main.py 已有 include_router(ai_config_router)")
else:
    # 找 app.include_router(admin_router) 所在行，在其后插入同缩进新行
    lines = content.split("\n")
    out = []
    inserted = False
    for line in lines:
        out.append(line)
        if not inserted and "app.include_router(admin_router)" in line:
            # 计算缩进
            indent = line[: len(line) - len(line.lstrip())]
            out.append(indent + "app.include_router(ai_config_router)")
            inserted = True
    if inserted:
        content = "\n".join(out)
        changed = True
        print("[OK]   添加 include_router(ai_config_router)")
    else:
        print("[ERR]  找不到 app.include_router(admin_router) 锚点", file=sys.stderr)
        sys.exit(2)

# ── 写回 + 语法检查 ──
if changed:
    backup_path = path.parent / (path.name + ".bak." + ts)
    backup_path.write_text(original, encoding="utf-8")
    print(f"[OK]   备份 {backup_path.name}")
    path.write_text(content, encoding="utf-8")

try:
    ast.parse(content)
    print("[OK]   main.py 语法 OK")
except SyntaxError as e:
    print(f"[ERR]  语法错误: {e}", file=sys.stderr)
    sys.exit(3)
PYEOF

if [ $? -ne 0 ]; then
    err "main.py patch 失败"
    ERRORS=$((ERRORS + 1))
fi

# ═══════════════════════════════════════════════════════════════
# 步骤 3：patch requirements.txt
# ═══════════════════════════════════════════════════════════════
echo
info "[3/4] patch requirements.txt"

REQ_FOUND=0
for req in "$TARGET_ROOT/requirements.txt" "$TARGET_ROOT/apps/api/requirements.txt"; do
    if [ -f "$req" ]; then
        REQ_FOUND=1
        if grep -qi "^cryptography" "$req"; then
            skip "$req 已有 cryptography"
        else
            cp "$req" "$req.bak.$TS"
            echo "cryptography>=42.0" >> "$req"
            ok "$req 添加 cryptography>=42.0"
        fi
    fi
done

if [ $REQ_FOUND -eq 0 ]; then
    warn "找不到 requirements.txt，跳过"
fi

# ═══════════════════════════════════════════════════════════════
# 步骤 4：patch docker-compose.yml
# ═══════════════════════════════════════════════════════════════
echo
info "[4/4] patch docker-compose.yml"

export DC_FILE="$TARGET_ROOT/docker-compose.yml"

if [ ! -f "$DC_FILE" ]; then
    warn "找不到 docker-compose.yml，跳过"
else
    python3 - <<'PYEOF'
import os
import re
import sys
from pathlib import Path

path = Path(os.environ["DC_FILE"])
ts = os.environ["TS"]

try:
    content = path.read_text(encoding="utf-8")
except Exception as e:
    print(f"[ERR]  读取失败: {e}", file=sys.stderr)
    sys.exit(1)

if "AI_CONFIG_ENCRYPTION_KEY" in content:
    print("[SKIP] docker-compose.yml 已有 AI_CONFIG_ENCRYPTION_KEY")
    sys.exit(0)

# 策略：每处 OPENAI_API_KEY: 行下方同缩进插入新 env
# 注意：YAML 里 env 有两种常见格式：
#   dict 形式：  OPENAI_API_KEY: ${OPENAI_API_KEY}
#   list 形式：  - OPENAI_API_KEY=${OPENAI_API_KEY}
# 分别匹配
dict_pattern = re.compile(
    r'^(?P<indent>[ \t]+)OPENAI_API_KEY:\s*[^\n]*$',
    re.MULTILINE,
)
list_pattern = re.compile(
    r'^(?P<indent>[ \t]+)- OPENAI_API_KEY=[^\n]*$',
    re.MULTILINE,
)

dict_matches = list(dict_pattern.finditer(content))
list_matches = list(list_pattern.finditer(content))

if not dict_matches and not list_matches:
    print("[ERR]  找不到 OPENAI_API_KEY 锚点", file=sys.stderr)
    print("       请手动给 api / celery_worker / celery_worker_knowledge 三个服务加 env：", file=sys.stderr)
    # 用字符串拼接避免 f-string 大括号转义坑
    example = "          AI_CONFIG_ENCRYPTION_KEY: " + chr(36) + "{AI_CONFIG_ENCRYPTION_KEY}"
    print("       " + example, file=sys.stderr)
    sys.exit(1)

# 决定用哪种格式
if dict_matches:
    matches = dict_matches
    fmt = "dict"
    print(f"[INFO] 检测到 dict 格式 env，找到 {len(matches)} 处 OPENAI_API_KEY")
else:
    matches = list_matches
    fmt = "list"
    print(f"[INFO] 检测到 list 格式 env，找到 {len(matches)} 处 OPENAI_API_KEY")

# 从后往前插入，避免偏移问题
new_content = content
dollar = chr(36)  # 避免在 Python 字符串中写 $ 的歧义
for m in reversed(matches):
    indent = m.group("indent")
    if fmt == "dict":
        insertion = "\n" + indent + "AI_CONFIG_ENCRYPTION_KEY: " + dollar + "{AI_CONFIG_ENCRYPTION_KEY}"
    else:
        insertion = "\n" + indent + "- AI_CONFIG_ENCRYPTION_KEY=" + dollar + "{AI_CONFIG_ENCRYPTION_KEY}"
    end_pos = m.end()
    new_content = new_content[:end_pos] + insertion + new_content[end_pos:]

backup_path = path.parent / (path.name + ".bak." + ts)
backup_path.write_text(content, encoding="utf-8")
print(f"[OK]   备份 {backup_path.name}")
path.write_text(new_content, encoding="utf-8")
print("[OK]   docker-compose.yml 已更新")
PYEOF

    if [ $? -ne 0 ]; then
        err "docker-compose.yml patch 失败"
        ERRORS=$((ERRORS + 1))
    fi
fi

# ═══════════════════════════════════════════════════════════════
# 总结
# ═══════════════════════════════════════════════════════════════
echo
echo "════════════════════════════════════════════════════════════"
if [ $ERRORS -eq 0 ]; then
    ok "后端 4 处改动全部完成"
else
    warn "有 $ERRORS 处改动失败，请看上面的错误信息"
fi
echo "════════════════════════════════════════════════════════════"

cat <<'TIPS'

════════════════════════════════════════════════════════════════════
 前端 2 个文件需要手动改（不自动 cat，避免淹没终端）
════════════════════════════════════════════════════════════════════

请分别执行这两个命令，把输出完整复制发给 Claude：

  cat apps/web/src/router/index.ts
  cat apps/web/src/views/AdminLayoutView.vue

Claude 会基于你的实际文件结构给出精准的改动指令。

════════════════════════════════════════════════════════════════════
 前端改完后的剩余步骤
════════════════════════════════════════════════════════════════════

# 1. 跑数据库迁移
docker compose exec -T postgres psql -U user -d adaptive_learning \
    < migrations/002_ai_config.sql

# 2. rebuild（因为加了 cryptography 依赖）
docker compose build api celery_worker celery_worker_knowledge web
docker compose up -d api celery_worker celery_worker_knowledge web

# 3. 看启动日志
docker compose logs api --tail=30 2>&1 | grep -v health

# 4. 浏览器打开 /admin/ai-config 开始配置 provider

TIPS
