#!/usr/bin/env python3
"""
阶段 F 补丁脚本：AI 对话作用域收口
执行方式：python3 apply_phase_f.py
"""
from __future__ import annotations
import re
import sys
from datetime import datetime
from pathlib import Path

BASE = Path.home() / "studystudio"

# ──────────────────────────────────────────────────────────────────────────────
# 工具函数
# ──────────────────────────────────────────────────────────────────────────────

def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")

def write(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")

def backup(path: Path) -> None:
    ts  = datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = path.with_name(path.name + f".bak.phase_f.{ts}")
    bak.write_text(read(path), encoding="utf-8")
    print(f"  💾 备份 → {bak.name}")

def replace_once(content: str, old: str, new: str, label: str) -> str:
    if old not in content:
        print(f"  ❌ 未找到目标代码块：{label}")
        sys.exit(1)
    count = content.count(old)
    if count > 1:
        print(f"  ⚠️  目标代码块出现 {count} 次（期望 1 次）：{label}")
        sys.exit(1)
    print(f"  ✅ 替换成功：{label}")
    return content.replace(old, new, 1)

def patch(rel_path: str, replacements: list[tuple[str, str, str]]) -> None:
    path = BASE / rel_path
    print(f"\n📄 处理 {rel_path}")
    backup(path)
    content = read(path)
    for old, new, label in replacements:
        content = replace_once(content, old, new, label)
    write(path, content)
    print(f"  ✔  写入完成")


# ══════════════════════════════════════════════════════════════════════════════
# 补丁 1 / 4  —  teaching_service.py
# ══════════════════════════════════════════════════════════════════════════════
TEACHING_PATH = "apps/api/modules/teaching/teaching_service.py"

# 1-A: retrieve() 签名 + 调用下游时透传参数
OLD_RETRIEVE_SIG = '''\
    async def retrieve(
        self, query: str, user_id: str, topic_key: str
    ) -> list[RankedKnowledgeItem]:
        """
        两路召回 + RRF 融合。
        返回最相关的 TOP_K 个知识点。
        """
        # 并行执行两路召回
        bm25_results   = await self._bm25_search(query)
        vector_results = await self._vector_search(query)'''

NEW_RETRIEVE_SIG = '''\
    async def retrieve(
        self, query: str, user_id: str, topic_key: str,
        space_id:   str | None = None,
        domain_tag: str | None = None,
        chapter_id: str | None = None,
    ) -> list[RankedKnowledgeItem]:
        """
        两路召回 + RRF 融合。
        返回最相关的 TOP_K 个知识点。
        space_id / domain_tag / chapter_id 不为 None 时进行作用域过滤。
        """
        # 并行执行两路召回
        bm25_results   = await self._bm25_search(query, space_id, domain_tag, chapter_id)
        vector_results = await self._vector_search(query, space_id, domain_tag, chapter_id)'''

# 1-B: _bm25_search() 加作用域过滤
OLD_BM25 = '''\
    async def _bm25_search(self, query: str) -> list[dict]:
        result = await self.db.execute(
            text("""
                SELECT entity_id::text, canonical_name, short_definition,
                       ts_rank(
                         to_tsvector('simple', COALESCE(canonical_name,'') || ' ' || COALESCE(short_definition,'')),
                         plainto_tsquery('simple', :query)
                       ) AS score
                FROM knowledge_entities
                WHERE review_status = 'approved'
                  AND to_tsvector('simple', COALESCE(canonical_name,'') || ' ' || COALESCE(short_definition,''))
                      @@ plainto_tsquery('simple', :query)
                ORDER BY score DESC
                LIMIT 30
            """),
            {"query": query}
        )
        return [dict(r._mapping) for r in result.fetchall()]'''

NEW_BM25 = '''\
    async def _bm25_search(
        self, query: str,
        space_id:   str | None = None,
        domain_tag: str | None = None,
        chapter_id: str | None = None,
    ) -> list[dict]:
        chapter_join = (
            "JOIN chapter_entity_links cel "
            "ON cel.entity_id = ke.entity_id "
            "AND cel.chapter_id = CAST(:chapter_id AS uuid)"
            if chapter_id else ""
        )
        sql = f"""
            SELECT ke.entity_id::text, ke.canonical_name, ke.short_definition,
                   ts_rank(
                     to_tsvector('simple', COALESCE(ke.canonical_name,'') || ' ' || COALESCE(ke.short_definition,'')),
                     plainto_tsquery('simple', :query)
                   ) AS score
            FROM knowledge_entities ke
            {chapter_join}
            WHERE ke.review_status = 'approved'
              AND (:space_id IS NULL OR ke.space_id = CAST(:space_id AS uuid) OR ke.space_type = 'global')
              AND (:domain_tag IS NULL OR ke.domain_tag = :domain_tag)
              AND to_tsvector('simple', COALESCE(ke.canonical_name,'') || ' ' || COALESCE(ke.short_definition,''))
                  @@ plainto_tsquery('simple', :query)
            ORDER BY score DESC
            LIMIT 30
        """
        result = await self.db.execute(
            text(sql),
            {"query": query, "space_id": space_id,
             "domain_tag": domain_tag, "chapter_id": chapter_id}
        )
        return [dict(r._mapping) for r in result.fetchall()]'''

# 1-C: _vector_search() 加作用域过滤
OLD_VECTOR = '''\
    async def _vector_search(self, query: str) -> list[dict]:
        query_emb = await self.llm.embed_single(query)
        result = await self.db.execute(
            text("""
                SELECT entity_id::text, canonical_name, short_definition,
                       1 - (embedding <=> CAST(:emb AS vector)) AS similarity
                FROM knowledge_entities
                WHERE review_status = 'approved'
                  AND embedding IS NOT NULL
                ORDER BY embedding <=> CAST(:emb AS vector)
                LIMIT 30
            """),
            {"emb": str(query_emb)}
        )
        return [dict(r._mapping) for r in result.fetchall()]'''

NEW_VECTOR = '''\
    async def _vector_search(
        self, query: str,
        space_id:   str | None = None,
        domain_tag: str | None = None,
        chapter_id: str | None = None,
    ) -> list[dict]:
        query_emb = await self.llm.embed_single(query)
        chapter_join = (
            "JOIN chapter_entity_links cel "
            "ON cel.entity_id = ke.entity_id "
            "AND cel.chapter_id = CAST(:chapter_id AS uuid)"
            if chapter_id else ""
        )
        sql = f"""
            SELECT ke.entity_id::text, ke.canonical_name, ke.short_definition,
                   1 - (ke.embedding <=> CAST(:emb AS vector)) AS similarity
            FROM knowledge_entities ke
            {chapter_join}
            WHERE ke.review_status = 'approved'
              AND ke.embedding IS NOT NULL
              AND (:space_id IS NULL OR ke.space_id = CAST(:space_id AS uuid) OR ke.space_type = 'global')
              AND (:domain_tag IS NULL OR ke.domain_tag = :domain_tag)
            ORDER BY ke.embedding <=> CAST(:emb AS vector)
            LIMIT 30
        """
        result = await self.db.execute(
            text(sql),
            {"emb": str(query_emb), "space_id": space_id,
             "domain_tag": domain_tag, "chapter_id": chapter_id}
        )
        return [dict(r._mapping) for r in result.fetchall()]'''

# 1-D: chat_and_prepare() 签名 + 透传给 retrieve
OLD_CHAT_PREPARE_SIG = '''\
    async def chat_and_prepare(
        self,
        conversation_id: str,
        user_message:    str,
        topic_key:       str,
        user_id:         str,
    ) -> tuple[dict, DiagnosisUpdate, int]:'''

NEW_CHAT_PREPARE_SIG = '''\
    async def chat_and_prepare(
        self,
        conversation_id: str,
        user_message:    str,
        topic_key:       str,
        user_id:         str,
        space_id:        str | None = None,
        domain_tag:      str | None = None,
        chapter_id:      str | None = None,
    ) -> tuple[dict, DiagnosisUpdate, int]:'''

OLD_RETRIEVE_CALL = '''\
        retrieval_svc = RetrievalFusionService(self.db)
        retrieved = await retrieval_svc.retrieve(user_message, user_id, topic_key)'''

NEW_RETRIEVE_CALL = '''\
        retrieval_svc = RetrievalFusionService(self.db)
        retrieved = await retrieval_svc.retrieve(
            user_message, user_id, topic_key,
            space_id=space_id, domain_tag=domain_tag, chapter_id=chapter_id,
        )'''

patch(TEACHING_PATH, [
    (OLD_RETRIEVE_SIG,      NEW_RETRIEVE_SIG,      "retrieve() 签名"),
    (OLD_BM25,              NEW_BM25,              "_bm25_search() 作用域过滤"),
    (OLD_VECTOR,            NEW_VECTOR,            "_vector_search() 作用域过滤"),
    (OLD_CHAT_PREPARE_SIG,  NEW_CHAT_PREPARE_SIG,  "chat_and_prepare() 签名"),
    (OLD_RETRIEVE_CALL,     NEW_RETRIEVE_CALL,     "retrieve() 调用透传参数"),
])


# ══════════════════════════════════════════════════════════════════════════════
# 补丁 2 / 4  —  routers.py
# ══════════════════════════════════════════════════════════════════════════════
ROUTERS_PATH = "apps/api/modules/routers.py"

# 2-A: chat() 处理器 —— 从 context 提取 space_id / domain_tag / chapter_id
OLD_CHAT_HANDLER = '''\
    svc = TeachingChatService(db)
    topic_key = req.context.get("topic_key", "")

    response, diagnosis, profile_version = await svc.chat_and_prepare(
        conversation_id = req.conversation_id,
        user_message    = req.message,
        topic_key       = topic_key,
        user_id         = current_user["user_id"],
    )'''

NEW_CHAT_HANDLER = '''\
    svc        = TeachingChatService(db)
    topic_key  = req.context.get("topic_key", "")
    space_id   = req.context.get("space_id") or None
    domain_tag = req.context.get("domain_tag") or None
    chapter_id = req.context.get("chapter_id") or None

    response, diagnosis, profile_version = await svc.chat_and_prepare(
        conversation_id = req.conversation_id,
        user_message    = req.message,
        topic_key       = topic_key,
        user_id         = current_user["user_id"],
        space_id        = space_id,
        domain_tag      = domain_tag,
        chapter_id      = chapter_id,
    )'''

# 2-B: 新增 GET /api/teaching/spaces 端点（追加在 create_conversation 之后）
OLD_CONV_ENDPOINT_END = '''\
    return {"code": 201, "msg": "success", "data": {"conversation_id": conv_id}}'''

NEW_CONV_ENDPOINT_END = '''\
    return {"code": 201, "msg": "success", "data": {"conversation_id": conv_id}}


@teaching_router.get("/spaces")
async def list_teaching_spaces(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession   = Depends(get_db),
) -> dict:
    """返回当前用户可用的知识空间（全局 + 本人个人空间）。"""
    from sqlalchemy import text as _text
    result = await db.execute(
        _text("""
            SELECT space_id::text, space_type,
                   COALESCE(name,
                     CASE space_type WHEN \'global\' THEN \'公共知识库\' ELSE \'我的知识库\' END
                   ) AS name
            FROM knowledge_spaces
            WHERE space_type = \'global\'
               OR (space_type = \'personal\' AND owner_id = CAST(:uid AS uuid))
            ORDER BY space_type DESC, name
        """),
        {"uid": current_user["user_id"]}
    )
    spaces = [
        {"space_id": r.space_id, "space_type": r.space_type, "name": r.name}
        for r in result.fetchall()
    ]
    return {"code": 200, "msg": "success", "data": {"spaces": spaces}}'''

patch(ROUTERS_PATH, [
    (OLD_CHAT_HANDLER,        NEW_CHAT_HANDLER,        "chat() 提取 space/domain/chapter"),
    (OLD_CONV_ENDPOINT_END,   NEW_CONV_ENDPOINT_END,   "新增 GET /teaching/spaces 端点"),
])


# ══════════════════════════════════════════════════════════════════════════════
# 补丁 3 / 4  —  api/index.ts
# ══════════════════════════════════════════════════════════════════════════════
API_INDEX_PATH = "apps/web/src/api/index.ts"

OLD_TEACHING_API = '''\
export const teachingApi = {
  createConversation: (topicKey: string) =>
    http.post(`/teaching/conversations?topic_key=${topicKey}`),
  chat: (data: { conversation_id: string; message: string; context: any }) =>
    http.post('/teaching/chat', data),
}'''

NEW_TEACHING_API = '''\
export const teachingApi = {
  createConversation: (topicKey: string) =>
    http.post(`/teaching/conversations?topic_key=${topicKey}`),
  chat: (data: { conversation_id: string; message: string; context: any }) =>
    http.post('/teaching/chat', data),
  getSpaces: () =>
    http.get('/teaching/spaces'),
}'''

patch(API_INDEX_PATH, [
    (OLD_TEACHING_API, NEW_TEACHING_API, "teachingApi 增加 getSpaces"),
])


# ══════════════════════════════════════════════════════════════════════════════
# 补丁 4 / 4  —  ChatView.vue
# ══════════════════════════════════════════════════════════════════════════════
CHAT_VIEW_PATH = "apps/web/src/views/tutorial/ChatView.vue"

# 4-A: 顶部配置栏模板 —— 加领域选择器
OLD_HEADER_TPL = '''\
    <!-- 顶部配置栏 -->
    <div class="chat-header">
      <el-input v-model="topicKey" placeholder="学习主题" size="small" style="width:180px" />
      <el-button size="small" :loading="starting" @click="startConversation"
        :type="conversationId ? \'default\' : \'primary\'">
        {{ conversationId ? \'新建对话\' : \'开始对话\' }}
      </el-button>
      <el-tag v-if="conversationId" type="success">对话进行中</el-tag>
    </div>'''

NEW_HEADER_TPL = '''\
    <!-- 顶部配置栏 -->
    <div class="chat-header">
      <el-input v-model="topicKey" placeholder="学习主题" size="small" style="width:160px" />
      <el-select
        v-model="selectedSpaceId"
        size="small"
        style="width:160px"
        placeholder="选择知识领域"
        :loading="spacesLoading"
      >
        <el-option
          v-for="s in spaces"
          :key="s.space_id"
          :label="s.name"
          :value="s.space_id"
        >
          <span>{{ s.space_type === \'global\' ? \'🌐\' : \'👤\' }} {{ s.name }}</span>
        </el-option>
      </el-select>
      <el-button size="small" :loading="starting" @click="startConversation"
        :type="conversationId ? \'default\' : \'primary\'">
        {{ conversationId ? \'新建对话\' : \'开始对话\' }}
      </el-button>
      <el-tag v-if="conversationId" type="success">对话进行中</el-tag>
      <el-tag v-if="chapterId" type="info" size="small">📖 章节精准模式</el-tag>
    </div>'''

# 4-B: script setup —— 增加空间相关 ref + 计算属性
OLD_SCRIPT_SETUP = '''\
import { ref, nextTick, onMounted } from \'vue\'
import { useRoute } from \'vue-router\'
import { marked } from \'marked\'
import { teachingApi } from \'@/api\'

const route    = useRoute()
const topicKey = ref((route.query.topic as string) || \'web-security\')

const conversationId = ref(\'\')
const messages       = ref<any[]>([])
const inputText      = ref(\'\')
const starting       = ref(false)
const thinking       = ref(false)
const messagesEl     = ref<HTMLElement>()'''

NEW_SCRIPT_SETUP = '''\
import { ref, computed, nextTick, onMounted } from \'vue\'
import { useRoute } from \'vue-router\'
import { marked } from \'marked\'
import { teachingApi } from \'@/api\'

const route     = useRoute()
const topicKey  = ref((route.query.topic as string) || \'web-security\')
const chapterId = ref((route.query.chapter_id as string) || \'\')

const conversationId = ref(\'\')
const messages       = ref<any[]>([])
const inputText      = ref(\'\')
const starting       = ref(false)
const thinking       = ref(false)
const messagesEl     = ref<HTMLElement>()

// ── 知识领域选择 ──────────────────────────────────────────────
interface KnowledgeSpace { space_id: string; space_type: string; name: string }
const spaces          = ref<KnowledgeSpace[]>([])
const spacesLoading   = ref(false)
const selectedSpaceId = ref(\'\')
const selectedSpace   = computed<KnowledgeSpace | undefined>(() =>
  spaces.value.find(s => s.space_id === selectedSpaceId.value)
)'''

# 4-C: chat() 调用 —— context 增加 space_id / space_type / chapter_id
OLD_CHAT_CONTEXT = '''\
    const res: any = await teachingApi.chat({
      conversation_id: conversationId.value,
      message:         text,
      context:         { topic_key: topicKey.value }
    })'''

NEW_CHAT_CONTEXT = '''\
    const res: any = await teachingApi.chat({
      conversation_id: conversationId.value,
      message:         text,
      context:         {
        topic_key:  topicKey.value,
        space_id:   selectedSpaceId.value || undefined,
        space_type: selectedSpace.value?.space_type || undefined,
        chapter_id: chapterId.value || undefined,
      }
    })'''

# 4-D: onMounted —— 先加载空间列表再启动对话
OLD_ON_MOUNTED = '''\
onMounted(() => {
  if (route.query.topic) startConversation()
})'''

NEW_ON_MOUNTED = '''\
async function loadSpaces() {
  spacesLoading.value = true
  try {
    const res: any = await teachingApi.getSpaces()
    spaces.value = res.data?.spaces || []
    if (spaces.value.length > 0) {
      // 默认选全局空间，无全局则取第一个
      const global = spaces.value.find(s => s.space_type === \'global\')
      selectedSpaceId.value = global?.space_id ?? spaces.value[0].space_id
    }
  } catch {
    // 加载失败不阻断对话，selectedSpaceId 保持空（后端不过滤）
  } finally {
    spacesLoading.value = false
  }
}

onMounted(async () => {
  await loadSpaces()
  if (route.query.topic) startConversation()
})'''

patch(CHAT_VIEW_PATH, [
    (OLD_HEADER_TPL,    NEW_HEADER_TPL,    "header 加领域选择器"),
    (OLD_SCRIPT_SETUP,  NEW_SCRIPT_SETUP,  "script 增加空间相关 ref"),
    (OLD_CHAT_CONTEXT,  NEW_CHAT_CONTEXT,  "chat() context 透传 space/chapter"),
    (OLD_ON_MOUNTED,    NEW_ON_MOUNTED,    "onMounted 先加载空间"),
])


# ══════════════════════════════════════════════════════════════════════════════
# 完成
# ══════════════════════════════════════════════════════════════════════════════
print("""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  阶段 F 补丁全部应用完毕 ✅
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
后续步骤：
  1. 重建 API：
       source ~/studystudio/dev_tools.sh && rebuild_api

  2. 重建前端：
       docker-compose up -d --no-deps --build web

  3. 等待就绪：
       wait_api

  4. 验证接口：
       TOKEN=$(get_token)
       api_get /api/teaching/spaces
""")
