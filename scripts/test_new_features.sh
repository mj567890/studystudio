#!/bin/bash
# test_new_features.sh
# 测试：账号管理 + Fork Space + 社区广场
# 用法：BASE_URL=http://your-server:8000 EMAIL=your@email.com PASS=yourPass bash test_new_features.sh

BASE_URL="${BASE_URL:-http://localhost:8000}"
EMAIL="${EMAIL:-test@example.com}"
PASS="${PASS:-Test@2024!}"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
ok()   { echo -e "${GREEN}[OK]${NC} $1"; }
fail() { echo -e "${RED}[FAIL]${NC} $1"; }
info() { echo -e "${YELLOW}[INFO]${NC} $1"; }

# ──────────────────────────────────────────
# 1. 登录拿 Token
# ──────────────────────────────────────────
info "=== 1. 登录 ==="
LOGIN=$(curl -s -X POST "$BASE_URL/api/auth/login" \
  -H "Content-Type: application/json" \
  -d "{\"email\":\"$EMAIL\",\"password\":\"$PASS\"}")
echo "$LOGIN" | python3 -m json.tool 2>/dev/null || echo "$LOGIN"

TOKEN=$(echo "$LOGIN" | python3 -c "import sys,json; print(json.load(sys.stdin)['data']['access_token'])" 2>/dev/null)
if [ -z "$TOKEN" ]; then
  fail "获取 Token 失败，请检查账号密码"
  exit 1
fi
ok "Token 获取成功: ${TOKEN:0:20}..."
AUTH="Authorization: Bearer $TOKEN"

# ──────────────────────────────────────────
# 2. 获取当前用户信息
# ──────────────────────────────────────────
info "=== 2. GET /api/users/me ==="
curl -s "$BASE_URL/api/users/me" -H "$AUTH" | python3 -m json.tool

# ──────────────────────────────────────────
# 3. 更新昵称
# ──────────────────────────────────────────
info "=== 3. PATCH /api/users/me (更新昵称) ==="
PATCH_RESP=$(curl -s -X PATCH "$BASE_URL/api/users/me" \
  -H "$AUTH" -H "Content-Type: application/json" \
  -d '{"nickname":"测试昵称_改"}')
echo "$PATCH_RESP" | python3 -m json.tool
CODE=$(echo "$PATCH_RESP" | python3 -c "import sys,json; print(json.load(sys.stdin).get('code'))" 2>/dev/null)
[ "$CODE" = "200" ] && ok "昵称更新成功" || fail "昵称更新失败"

# ──────────────────────────────────────────
# 4. 更新头像 URL
# ──────────────────────────────────────────
info "=== 4. PATCH /api/users/me (更新头像 URL) ==="
curl -s -X PATCH "$BASE_URL/api/users/me" \
  -H "$AUTH" -H "Content-Type: application/json" \
  -d '{"avatar_url":"https://example.com/avatar.png"}' | python3 -m json.tool

# ──────────────────────────────────────────
# 5. 修改密码（弱密码应被拒绝）
# ──────────────────────────────────────────
info "=== 5. POST /api/users/me/password (弱密码，预期 422) ==="
WEAK=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$BASE_URL/api/users/me/password" \
  -H "$AUTH" -H "Content-Type: application/json" \
  -d "{\"old_password\":\"$PASS\",\"new_password\":\"password123\"}")
[ "$WEAK" = "422" ] && ok "弱密码被正确拒绝 (422)" || fail "弱密码未被拒绝，实际返回: $WEAK"

info "=== 5b. POST /api/users/me/password (旧密码错误，预期 400) ==="
WRONG=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$BASE_URL/api/users/me/password" \
  -H "$AUTH" -H "Content-Type: application/json" \
  -d '{"old_password":"WrongPass!999","new_password":"NewTest@2024!"}')
[ "$WRONG" = "400" ] && ok "旧密码错误被正确拒绝 (400)" || fail "旧密码错误未被拒绝，实际返回: $WRONG"

# ──────────────────────────────────────────
# 6. Fork Space
# ──────────────────────────────────────────
info "=== 6. 获取我的 Space 列表 ==="
SPACES=$(curl -s "$BASE_URL/api/spaces" -H "$AUTH")
echo "$SPACES" | python3 -m json.tool
SPACE_ID=$(echo "$SPACES" | python3 -c "
import sys,json
data = json.load(sys.stdin).get('data', [])
if data: print(data[0]['space_id'])
" 2>/dev/null)

if [ -n "$SPACE_ID" ]; then
  info "=== 6b. POST /api/spaces/$SPACE_ID/fork ==="
  FORK=$(curl -s -X POST "$BASE_URL/api/spaces/$SPACE_ID/fork" \
    -H "$AUTH" -H "Content-Type: application/json" \
    -d '{"name":""}')
  echo "$FORK" | python3 -m json.tool
  TASK_ID=$(echo "$FORK" | python3 -c "import sys,json; print(json.load(sys.stdin)['data']['task_id'])" 2>/dev/null)

  if [ -n "$TASK_ID" ]; then
    ok "Fork 发起成功，task_id=$TASK_ID"
    info "=== 6c. 轮询 fork 任务状态（最多 30 秒）==="
    for i in $(seq 1 10); do
      sleep 3
      STATUS=$(curl -s "$BASE_URL/api/fork-tasks/$TASK_ID" -H "$AUTH")
      ST=$(echo "$STATUS" | python3 -c "import sys,json; print(json.load(sys.stdin)['data']['status'])" 2>/dev/null)
      echo "  [$i] status=$ST"
      if [ "$ST" = "done" ]; then ok "Fork 完成"; break; fi
      if [ "$ST" = "failed" ]; then fail "Fork 失败"; echo "$STATUS" | python3 -m json.tool; break; fi
    done
  else
    fail "Fork 接口返回异常"
  fi
else
  info "没有可用 Space，跳过 Fork 测试（请先创建一个 personal space）"
fi

# ──────────────────────────────────────────
# 7. 社区广场
# ──────────────────────────────────────────
info "=== 7. GET /api/community/curations (已批准列表) ==="
curl -s "$BASE_URL/api/community/curations" -H "$AUTH" | python3 -m json.tool

info "=== 7b. GET /api/community/curations/pending (admin 待审核列表) ==="
PENDING=$(curl -s -o /dev/null -w "%{http_code}" "$BASE_URL/api/community/curations/pending" -H "$AUTH")
echo "  HTTP $PENDING（非 admin 应为 403）"

echo ""
info "=== 测试完成 ==="
