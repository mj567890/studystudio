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
          <div class="conv-item-footer">
          <span class="conv-meta">{{ c.turn_count }} 条 · {{ formatTime(c.updated_at) }}</span>
          <el-button link type="danger" size="small"
            @click.stop="deleteConversation(c.conversation_id)"
            style="padding:0;height:16px;font-size:11px">删除</el-button>
        </div>
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

            <div style="margin-top:6px;text-align:right">
              <el-button link size="small" style="color:#909399;font-size:12px"
                @click="saveAsNote(msg)">📌 存为笔记</el-button>
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
            <!-- H-7 苏格拉底式追问 -->
            <div v-if="msg.proactive_question" class="proactive-q">
              <span class="pq-icon">🤔</span>
              <span class="pq-text">{{ msg.proactive_question }}</span>
              <el-button
                size="small" type="primary" plain
                style="margin-left:8px;flex-shrink:0"
                @click="sendMessage(msg.proactive_question)"
              >回答这个问题</el-button>
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
          placeholder="输入问题…（Enter 发送，Shift+Enter 换行）"
          :disabled="thinking"
          @keydown.enter.exact.prevent="send" @keydown.shift.enter.exact="newline"
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
import { learnerApi, knowledgeApi, tutorialApi, teachingApi, notesApi, convRenameApi } from '@/api'
import { ElMessage, ElMessageBox } from 'element-plus'

const route = useRoute()

// ── 当前对话 ──────────────────────────────────
const conversationId = ref('')
const messages       = ref<any[]>([])
const inputText      = ref('')
const starting       = ref(false)
const thinking       = ref(false)
const messagesEl     = ref<HTMLElement>()

// ── 话题（隐藏，从路由参数读取）────────────────
const topicKey    = ref((route.query.topic as string) || 'web-security')
const chapterId   = ref((route.query.chapter_id as string) || '')
const chapterTitle = ref((route.query.chapter as string) || '')

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
      content:            data.assistant_message,
      diagnosis:          data.diagnosis_update,
      next_steps:         data.suggested_next_steps,
      proactive_question: data.proactive_question || null,
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

function newline(e: KeyboardEvent) {
  const el = (e.target as HTMLTextAreaElement)
  const pos = el.selectionStart ?? inputText.value.length
  inputText.value = inputText.value.slice(0, pos) + "\n" + inputText.value.slice(pos)
  nextTick(() => { el.selectionStart = el.selectionEnd = pos + 1 })
}

async function deleteConversation(cid: string) {
  try {
    await teachingApi.deleteConversation(cid)
    conversations.value = conversations.value.filter(c => c.conversation_id !== cid)
    if (conversationId.value === cid) {
      conversationId.value = ""
      messages.value = []
    }
  } catch {
    //
  }
}

async function saveAsNote(msg: any) {
  if (!msg.content) return
  try {
    const res: any = await notesApi.create({
      content:         msg.content,
      source_type:     'ai_chat',
      topic_key:       topicKey.value,
      chapter_id:      chapterId.value || '',
      chapter_title:   chapterTitle.value || '',
      conversation_id: conversationId.value,
    })
    ElMessage.success(`已存为笔记：${res.data?.title || ''}`)
  } catch {
    ElMessage.error('存为笔记失败')
  }
}

async function startRename(conv: any) {
  try {
    const { value } = await (ElMessageBox as any).prompt('输入新名称', '重命名对话', {
      confirmButtonText: '确认',
      cancelButtonText:  '取消',
      inputValue:        conv.title || '',
      inputValidator:    (v: string) => v.trim() ? true : '名称不能为空',
    })
    await convRenameApi.rename(conv.conversation_id, value.trim())
    conv.title = value.trim()
    ElMessage.success('已重命名')
  } catch { /* 取消 */ }
}

async function sendMessage(text: string) {
  inputText.value = text
  await send()
}

// ── 初始化 ────────────────────────────────────
onMounted(async () => {
  await Promise.all([loadSpaces(), loadConversations()])
  if (route.query.topic) {
    await newConversation()
    // 如果从教程页跳转且带有章节信息，自动发送章节提示
    if (chapterTitle.value && conversationId.value) {
      inputText.value = `我刚刚学习了「${chapterTitle.value}」这一章节，请针对这个章节的内容帮我解答问题。`
    }
  }
})
</script>

<style scoped>
.proactive-q {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  margin-top: 10px;
  padding: 8px 12px;
  background: #f0f7ff;
  border: 1px solid #cce0ff;
  border-radius: 8px;
  font-size: 13px;
  color: #1a6db5;
  flex-wrap: wrap;
}
.pq-icon { font-size: 14px; flex-shrink: 0; margin-top: 1px; }
.pq-text { flex: 1; line-height: 1.5; min-width: 0; }

.proactive-q {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  margin-top: 10px;
  padding: 8px 12px;
  background: #f0f7ff;
  border: 1px solid #cce0ff;
  border-radius: 8px;
  font-size: 13px;
  color: #1a6db5;
  flex-wrap: wrap;
}
.pq-icon { font-size: 14px; flex-shrink: 0; margin-top: 1px; }
.pq-text { flex: 1; line-height: 1.5; min-width: 0; }

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
.conv-item-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 3px;
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
