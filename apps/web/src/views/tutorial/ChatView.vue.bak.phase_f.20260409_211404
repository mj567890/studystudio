<template>
  <div class="chat-page">
    <!-- 顶部配置栏 -->
    <div class="chat-header">
      <el-input v-model="topicKey" placeholder="学习主题" size="small" style="width:180px" />
      <el-button size="small" :loading="starting" @click="startConversation"
        :type="conversationId ? 'default' : 'primary'">
        {{ conversationId ? '新建对话' : '开始对话' }}
      </el-button>
      <el-tag v-if="conversationId" type="success">对话进行中</el-tag>
    </div>

    <!-- 消息区 -->
    <div class="messages" ref="messagesEl">
      <div v-if="!conversationId" class="empty-tip">
        <el-empty description="选择主题后点击「开始对话」">
          <el-button type="primary" @click="startConversation">开始对话</el-button>
        </el-empty>
      </div>

      <div v-for="(msg, idx) in messages" :key="idx"
        :class="['message', msg.role]">
        <div class="avatar">{{ msg.role === 'user' ? '我' : 'AI' }}</div>
        <div class="bubble">
          <div v-if="msg.role === 'assistant'" v-html="renderMd(msg.content)" />
          <div v-else>{{ msg.content }}</div>

          <!-- AI 诊断信息 -->
          <div v-if="msg.diagnosis" class="diagnosis">
            <el-divider />
            <p style="font-size:12px;color:#909399;margin-bottom:6px">📊 诊断分析</p>
            <div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:4px">
              <el-tag v-for="g in msg.diagnosis.suspected_gap_types" :key="g"
                size="small" type="warning">{{ gapLabel(g) }}</el-tag>
            </div>
            <p v-if="msg.diagnosis.error_pattern" style="font-size:12px;color:#606266">
              💡 {{ msg.diagnosis.error_pattern }}
            </p>
            <p style="font-size:12px;color:#909399">
              置信度：{{ Math.round((msg.diagnosis.confidence||0)*100) }}%
            </p>
          </div>

          <!-- 推荐下一步 -->
          <div v-if="msg.next_steps?.length" class="next-steps">
            <p style="font-size:12px;color:#909399;margin-bottom:6px">🔗 相关知识点</p>
            <el-tag v-for="s in msg.next_steps" :key="s.ref_id"
              size="small" style="margin:2px;cursor:pointer"
              @click="sendMessage(`请解释一下「${s.title}」`)">
              {{ s.title }}
            </el-tag>
          </div>
        </div>
      </div>

      <!-- AI 思考中 -->
      <div v-if="thinking" class="message assistant">
        <div class="avatar">AI</div>
        <div class="bubble thinking">
          <span class="dot" /><span class="dot" /><span class="dot" />
        </div>
      </div>
    </div>

    <!-- 输入区 -->
    <div class="input-area">
      <el-input
        v-model="inputText"
        type="textarea"
        :rows="3"
        placeholder="输入你的问题... （Ctrl+Enter 发送）"
        :disabled="!conversationId || thinking"
        @keydown.ctrl.enter="send"
        resize="none"
      />
      <el-button type="primary" :loading="thinking"
        :disabled="!conversationId || !inputText.trim()"
        style="margin-left:12px;height:80px;width:80px"
        @click="send">发送</el-button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, nextTick, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { marked } from 'marked'
import { teachingApi } from '@/api'

const route    = useRoute()
const topicKey = ref((route.query.topic as string) || 'web-security')

const conversationId = ref('')
const messages       = ref<any[]>([])
const inputText      = ref('')
const starting       = ref(false)
const thinking       = ref(false)
const messagesEl     = ref<HTMLElement>()

const GAP_LABELS: Record<string, string> = {
  definition: '定义型', mechanism: '机制型', flow: '流程型',
  distinction: '区分型', application: '应用型', causal: '因果型'
}
const gapLabel = (g: string) => GAP_LABELS[g] || g
const renderMd = (text: string) => marked(text || '')

async function startConversation() {
  starting.value = true
  try {
    const res: any = await teachingApi.createConversation(topicKey.value)
    conversationId.value = res.data.conversation_id
    messages.value = []
    // 欢迎消息
    messages.value.push({
      role:    'assistant',
      content: `你好！我是你的 AI 学习助手，我们今天学习**「${topicKey.value}」**相关内容。有什么不懂的尽管问我！`,
    })
  } finally { starting.value = false }
}

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
      context:         { topic_key: topicKey.value }
    })
    const data = res.data
    messages.value.push({
      role:       'assistant',
      content:    data.assistant_message,
      diagnosis:  data.diagnosis_update,
      next_steps: data.suggested_next_steps,
    })
  } finally {
    thinking.value = false
    await scrollBottom()
  }
}

async function sendMessage(text: string) {
  inputText.value = text
  await send()
}

async function scrollBottom() {
  await nextTick()
  if (messagesEl.value) {
    messagesEl.value.scrollTop = messagesEl.value.scrollHeight
  }
}

onMounted(() => {
  if (route.query.topic) startConversation()
})
</script>

<style scoped>
.chat-page {
  display: flex; flex-direction: column;
  height: calc(100vh - 100px); padding: 8px;
}
.chat-header {
  display: flex; align-items: center; gap: 10px;
  padding: 10px 16px; background: #fff;
  border-radius: 8px; margin-bottom: 12px;
  box-shadow: 0 1px 4px rgba(0,0,0,.08);
}
.messages {
  flex: 1; overflow-y: auto; padding: 16px;
  background: #fff; border-radius: 8px;
  box-shadow: 0 1px 4px rgba(0,0,0,.08);
}
.empty-tip { height: 100%; display: flex; align-items: center; justify-content: center; }
.message {
  display: flex; gap: 12px; margin-bottom: 20px;
}
.message.user { flex-direction: row-reverse; }
.avatar {
  width: 36px; height: 36px; border-radius: 50%;
  background: #409eff; color: #fff;
  display: flex; align-items: center; justify-content: center;
  font-size: 12px; font-weight: bold; flex-shrink: 0;
}
.message.user .avatar { background: #67c23a; }
.bubble {
  max-width: 70%; padding: 12px 16px;
  background: #f4f6f9; border-radius: 12px;
  line-height: 1.7; font-size: 14px;
}
.message.user .bubble {
  background: #409eff; color: #fff;
}
.bubble :deep(p)    { margin-bottom: 8px; }
.bubble :deep(code) { background: rgba(0,0,0,.08); padding: 2px 5px; border-radius: 3px; }
.bubble :deep(pre)  { background: #282c34; color: #abb2bf; padding: 12px;
  border-radius: 6px; overflow-x: auto; margin: 8px 0; }
.diagnosis   { margin-top: 10px; }
.next-steps  { margin-top: 10px; padding-top: 8px; border-top: 1px dashed #eee; }
.thinking    { display: flex; align-items: center; gap: 4px; padding: 16px; }
.dot {
  width: 8px; height: 8px; background: #909399;
  border-radius: 50%; animation: bounce 1.2s infinite;
}
.dot:nth-child(2) { animation-delay: .2s; }
.dot:nth-child(3) { animation-delay: .4s; }
@keyframes bounce {
  0%, 80%, 100% { transform: scale(0); }
  40%           { transform: scale(1); }
}
.input-area {
  display: flex; align-items: flex-end;
  margin-top: 12px; padding: 12px 16px;
  background: #fff; border-radius: 8px;
  box-shadow: 0 1px 4px rgba(0,0,0,.08);
}
.input-area .el-textarea { flex: 1; }
</style>
