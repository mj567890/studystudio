"""
scripts/seed_knowledge.py
种子知识库导入脚本

用途：向数据库导入初始知识点和关系，让系统开箱即用。
运行：docker compose exec api python scripts/seed_knowledge.py

默认导入一批网络安全领域的核心知识点作为示例，
实际使用时可替换为你自己的领域知识。
"""
import asyncio
import sys
import os

# 确保能找到项目模块
sys.path.insert(0, "/app")

from sqlalchemy import text
from apps.api.core.db import async_session_factory, init_db


# ── 种子知识点数据 ────────────────────────────────────────────────────────
# 可根据实际需求替换为你的领域知识
SEED_ENTITIES = [
    {
        "name": "SQL注入",
        "entity_type": "concept",
        "canonical_name": "SQL注入",
        "domain_tag": "web-security",
        "short_definition": "攻击者通过在输入中插入恶意SQL代码，操纵数据库查询的攻击方式",
        "detailed_explanation": (
            "SQL注入是一种代码注入技术，攻击者将恶意SQL语句插入到应用程序的输入字段中，"
            "当应用程序将用户输入直接拼接到SQL查询中时，攻击者可以修改查询逻辑，"
            "实现未授权的数据读取、修改或删除，甚至获取系统权限。"
        ),
        "is_core": True,
    },
    {
        "name": "XSS跨站脚本攻击",
        "entity_type": "concept",
        "canonical_name": "XSS跨站脚本攻击",
        "domain_tag": "web-security",
        "short_definition": "攻击者向网页注入恶意客户端脚本，在用户浏览器中执行",
        "detailed_explanation": (
            "跨站脚本攻击（XSS）是一种注入攻击，攻击者将恶意脚本注入到受信任网站的网页中。"
            "分为反射型、存储型和DOM型三种。攻击者可利用XSS窃取Cookie、劫持会话、"
            "重定向用户或执行任意JavaScript代码。"
        ),
        "is_core": True,
    },
    {
        "name": "CSRF跨站请求伪造",
        "entity_type": "concept",
        "canonical_name": "CSRF跨站请求伪造",
        "domain_tag": "web-security",
        "short_definition": "诱使已登录用户在不知情的情况下执行非预期操作",
        "detailed_explanation": (
            "跨站请求伪造（CSRF）攻击利用网站对用户浏览器的信任，"
            "通过伪造请求让已认证用户在不知情的情况下执行恶意操作，"
            "如转账、修改密码等。防御措施包括CSRF Token、SameSite Cookie属性等。"
        ),
        "is_core": True,
    },
    {
        "name": "文件包含漏洞",
        "entity_type": "concept",
        "canonical_name": "文件包含漏洞",
        "domain_tag": "web-security",
        "short_definition": "攻击者通过控制include路径参数，包含并执行任意文件",
        "detailed_explanation": (
            "文件包含漏洞出现在PHP等动态语言中，当include/require函数的参数可被用户控制时，"
            "攻击者可以包含恶意文件执行任意代码。分为本地文件包含（LFI）和远程文件包含（RFI）。"
        ),
        "is_core": True,
    },
    {
        "name": "路径遍历攻击",
        "entity_type": "concept",
        "canonical_name": "路径遍历攻击",
        "domain_tag": "web-security",
        "short_definition": "通过../等序列访问Web根目录以外的文件",
        "detailed_explanation": (
            "路径遍历（目录遍历）攻击利用../序列突破Web应用的文件访问限制，"
            "读取服务器上的敏感文件，如/etc/passwd、配置文件等。"
            "是文件包含漏洞的基础前置知识。"
        ),
        "is_core": True,
    },
    {
        "name": "输入验证",
        "entity_type": "defense",
        "canonical_name": "输入验证",
        "domain_tag": "web-security",
        "short_definition": "对所有用户输入进行合法性校验，拒绝非预期数据",
        "detailed_explanation": (
            "输入验证是防御注入攻击的首要措施，包括白名单验证、长度限制、"
            "类型检查和格式校验。应在服务端进行验证，客户端验证仅作辅助。"
        ),
        "is_core": False,
    },
    {
        "name": "参数化查询",
        "entity_type": "defense",
        "canonical_name": "参数化查询",
        "domain_tag": "web-security",
        "short_definition": "使用预编译语句分离SQL代码与数据，从根本上防止SQL注入",
        "detailed_explanation": (
            "参数化查询（预处理语句）是防止SQL注入最有效的方法，"
            "通过将SQL结构和数据分开传递，数据库不会将用户输入解析为SQL指令，"
            "彻底消除SQL注入风险。"
        ),
        "is_core": False,
    },
    {
        "name": "输出编码",
        "entity_type": "defense",
        "canonical_name": "输出编码",
        "domain_tag": "web-security",
        "short_definition": "将特殊字符转义后再输出到HTML，防止XSS攻击",
        "detailed_explanation": (
            "输出编码将HTML特殊字符（如<、>、&、\"）转换为HTML实体，"
            "防止浏览器将用户输入解析为可执行脚本，是防御XSS攻击的核心措施。"
        ),
        "is_core": False,
    },
]

# ── 种子关系数据 ──────────────────────────────────────────────────────────
# 格式：(source_canonical_name, target_canonical_name, relation_type)
SEED_RELATIONS = [
    ("路径遍历攻击", "文件包含漏洞", "prerequisite_of"),   # 路径遍历是文件包含的前置知识
    ("输入验证", "SQL注入", "related"),                    # 输入验证可防御SQL注入
    ("参数化查询", "SQL注入", "related"),                  # 参数化查询防御SQL注入
    ("输出编码", "XSS跨站脚本攻击", "related"),             # 输出编码防御XSS
    ("SQL注入", "XSS跨站脚本攻击", "related"),             # 同属注入类攻击
]


async def seed():
    print("🌱 开始导入种子知识库...")

    await init_db()

    async with async_session_factory() as session:
        # ── 导入知识点 ────────────────────────────────────────────────────
        import uuid
        entity_id_map = {}  # canonical_name -> entity_id

        for entity in SEED_ENTITIES:
            # 检查是否已存在（幂等）
            result = await session.execute(
                text("SELECT entity_id FROM knowledge_entities WHERE canonical_name = :name"),
                {"name": entity["canonical_name"]}
            )
            existing = result.fetchone()

            if existing:
                entity_id_map[entity["canonical_name"]] = str(existing.entity_id)
                print(f"  ⏭  已存在，跳过：{entity['canonical_name']}")
                continue

            entity_id = str(uuid.uuid4())
            entity_id_map[entity["canonical_name"]] = entity_id

            await session.execute(
                text("""
                    INSERT INTO knowledge_entities
                      (entity_id, name, entity_type, canonical_name, domain_tag,
                       space_type, visibility, short_definition, detailed_explanation,
                       review_status, is_core)
                    VALUES
                      (:entity_id, :name, :entity_type, :canonical_name, :domain_tag,
                       'global', 'public', :short_definition, :detailed_explanation,
                       'approved', :is_core)
                """),
                {
                    "entity_id":           entity_id,
                    "name":                entity["name"],
                    "entity_type":         entity["entity_type"],
                    "canonical_name":      entity["canonical_name"],
                    "domain_tag":          entity["domain_tag"],
                    "short_definition":    entity["short_definition"],
                    "detailed_explanation": entity["detailed_explanation"],
                    "is_core":             entity["is_core"],
                }
            )
            print(f"  ✅ 导入知识点：{entity['canonical_name']}")

        await session.commit()

        # ── 导入关系 ──────────────────────────────────────────────────────
        for source_name, target_name, relation_type in SEED_RELATIONS:
            source_id = entity_id_map.get(source_name)
            target_id = entity_id_map.get(target_name)

            if not source_id or not target_id:
                print(f"  ⚠️  关系跳过（找不到实体）：{source_name} -> {target_name}")
                continue

            # 检查是否已存在
            result = await session.execute(
                text("""
                    SELECT 1 FROM knowledge_relations
                    WHERE source_entity_id = :src AND target_entity_id = :tgt
                      AND relation_type = :rtype
                """),
                {"src": source_id, "tgt": target_id, "rtype": relation_type}
            )
            if result.fetchone():
                print(f"  ⏭  关系已存在，跳过：{source_name} -{relation_type}-> {target_name}")
                continue

            await session.execute(
                text("""
                    INSERT INTO knowledge_relations
                      (relation_id, source_entity_id, target_entity_id, relation_type, review_status)
                    VALUES
                      (:rid, :src, :tgt, :rtype, 'approved')
                """),
                {
                    "rid":   str(uuid.uuid4()),
                    "src":   source_id,
                    "tgt":   target_id,
                    "rtype": relation_type,
                }
            )
            print(f"  ✅ 导入关系：{source_name} -{relation_type}-> {target_name}")

        await session.commit()

    print("\n🎉 种子知识库导入完成！")
    print(f"   知识点：{len(SEED_ENTITIES)} 个")
    print(f"   关系：{len(SEED_RELATIONS)} 条")
    print("\n提示：可编辑 scripts/seed_knowledge.py 中的 SEED_ENTITIES 替换为你自己的领域知识。")


if __name__ == "__main__":
    asyncio.run(seed())
