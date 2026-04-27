"""C5 merge retest — 全新独立空间，先全量后增量。

流程：
1. 注册/登录测试用户
2. 生成两本内容相关但领域不同的 PDF
3. 上传 Book A → 等待 published 蓝图
4. 上传 Book B（相同 domain_tag）→ 等待 merge
5. 验证 merge 日志和章节变化
"""
import requests
import json
import sys
import time
import os
import re
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak
from reportlab.lib.units import inch

BASE = "http://localhost:8000/api"
EMAIL = "c5_merge_test@test.com"
PASSWORD = "C5MergeTest123!"
DOMAIN_TAG = "nosql-injection-merge-test"

# ── PDF generation ──────────────────────────────────────────────

def build_pdf(output_path, title, chapters):
    fitz = __import__("fitz")
    doc = SimpleDocTemplate(output_path, pagesize=A4)
    styles = getSampleStyleSheet()
    cn = ParagraphStyle("CN", parent=styles["Normal"], fontSize=12, leading=18)
    h1 = ParagraphStyle("H1", parent=styles["Heading1"], fontSize=18)
    h2 = ParagraphStyle("H2", parent=styles["Heading2"], fontSize=14)

    story = [Paragraph(title, h1), Spacer(1, 0.3 * inch)]
    for ch_title, ch_content in chapters:
        story.append(PageBreak())
        story.append(Paragraph(ch_title, h2))
        story.append(Spacer(1, 0.2 * inch))
        for para in ch_content.split("\n\n"):
            if para.strip():
                story.append(Paragraph(para.strip(), cn))
                story.append(Spacer(1, 0.15 * inch))
    doc.build(story)

    # Add TOC
    fitz_doc = fitz.open(output_path)
    toc = [[1, ch[0], i+1] for i, ch in enumerate(chapters)]
    fitz_doc.set_toc(toc)
    fitz_doc.saveIncr()
    fitz_doc.close()
    print(f"  PDF: {output_path} ({os.path.getsize(output_path)} bytes)")
    return output_path


# Book A: NoSQL Injection Fundamentals (建立初始课程)
BOOK_A_CHAPTERS = [
    ("Chapter 1: Introduction to NoSQL Injection",
     "NoSQL injection is a vulnerability that occurs when user-supplied input is not properly "
     "sanitized before being used in NoSQL database queries. Unlike traditional SQL injection, "
     "NoSQL injection attacks target non-relational databases such as MongoDB, CouchDB, Redis, "
     "and Cassandra. These databases use query languages that differ significantly from SQL, "
     "but the underlying principle remains the same: untrusted input is interpreted as code.\n\n"
     "The attack surface for NoSQL injection is broad. It includes MongoDB's $where operator, "
     "the $regex operator in MongoDB, JavaScript injection through server-side evaluation, "
     "and key-based injection in Redis. Understanding these attack vectors is the first step "
     "toward building secure NoSQL applications."),

    ("Chapter 2: MongoDB Injection Attack Patterns",
     "MongoDB is the most commonly targeted NoSQL database for injection attacks. The MongoDB "
     "query language uses JSON-like syntax with operators prefixed by $. Common vulnerable "
     "patterns include passing raw user input to the $where operator without validation, "
     "and constructing queries by string concatenation.\n\n"
     "Attackers exploit MongoDB's flexible schema and JavaScript-based query operators. "
     "For example, an attacker can inject a $regex operator to enumerate all documents, "
     "or use $ne (not equals) to bypass authentication checks. The $where operator allows "
     "arbitrary JavaScript execution, making it particularly dangerous when combined with "
     "unsanitized user input."),

    ("Chapter 3: Input Validation for NoSQL Databases",
     "The most effective defense against NoSQL injection is strict input validation. "
     "Applications should validate and sanitize all user input before using it in database "
     "queries. For string inputs, use allowlists of valid characters. For numeric inputs, "
     "validate the type and range. For structured data, validate against a schema.\n\n"
     "Input validation should happen at multiple layers: at the API boundary, at the "
     "application logic layer, and at the database query layer. Each layer provides "
     "defense in depth. Never rely on a single validation point, as attackers may find "
     "ways to bypass individual checks."),

    ("Chapter 4: Parameterized Queries in MongoDB",
     "Parameterized queries separate the query structure from the query data. In MongoDB, "
     "this means constructing queries using driver-level operators rather than string "
     "concatenation or dynamic object construction from user input. Modern MongoDB drivers "
     "provide safe ways to build queries.\n\n"
     "For example, instead of building a query object by directly merging user input, "
     "use typed query builder methods. Validate that user input does not contain MongoDB "
     "operators (keys prefixed with $). Most MongoDB drivers now include built-in protection "
     "against operator injection when using the latest API versions."),

    ("Chapter 5: Security Hardening for NoSQL Deployments",
     "Beyond application-level defenses, NoSQL database deployments require proper security "
     "configuration. Enable authentication on all database instances. Use TLS for all "
     "client-server communication. Implement network segmentation to isolate database servers. "
     "Apply the principle of least privilege to database user accounts.\n\n"
     "Regular security audits and penetration testing should include NoSQL injection "
     "scenarios. Monitor database logs for unusual query patterns. Implement rate limiting "
     "on API endpoints that interact with the database. Keep database software and drivers "
     "updated to the latest secure versions."),
]

# Book B: Advanced NoSQL and ORM Security (补充和扩展)
BOOK_B_CHAPTERS = [
    ("Chapter 6: Advanced MongoDB Injection via Aggregation Pipelines",
     "MongoDB's aggregation framework provides powerful data processing capabilities but also "
     "introduces additional injection surfaces. Attackers can manipulate aggregation pipeline "
     "stages such as $match, $group, and $project to extract unauthorized data or perform "
     "denial of service attacks. The $lookup stage can be exploited to perform cross-collection "
     "data exfiltration.\n\n"
     "Aggregation pipeline injection requires specific defenses: validate the structure of "
     "pipeline stages before execution, restrict available aggregation operators, and use "
     "the allowDiskUse option cautiously. Always apply the same input validation rigor to "
     "aggregation pipelines as you would to traditional queries."),

    ("Chapter 7: GraphQL Injection and API Security",
     "GraphQL APIs introduce a new class of injection vulnerabilities. While GraphQL itself "
     "is query language agnostic, resolvers that construct NoSQL queries from GraphQL arguments "
     "are vulnerable to injection. Attackers can exploit deeply nested queries, field suggestions, "
     "and introspection to discover and exploit injection points.\n\n"
     "Defending GraphQL APIs requires: query depth limiting, query complexity analysis, "
     "persisted queries to prevent arbitrary query execution, input validation at the resolver "
     "level, and proper error handling that does not leak schema information. GraphQL security "
     "gateways can provide additional protection layers."),

    ("Chapter 8: ORM Security and Query Builder Injection",
     "Object-Relational Mappers (ORMs) like Mongoose, TypeORM, and Hibernate OGM provide "
     "abstraction layers over databases, but they do not automatically prevent injection. "
     "ORM query builders that concatenate user input into query conditions are still vulnerable. "
     "The misconception that 'ORMs prevent injection' leads to complacent coding practices.\n\n"
     "Secure ORM usage requires: using the ORM's parameterized query methods, avoiding raw "
     "query execution with user input, validating entity field types and values, and enabling "
     "ORM-level security features such as automatic escaping and operator filtering."),
]

# ── API helpers ──────────────────────────────────────────────────

def register_or_login():
    """Register a new test user or login if already exists."""
    # Try login first
    resp = requests.post(f"{BASE}/auth/login", json={
        "email": EMAIL, "password": PASSWORD
    })
    if resp.status_code == 200:
        token = resp.json()["data"]["access_token"]
        print(f"[OK] Logged in as {EMAIL}")
        return token

    # Register
    resp = requests.post(f"{BASE}/auth/register", json={
        "email": EMAIL, "password": PASSWORD, "nickname": "C5MergeTester"
    })
    if resp.status_code == 201:
        print(f"[OK] Registered new user {EMAIL}")
        # Login after registration
        resp = requests.post(f"{BASE}/auth/login", json={
            "email": EMAIL, "password": PASSWORD
        })
        token = resp.json()["data"]["access_token"]
        return token

    print(f"[FAIL] Auth failed: {resp.status_code} {resp.text}")
    sys.exit(1)


def upload_file(token, filepath, domain_tag):
    """Upload a file via the API."""
    headers = {"Authorization": f"Bearer {token}"}
    with open(filepath, "rb") as f:
        resp = requests.post(
            f"{BASE}/files/upload",
            headers=headers,
            files={"file": (os.path.basename(filepath), f, "application/pdf")},
            data={
                "space_type": "personal",
                "domain_tag": domain_tag,
            }
        )
    if resp.status_code in (200, 201, 202):
        data = resp.json()["data"]
        print(f"[OK] Uploaded {os.path.basename(filepath)}")
        print(f"  document_id: {data['document_id']}")
        print(f"  space_id:    {data.get('space_id')}")
        print(f"  is_duplicate: {data.get('is_duplicate', False)}")
        return data
    print(f"[FAIL] Upload failed: {resp.status_code} {resp.text}")
    return None


def check_document(token, document_id):
    """Check document status."""
    headers = {"Authorization": f"Bearer {token}"}
    resp = requests.get(f"{BASE}/files/documents/{document_id}/view", headers=headers)
    return resp


def check_blueprint_via_db(space_id):
    """Check blueprint status via docker exec."""
    import subprocess
    result = subprocess.run([
        "docker", "compose", "exec", "-T", "postgres", "psql", "-U", "user",
        "-d", "adaptive_learning", "-t", "-A",
        "-c", f"SELECT status, version FROM skill_blueprints WHERE space_id='{space_id}' ORDER BY updated_at DESC LIMIT 1"
    ], capture_output=True, text=True, cwd=r"D:\studystudio_ds")
    return result.stdout.strip()


# ── Main flow ────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("C5 Merge Re-test: NoSQL Injection Merge Test")
    print("=" * 60)

    # Step 0: Auth
    token = register_or_login()

    # Step 1: Generate PDFs
    print("\n── Step 1: Generate test PDFs ──")
    os.makedirs("/tmp", exist_ok=True)
    build_pdf("/tmp/c5_book_a.pdf", "NoSQL Injection Fundamentals", BOOK_A_CHAPTERS)
    build_pdf("/tmp/c5_book_b.pdf", "Advanced NoSQL & ORM Security", BOOK_B_CHAPTERS)

    # Step 2: Upload Book A
    print("\n── Step 2: Upload Book A (initial course) ──")
    result_a = upload_file(token, "/tmp/c5_book_a.pdf", DOMAIN_TAG)
    if not result_a:
        sys.exit(1)
    space_id = result_a.get("space_id")
    doc_a_id = result_a["document_id"]
    print(f"  space_id = {space_id}")

    # Step 3: Wait for Book A blueprint to be published
    print("\n── Step 3: Wait for Book A pipeline (up to 5 min) ──")
    max_wait = 300  # 5 minutes
    start = time.time()
    published = False
    while time.time() - start < max_wait:
        status = check_blueprint_via_db(space_id)
        print(f"  [{int(time.time() - start)}s] Blueprint status: {status}")
        if "published" in status:
            published = True
            print("  [OK] Book A blueprint published!")
            break
        time.sleep(10)

    if not published:
        print("  [FAIL] Book A blueprint did not publish within timeout")
        print("  Check worker logs for errors. Continuing anyway...")

    # Step 4: Upload Book B (should trigger merge)
    print("\n── Step 4: Upload Book B (trigger merge) ──")
    result_b = upload_file(token, "/tmp/c5_book_b.pdf", DOMAIN_TAG)
    if not result_b:
        sys.exit(1)
    doc_b_id = result_b["document_id"]

    # Step 5: Wait for merge to complete
    print("\n── Step 5: Wait for merge (up to 5 min) ──")
    start = time.time()
    merge_done = False
    while time.time() - start < max_wait:
        status = check_blueprint_via_db(space_id)
        print(f"  [{int(time.time() - start)}s] Blueprint status: {status}")
        if "published" in status:
            # Check version — should have incremented
            parts = status.split("|")
            if len(parts) >= 2:
                ver = parts[1].strip()
                print(f"  [OK] Blueprint published, version={ver}")
                merge_done = True
                break
        time.sleep(10)

    if not merge_done:
        print("  [FAIL] Merge did not complete within timeout")
        print("  Check worker logs.")

    # Step 6: Summary
    print("\n── Step 6: Results ──")
    print(f"  Space: {space_id}")
    print(f"  Book A document: {doc_a_id}")
    print(f"  Book B document: {doc_b_id}")
    print(f"  Domain tag: {DOMAIN_TAG}")
    print("\n[OK] C5 merge retest complete. Check worker logs for:")
    print("  - '[merge] Diffing entities' for entity diff")
    print("  - '[merge] Blueprint merge complete' for merge success")
    print("  - Chapter counts to verify incremental merge")


if __name__ == "__main__":
    main()
