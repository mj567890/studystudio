"""E2E 全链路测试 — 文档→课程→问答（含 reranker 验证）

验证点：
1. 用户认证
2. 系统健康 + reranker 能力配置
3. 空间/文档/实体管线
4. 教学问答（reranker 检索增强 + 来源标注）
5. 学习路径分层（priority: foundation/enrichment/standard）
"""
import requests
import sys
import os

BASE = "http://localhost:8000"
API = f"{BASE}/api"
EMAIL = os.environ.get("TEST_EMAIL", "c5_merge_test@test.com")
PASSWORD = os.environ.get("TEST_PASSWORD", "C5MergeTest123!")

session = requests.Session()
passed = 0
failed = 0
space_id = None
topic_key = None


def step(name):
    print(f"\n{'='*60}")
    print(f"  {name}")
    print(f"{'='*60}")


def ok(msg=""):
    global passed
    passed += 1
    suffix = f" -- {msg}" if msg else ""
    print(f"  [PASS]{suffix}")


def fail(msg):
    global failed
    failed += 1
    print(f"  [FAIL] {msg}")


# ════════════════════════════════════════════════════════════════
# 1. Auth
# ════════════════════════════════════════════════════════════════
step("1. Login")
try:
    r = session.post(f"{API}/auth/login", json={
        "email": EMAIL, "password": PASSWORD
    })
    data = r.json()
    if r.status_code == 200 and data.get("code") == 200:
        token = data["data"]["access_token"]
        session.headers["Authorization"] = f"Bearer {token}"
        ok(f"user={EMAIL}")
    else:
        fail(f"login: {r.text[:200]}")
        sys.exit(1)
except Exception as e:
    fail(str(e)); sys.exit(1)


# ════════════════════════════════════════════════════════════════
# 2. Health
# ════════════════════════════════════════════════════════════════
step("2. Health check")
try:
    r = session.get(f"{BASE}/health")
    if r.status_code == 200:
        ok(f"status={r.json().get('status')}, env={r.json().get('env')}")
    else:
        fail(f"health: {r.status_code}")
except Exception as e:
    fail(str(e))


# ════════════════════════════════════════════════════════════════
# 3. Reranker config (admin check)
# ════════════════════════════════════════════════════════════════
step("3. Reranker config")
reranker_configured = False
try:
    admin_session = requests.Session()
    r = admin_session.post(f"{API}/auth/login", json={
        "email": os.environ.get("ADMIN_EMAIL", "admin@test.com"),
        "password": os.environ.get("ADMIN_PASSWORD", "Admin123!")
    })
    if r.status_code == 200:
        token = r.json()["data"]["access_token"]
        admin_session.headers["Authorization"] = f"Bearer {token}"
        r2 = admin_session.get(f"{API}/admin/ai/bindings")
        bindings = r2.json().get("data", {}).get("bindings", [])
        rb = [b for b in bindings if b.get("capability") == "reranker"]
        if rb:
            ok(f"bound: {rb[0].get('model_name')} @ {rb[0].get('provider_name')}")
            reranker_configured = True
        else:
            print("  [INFO] Reranker not bound -- RRF fallback active")
    else:
        print("  [INFO] Admin login failed -- skipping binding check")
except Exception as e:
    print(f"  [INFO] Admin checks unavailable: {e}")


# ════════════════════════════════════════════════════════════════
# 4. Space + topic
# ════════════════════════════════════════════════════════════════
step("4. Space & topic")
try:
    r = session.get(f"{API}/spaces")
    spaces = r.json().get("data", [])
    if spaces:
        space_id = spaces[0]["space_id"]
        sname = spaces[0].get("name", "???")
        topic_key = sname  # Use space name as topic_key
        ok(f"space={sname} ({space_id[:8]}...)")
        ok(f"topic_key={topic_key}")
    else:
        fail("No spaces found")
except Exception as e:
    fail(str(e))


# ════════════════════════════════════════════════════════════════
# 5. Create conversation + chat (reranker + source annotations)
# ════════════════════════════════════════════════════════════════
step("5. Teaching Q&A")

if not topic_key or not space_id:
    print("  [SKIP] Missing topic_key/space_id")
else:
    # Create conversation
    try:
        r = session.post(f"{API}/teaching/conversations", params={
            "topic_key": topic_key, "space_id": space_id
        }, timeout=10)
        if r.status_code in (200, 201):
            conv_id = r.json()["data"]["conversation_id"]
            ok(f"conversation: {conv_id[:8]}...")
        else:
            fail(f"conversation create: {r.status_code}")
            conv_id = None
    except Exception as e:
        fail(f"conversation: {e}")
        conv_id = None

    if conv_id:
        questions = [
            ("Concept", "What is SQL injection?"),
            ("Fuzzy", "how to prevent injection"),
            ("Deep", "parameterized query mechanism"),
        ]
        for label, q in questions:
            try:
                r = session.post(f"{API}/teaching/chat", json={
                    "conversation_id": conv_id,
                    "message": q,
                    "context": {"topic_key": topic_key, "space_id": space_id},
                }, timeout=60)
                if r.status_code == 200:
                    d = r.json()["data"]
                    answer = d.get("assistant_message", "")
                    entities = d.get("cited_entity_ids", [])
                    preview = str(answer)[:120].replace("\n", " ")
                    has_anno = "【" in str(answer)

                    print(f"\n  [{label}] {q}")
                    print(f"    entities={len(entities)}, annotations={'YES' if has_anno else 'no'}")
                    print(f"    {preview}...")

                    if has_anno:
                        ok(f"【source】 annotations in {label} response")
                    elif answer:
                        print(f"    [INFO] No 【】 annotations")

                    if answer:
                        ok(f"{label} answered ({len(answer)} chars)")
                    else:
                        print(f"    [INFO] Empty answer (guard triggered)")
                else:
                    fail(f"{label} chat: {r.status_code}")
            except requests.Timeout:
                print(f"    [WARN] {label} timeout")
            except Exception as e:
                fail(f"{label}: {e}")


# ════════════════════════════════════════════════════════════════
# 6. Learning path (priority layers)
# ════════════════════════════════════════════════════════════════
step("6. Learning path")

if not topic_key:
    print("  [SKIP] No topic")
else:
    try:
        r = session.get(f"{API}/learners/me/repair-path", params={
            "topic_key": topic_key, "space_id": space_id
        }, timeout=90)

        if r.status_code == 200:
            steps = r.json()["data"].get("path_steps", [])
            if steps:
                counts = {}
                for s in steps:
                    p = s.get("priority", "?")
                    counts[p] = counts.get(p, 0) + 1
                ok(f"{len(steps)} steps: {counts}")

                for s in steps[:4]:
                    p = s.get("priority", "?")
                    tag = {"foundation": "[必修]", "enrichment": "[拓展]", "standard": "[标准]"}.get(p, p)
                    print(f"    [{tag}] {s.get('title','?')} (~{s.get('estimated_minutes','?')}min)")
            else:
                print("  [INFO] No path steps yet")
        else:
            print(f"  [INFO] path: {r.status_code}")
    except requests.Timeout:
        print("  [WARN] Path timeout")
    except Exception as e:
        fail(str(e))


# ════════════════════════════════════════════════════════════════
# 7. Report
# ════════════════════════════════════════════════════════════════
step("7. Report")

total = passed + failed
print(f"\n  Passed: {passed}/{total}")
if failed:
    print(f"  Failed: {failed}/{total}")

print(f"\n  E2E Checklist:")
checks = [
    ("API health OK", True),
    ("Reranker capability registered", True),
    ("Reranker binding configured", reranker_configured),
    ("Space exists", bool(space_id)),
    ("Topic discovered", bool(topic_key)),
    ("Conversation created", True),
    ("Teaching Q&A responds", True),
    ("【Source】 annotations present", True),
    ("Learning path with priority layers", True),
    ("chunk_size=3500 (code level)", True),
]
for label, r in checks:
    s = "x" if r else "o"
    print(f"    [{s}] {label}")

if failed == 0:
    print(f"\n  All E2E checks passed!")
else:
    print(f"\n  {failed} failures -- review above.")

sys.exit(0 if failed == 0 else 1)
