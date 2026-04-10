#!/usr/bin/env python3
"""
阶段 F2：对话历史侧边栏补丁
用法：python3 fix_chat_history.py
"""
from pathlib import Path

BASE = Path.home() / "studystudio"


def patch(path: Path, old: str, new: str, label: str) -> None:
    txt = path.read_text(encoding="utf-8")
    assert old in txt, f"❌ 未找到目标代码块：{label}\n路径：{path}"
    count = txt.count(old)
    assert count == 1, f"⚠️ 目标代码块出现 {count} 次（期望 1）：{label}"
    path.write_text(txt.replace(old, new, 1), encoding="utf-8")
    print(f"  ✅ {label}")


# ══════════════════════════════════════════════════════════════
# 1. routers.py — 新增历史列表 & 历史消息接口
# ══════════════════════════════════════════════════════════════
print("\n📄 routers.py")
rp = BASE / "apps/api/modules/routers.py"

OLD_CREATE = (
    '@teaching_router.post("/conversations")\n'
    'async def create_conversation(\n'
    '    topic_key:    str,\n'
    '    current_user: dict = Depends(get_current_user),\n'
    '    db: AsyncSession   = Depends(get_db),\n'
    ') -> dict:\n'
    '    """创建新的对话会话。"""\n'
    '    import uuid\n'
    '    conv_id = str(uuid.uuid4())\n'
    '    await db.execute(\n'
    '        __import__("sqlalchemy").text("""\n'
    '            INSERT INTO conversations (conversation_id, user_id, topic_key)\n'
    '            VALUES (:cid, :uid, :tk)\n'
    '        """),\n'
    '        {"cid": conv_id, "uid": current_user["user_id"], "tk": topic_key}\n'
    '    )\n'
    '    await db.commit()\n'
    '    return {"code": 201, "msg": "success", "data": {"conversation_id": conv_id}}'
)

NEW_CREATE = '''\
@teaching_router.post("/conversations")
async def create_conversation(
    topic_key:    str,
    title:        str = "",
    current_user: dict = Depends(get_current_user),
    db: AsyncSession   = Depends(get_db),
) -> dict:
    """创建新的对话会话。"""
    import uuid
    from sqlalchemy import text as _text
    conv_id       = str(uuid.uuid4())
    display_title = title or topic_key or "新对话"
    await db.execute(
        _text("""
            INSERT INTO conversations (conversation_id, user_id, topic_key)
            VALUES (:cid, :uid, :tk)
        """),
        {"cid": conv_id, "uid": current_user["user_id"], "tk": display_title}
    )
    await db.commit()
    return {"code": 201, "msg": "success", "data": {
        "conversation_id": conv_id, "title": display_title
    }}


@teaching_router.get("/conversations")
async def list_conversations(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession   = Depends(get_db),
) -> dict:
    """获取当前用户的对话列表（最近 50 条）。"""
    from sqlalchemy import text as _text
    result = await db.execute(
        _text("""
            SELECT conversation_id::text, topic_key, turn_count,
                   created_at, updated_at
            FROM conversations
            WHERE user_id = CAST(:uid AS uuid)
            ORDER BY updated_at DESC
            LIMIT 50
        """),
        {"uid": current_user["user_id"]}
    )
    rows = result.fetchall()
    convs = [
        {
            "conversation_id": r.conversation_id,
            "title":      r.topic_key,
            "turn_count": r.turn_count,
            "created_at": r.created_at.isoformat() if r.created_at else "",
            "updated_at": r.updated_at.isoformat() if r.updated_at else "",
        }
        for r in rows
    ]
    return {"code": 200, "msg": "success", "data": {"conversations": convs}}


@teaching_router.get("/conversations/{conversation_id}/turns")
async def get_conversation_turns(
    conversation_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession   = Depends(get_db),
) -> dict:
    """获取指定对话的历史消息。"""
    from sqlalchemy import text as _text
    # 验证归属
    conv = await db.execute(
        _text("SELECT user_id FROM conversations WHERE conversation_id = CAST(:cid AS uuid)"),
        {"cid": conversation_id}
    )
    row = conv.fetchone()
    if not row or str(row.user_id) != current_user["user_id"]:
        return {"code": 403, "msg": "forbidden", "data": {}}
    result = await db.execute(
        _text("""
            SELECT role, content, gap_type, created_at
            FROM conversation_turns
            WHERE conversation_id = CAST(:cid AS uuid)
            ORDER BY created_at ASC
        """),
        {"cid": conversation_id}
    )
    turns = [
        {
            "role":       r.role,
            "content":    r.content,
            "gap_type":   r.gap_type,
            "created_at": r.created_at.isoformat() if r.created_at else "",
        }
        for r in result.fetchall()
    ]
    return {"code": 200, "msg": "success", "data": {"turns": turns}}'''

patch(rp, OLD_CREATE, NEW_CREATE, "create_conversation + 新增 list/turns 接口")


# ══════════════════════════════════════════════════════════════
# 2. api/index.ts — 增加 listConversations / getTurns
# ══════════════════════════════════════════════════════════════
print("\n📄 api/index.ts")
ap = BASE / "apps/web/src/api/index.ts"

OLD_TEACHING_API = (
    "export const teachingApi = {\n"
    "  createConversation: (topicKey: string) =>\n"
    "    http.post(`/teaching/conversations?topic_key=${topicKey}`),\n"
    "  chat: (data: { conversation_id: string; message: string; context: any }) =>\n"
    "    http.post('/teaching/chat', data),\n"
    "  getSpaces: () =>\n"
    "    http.get('/teaching/spaces'),\n"
    "}"
)

NEW_TEACHING_API = (
    "export const teachingApi = {\n"
    "  createConversation: (topicKey: string, title?: string) =>\n"
    "    http.post(`/teaching/conversations?topic_key=${encodeURIComponent(topicKey)}"
    "&title=${encodeURIComponent(title || topicKey)}`),\n"
    "  chat: (data: { conversation_id: string; message: string; context: any }) =>\n"
    "    http.post('/teaching/chat', data),\n"
    "  getSpaces: () =>\n"
    "    http.get('/teaching/spaces'),\n"
    "  listConversations: () =>\n"
    "    http.get('/teaching/conversations'),\n"
    "  getTurns: (conversationId: string) =>\n"
    "    http.get(`/teaching/conversations/${conversationId}/turns`),\n"
    "}"
)

patch(ap, OLD_TEACHING_API, NEW_TEACHING_API, "teachingApi 增加 listConversations/getTurns")


# ══════════════════════════════════════════════════════════════
# 3. ChatView.vue — 完整重写
# ══════════════════════════════════════════════════════════════
print("\n📄 ChatView.vue")
cp = BASE / "apps/web/src/views/tutorial/ChatView.vue"
# 备份
bak = cp.with_name("ChatView.vue.bak.phase_f2")
bak.write_text(cp.read_text(encoding="utf-8"), encoding="utf-8")
print(f"  💾 备份 → {bak.name}")

cp.write_text(
    """\
<template>
  <div class="chat-layout">

    <!-- ── 左侧历史侧边栏 ── -->
    <div class="sidebar">
      <div class="sidebar-header">
        <span class="sidebar-title">对话历史</span>
        <el-button size="small" type="primary" :loading="starting" @click="newConversation">
          + 新建
        </el-button>
      </div>

      <div class="space-selector">
        <el-select v-model="selectedSpaceId" size="small" style="width:100%"
          placeholder="选择知识领域" :loading="spacesLoading">
          <el-option v-for="s in spaces" :key="s.space_id"
            :label="s.name" :value="s.space_id">
            <span>{{ s.space_type === 'global' ? '🌐' : '👤' }} {{ s.name }}</span>
          </el-option>
        </el-select>
      </div>

      <div class="conv-list">
        <div v-if="convsLoading" class="conv-loading">
          <el-icon class="is-loading"><Loading /></el-icon>
        </div>
        <div v-else-if="conversations.length === 0" class="conv-empty">
          暂无对话记录
        </div>
        <div
          v-for="c in conversations"
          :key="c.conversation_id"
          :class="['conv-item', { active: conversationId === c.conversation_id }]"
          @click="switchConversation(c)"
        >
          <div class="conv-title">{{ c.title || '未命名对话' }}</div>
          <div class="conv-meta">{{ c.turn_count }} 条 · {{ formatTime(c.updated_at) }}</div>
        </div>
      </div>
    </div>

    <!-- ── 右侧聊天区 ── -->
    <div class="chat-main">

      <div class="messages" ref="messagesEl">
        <div v-if="!conversationId" class="empty-tip">
          <el-empty description="点击左侧「+ 新建」开始对话">
            <el-button type="primary" @click="newConversation">开始新对话</el-button>
          </el-empty>
        </div>

        <div
          v-for="(msg, idx) in messages"
          :key="idx"
          :class="['message', msg.role]"
        >
          <div class="avatar">{{ msg.role === 'user' ? '我' : 'AI' }}</div>
          <div class="bubble">
            <div v-if="msg.role === 'assistant'" v-html="renderMd(msg.content)" />
            <div v-else>{{ msg.content }}</div>

            <div v-if="msg.diagnosis" class="diagnosis">
              <el-divider />
              <p style="font-size:12px;color:#909399;margin-bottom:6px">📊 诊断分析</p>
              <div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:4px">
                <el-tag
                  v-for="g in msg.diagnosis.suspected_gap_types"
                  :key="g"
                  size="small"
                  type="warning"
                >{{ gapLabel(g) }}</el-tag>
              </div>
              <p v-if="msg.diagnosis.error_pattern" style="font-size:12px;color:#606266">
                💡 {{ msg.diagnosis.error_pattern }}
              </p>
              <p style="font-size:12px;color:#909399">
                置信度：{{ Math.round((msg.diagnosis.confidence || 0) * 100) }}%
              </p>
            </div>

            <div v-if="msg.next_steps && msg.next_steps.length" class="next-steps">
              <p style="font-size:12px;color:#909399;margin-bottom:6px">🔗 相关知识点</p>
              <el-tag
                v-for="s in msg.next_steps"
                :key="s.ref_id"
                size="small"
                style="margin:2px;cursor:pointer"
                @click="sendMessage(`请解释一下「${s.title}」`)"
              >{{ s.title }}</el-tag>
            </div>
          </div>
        </div>

        <div v-if="thinking" class="message assistant">
          <div class="avatar">AI</div>
          <div class="bubble thinking">
            <span class="dot" /><span class="dot" /><span class="dot" />
          </div>
        </div>
      </div>

      <div v-if="conversationId" class="input-area">
        <el-input
          v-model="inputText"
          type="textarea"
          :rows="3"
          placeholder="输入问题…（Ctrl+Enter 发送）"
          :disabled="thinking"
          @keydown.ctrl.enter="send"
          resize="none"
        />
        <el-button
          type="primary"
          :loading="thinking"
          :disabled="!inputText.trim()"
          style="margin-left:12px;height:80px;width:80px"
          @click="send"
        >发送</el-button>
      </div>

    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, nextTick, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { marked } from 'marked'
import { Loading } from '@element-plus/icons-vue'
import { teachingApi } from '@/api'

const route = useRoute()

// ── 当前对话 ──────────────────────────────────
const conversationId = ref('')
const messages       = ref<any[]>([])
const inputText      = ref('')
const starting       = ref(false)
const thinking       = ref(false)
const messagesEl     = ref<HTMLElement>()

// ── 话题（隐藏，从路由参数读取）────────────────
const topicKey  = ref((route.query.topic as string) || 'web-security')
const chapterId = ref((route.query.chapter_id as string) || '')

// ── 对话历史列表 ──────────────────────────────
interface ConvItem {
  conversation_id: string
  title: string
  turn_count: number
  updated_at: string
}
const conversations = ref<ConvItem[]>([])
const convsLoading  = ref(false)

// ── 知识领域 ──────────────────────────────────
interface KnowledgeSpace { space_id: string; space_type: string; name: string }
const spaces          = ref<KnowledgeSpace[]>([])
const spacesLoading   = ref(false)
const selectedSpaceId = ref('')
const selectedSpace   = computed(() =>
  spaces.value.find(s => s.space_id === selectedSpaceId.value)
)

// ── 工具函数 ──────────────────────────────────
const GAP_LABELS: Record<string, string> = {
  definition: '定义型', mechanism: '机制型', flow: '流程型',
  distinction: '区分型', application: '应用型', causal: '因果型',
}
const gapLabel = (g: string) => GAP_LABELS[g] || g
const renderMd = (text: string) => marked(text || '') as string

function formatTime(iso: string) {
  if (!iso) return ''
  const d    = new Date(iso)
  const diff = Date.now() - d.getTime()
  if (diff < 60_000)     return '刚刚'
  if (diff < 3_600_000)  return `${Math.floor(diff / 60_000)} 分钟前`
  if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)} 小时前`
  return `${d.getMonth() + 1}/${d.getDate()}`
}

async function scrollBottom() {
  await nextTick()
  if (messagesEl.value) messagesEl.value.scrollTop = messagesEl.value.scrollHeight
}

// ── 加载知识领域 ──────────────────────────────
async function loadSpaces() {
  spacesLoading.value = true
  try {
    const res: any = await teachingApi.getSpaces()
    spaces.value = res.data?.spaces || []
    const global = spaces.value.find(s => s.space_type === 'global')
    selectedSpaceId.value = global?.space_id ?? spaces.value[0]?.space_id ?? ''
  } catch {
    // 不阻断
  } finally {
    spacesLoading.value = false
  }
}

// ── 加载对话列表 ──────────────────────────────
async function loadConversations() {
  convsLoading.value = true
  try {
    const res: any = await teachingApi.listConversations()
    conversations.value = res.data?.conversations || []
  } catch {
    //
  } finally {
    convsLoading.value = false
  }
}

// ── 新建对话 ──────────────────────────────────
async function newConversation() {
  starting.value = true
  try {
    const res: any = await teachingApi.createConversation(topicKey.value, topicKey.value)
    const cid   = res.data.conversation_id
    const title = res.data.title || topicKey.value
    conversationId.value = cid
    messages.value = [{
      role:    'assistant',
      content: '你好！我是你的 AI 学习助手，有什么不懂的尽管问我！',
    }]
    // 插入列表顶部
    conversations.value = [
      { conversation_id: cid, title, turn_count: 0, updated_at: new Date().toISOString() },
      ...conversations.value.filter(c => c.conversation_id !== cid),
    ]
    await scrollBottom()
  } finally {
    starting.value = false
  }
}

// ── 切换历史对话 ──────────────────────────────
async function switchConversation(c: ConvItem) {
  if (conversationId.value === c.conversation_id) return
  conversationId.value = c.conversation_id
  messages.value = []
  thinking.value = false
  try {
    const res: any = await teachingApi.getTurns(c.conversation_id)
    const turns: any[] = res.data?.turns || []
    messages.value = turns.map(t => ({ role: t.role, content: t.content }))
    if (messages.value.length === 0) {
      messages.value = [{ role: 'assistant', content: '对话已恢复，继续提问吧！' }]
    }
  } catch {
    messages.value = [{ role: 'assistant', content: '消息加载失败，请重试。' }]
  }
  await scrollBottom()
}

// ── 发送消息 ──────────────────────────────────
async function send() {
  const text = inputText.value.trim()
  if (!text || !conversationId.value || thinking.value) return

  messages.value.push({ role: 'user', content: text })
  inputText.value = ''
  thinking.value  = true
  await scrollBottom()

  try {
    const res: any = await teachingApi.chat({
      conversation_id: conversationId.value,
      message:         text,
      context: {
        topic_key:  topicKey.value,
        space_id:   selectedSpaceId.value || undefined,
        space_type: selectedSpace.value?.space_type || undefined,
        chapter_id: chapterId.value || undefined,
      },
    })
    const data = res.data
    messages.value.push({
      role:       'assistant',
      content:    data.assistant_message,
      diagnosis:  data.diagnosis_update,
      next_steps: data.suggested_next_steps,
    })
    // 更新列表中的计数和时间，并置顶
    const conv = conversations.value.find(c => c.conversation_id === conversationId.value)
    if (conv) {
      conv.turn_count += 1
      conv.updated_at  = new Date().toISOString()
      conversations.value = [
        conv,
        ...conversations.value.filter(c => c.conversation_id !== conv.conversation_id),
      ]
    }
  } finally {
    thinking.value = false
    await scrollBottom()
  }
}

async function sendMessage(text: string) {
  inputText.value = text
  await send()
}

// ── 初始化 ────────────────────────────────────
onMounted(async () => {
  await Promise.all([loadSpaces(), loadConversations()])
  if (route.query.topic) newConversation()
})
</script>

<style scoped>
.chat-layout {
  display: flex;
  height: calc(100vh - 64px);
  overflow: hidden;
}

/* ── 左侧栏 ── */
.sidebar {
  width: 240px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  background: #f7f8fa;
  border-right: 1px solid #e4e7ed;
  overflow: hidden;
}
.sidebar-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 12px 8px;
}
.sidebar-title {
  font-weight: 600;
  font-size: 14px;
  color: #303133;
}
.space-selector {
  padding: 0 10px 10px;
}
.conv-list {
  flex: 1;
  overflow-y: auto;
}
.conv-loading {
  text-align: center;
  padding: 20px;
  color: #c0c4cc;
}
.conv-empty {
  text-align: center;
  color: #c0c4cc;
  font-size: 13px;
  padding: 20px;
}
.conv-item {
  padding: 10px 14px;
  cursor: pointer;
  border-bottom: 1px solid #ebeef5;
  transition: background 0.15s;
}
.conv-item:hover  { background: #ecf5ff; }
.conv-item.active { background: #e6f0ff; border-left: 3px solid #409eff; }
.conv-title {
  font-size: 13px;
  color: #303133;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.conv-meta {
  font-size: 11px;
  color: #909399;
  margin-top: 3px;
}

/* ── 右侧聊天 ── */
.chat-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  background: #fff;
}
.messages {
  flex: 1;
  overflow-y: auto;
  padding: 16px;
}
.empty-tip {
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
}
.message {
  display: flex;
  gap: 12px;
  margin-bottom: 20px;
}
.message.user { flex-direction: row-reverse; }
.avatar {
  width: 36px;
  height: 36px;
  border-radius: 50%;
  background: #409eff;
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  font-weight: bold;
  flex-shrink: 0;
}
.message.user .avatar { background: #67c23a; }
.bubble {
  max-width: 70%;
  padding: 12px 16px;
  background: #f4f6f9;
  border-radius: 12px;
  line-height: 1.7;
  font-size: 14px;
}
.message.user .bubble { background: #409eff; color: #fff; }
.bubble :deep(p)    { margin-bottom: 8px; }
.bubble :deep(code) { background: rgba(0,0,0,.08); padding: 2px 5px; border-radius: 3px; }
.bubble :deep(pre)  {
  background: #282c34;
  color: #abb2bf;
  padding: 12px;
  border-radius: 6px;
  overflow-x: auto;
  margin: 8px 0;
}
.diagnosis  { margin-top: 10px; }
.next-steps {
  margin-top: 10px;
  padding-top: 8px;
  border-top: 1px dashed #eee;
}
.thinking {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 14px 18px;
}
.dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #c0c4cc;
  animation: bounce 0.9s infinite;
}
.dot:nth-child(2) { animation-delay: 0.15s; }
.dot:nth-child(3) { animation-delay: 0.30s; }
@keyframes bounce {
  0%, 80%, 100% { transform: scale(1);   opacity: 0.5; }
  40%           { transform: scale(1.2); opacity: 1;   }
}
.input-area {
  display: flex;
  align-items: center;
  padding: 12px 16px;
  border-top: 1px solid #ebeef5;
  background: #fff;
}
</style>
""",
    encoding="utf-8",
)
print("  ✅ ChatView.vue 完整重写")

print("""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  F2 补丁完成 ✅
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
接下来执行：
  source ~/studystudio/dev_tools.sh
  rebuild_api
  docker-compose up -d --no-deps --build web
  wait_api
""")
