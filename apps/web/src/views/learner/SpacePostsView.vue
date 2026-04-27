<template>
  <div class="page">
    <el-page-header @back="$router.push('/discuss')"
      :content="spaceName ? `${spaceName} · 讨论区` : '讨论区'"
      style="margin-bottom:16px" />

    <el-card>
      <template #header>
        <div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:8px">
          <div style="display:flex;gap:8px;align-items:center">
            <el-select v-model="filterType" placeholder="全部类型" clearable size="small"
              style="width:130px" @change="load">
              <el-option label="📝 笔记" value="note" />
              <el-option label="🤔 求助" value="question" />
              <el-option label="🎯 讨论" value="discussion" />
            </el-select>
            <el-select v-model="filterChapter" placeholder="全部章节" clearable size="small"
              style="width:160px" @change="load">
              <el-option v-for="ch in chapters" :key="ch.chapter_id"
                :label="ch.title" :value="ch.chapter_id" />
            </el-select>
          </div>
          <el-button type="primary" size="small" @click="showPost = true">+ 发帖</el-button>
        </div>
      </template>

      <div v-if="loading" style="text-align:center;padding:40px">
        <el-icon class="is-loading" style="font-size:32px"><Loading /></el-icon>
      </div>

      <el-empty v-else-if="posts.length === 0"
        description="还没有帖子，来发第一帖吧" style="padding:40px 0" />

      <div v-else class="post-list">
        <div v-for="post in posts" :key="post.post_id"
          class="post-card" @click="openPost(post)">
          <div class="post-header">
            <span :class="['type-tag', post.post_type]">{{ typeLabel(post.post_type) }}</span>
            <span class="chapter-hint" v-if="post.chapter_title">{{ post.chapter_title }}</span>
            <span class="post-author">{{ post.username }}</span>
            <span class="post-time">{{ formatDate(post.created_at) }}</span>
          </div>
          <div v-if="post.title" class="post-title">{{ post.title }}</div>
          <div class="post-content">{{ post.content }}</div>
          <div class="post-footer">
            <span>💬 {{ post.reply_count }} 条回复</span>
          </div>
        </div>
      </div>
    </el-card>

    <!-- 发帖 dialog -->
    <el-dialog v-model="showPost" title="发帖" width="560px" :close-on-click-modal="false">
      <div style="display:flex;flex-direction:column;gap:12px">
        <div style="display:flex;gap:8px">
          <div v-for="t in postTypes" :key="t.value"
            :class="['type-btn', { active: newPost.post_type === t.value }]"
            @click="newPost.post_type = t.value">
            {{ t.label }}
          </div>
        </div>
        <el-select v-model="newPost.chapter_id" placeholder="关联章节（可选）"
          clearable style="width:100%">
          <el-option v-for="ch in chapters" :key="ch.chapter_id"
            :label="ch.title" :value="ch.chapter_id" />
        </el-select>
        <el-input v-model="newPost.title" placeholder="标题（可选）" />
        <el-input v-model="newPost.content" type="textarea" :rows="5"
          :placeholder="postPlaceholder" />
      </div>
      <template #footer>
        <el-button @click="showPost = false">取消</el-button>
        <el-button type="primary" :loading="posting" @click="submitPost">发布</el-button>
      </template>
    </el-dialog>

    <!-- 帖子详情 dialog -->
    <el-dialog v-model="showDetail"
      :title="currentPost?.title || currentPost?.content?.slice(0,30)"
      width="620px">
      <div v-if="currentPost">
        <div class="detail-post">
          <div style="display:flex;gap:6px;align-items:center;margin-bottom:8px">
            <span :class="['type-tag', currentPost.post_type]">{{ typeLabel(currentPost.post_type) }}</span>
            <span v-if="currentPost.chapter_title" class="chapter-hint">{{ currentPost.chapter_title }}</span>
          </div>
          <p style="color:#303133;line-height:1.8;margin:0;white-space:pre-wrap">{{ currentPost.content }}</p>
          <div style="color:#909399;font-size:12px;margin-top:8px;display:flex;gap:12px">
            <span>{{ currentPost.username }}</span>
            <span>{{ formatDate(currentPost.created_at) }}</span>
            <span v-if="currentPost.user_id === currentUserId"
              style="color:#f56c6c;cursor:pointer;margin-left:auto"
              @click="deletePost(currentPost)">删除帖子</span>
          </div>
        </div>

        <div class="reply-list">
          <div v-for="r in replies" :key="r.reply_id" class="reply-item">
            <div class="reply-meta">
              <span class="reply-author">{{ r.username }}</span>
              <span class="reply-time">{{ formatDate(r.created_at) }}</span>
              <span v-if="r.user_id === currentUserId"
                style="color:#f56c6c;cursor:pointer;font-size:12px;margin-left:auto"
                @click="deleteReply(r)">删除</span>
            </div>
            <div class="reply-content">{{ r.content }}</div>
          </div>
          <el-empty v-if="replies.length === 0" description="还没有回复" :image-size="50" />
        </div>

        <div class="reply-input">
          <el-input v-model="replyContent" type="textarea" :rows="3" placeholder="写下你的回复…" />
          <el-button type="primary" size="small" :loading="replying"
            style="margin-top:8px;width:100%" @click="submitReply">回复</el-button>
        </div>
      </div>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { discussApi, spaceApi } from '@/api'

const route   = useRoute()
const router  = useRouter()
const spaceId = computed(() => route.params.space_id as string)

const loading   = ref(false)
const posts     = ref<any[]>([])
const spaceName = ref('')
const filterType    = ref('')
const filterChapter = ref('')

const showPost = ref(false)
const posting  = ref(false)
const newPost  = ref({ chapter_id: '', post_type: 'discussion', title: '', content: '' })

const showDetail   = ref(false)
const currentPost  = ref<any>(null)
const replies      = ref<any[]>([])
const replyContent = ref('')
const replying     = ref(false)

const chapters = ref<any[]>([])

// 从 token 取当前用户 id
const currentUserId = computed(() => {
  try {
    const token = localStorage.getItem('token') || ''
    const payload = JSON.parse(atob(token.split('.')[1]))
    return payload.sub || ''
  } catch { return '' }
})

const postTypes = [
  { value: 'note',       label: '📝 笔记' },
  { value: 'question',   label: '🤔 求助' },
  { value: 'discussion', label: '🎯 讨论' },
]

function typeLabel(t: string) {
  return postTypes.find(p => p.value === t)?.label || t
}

const postPlaceholder = computed(() => ({
  note:       '记录你的学习笔记或心得…',
  question:   '描述一下你卡在哪里了，越具体越好…',
  discussion: '分享你的想法或联想到的实际场景…',
}[newPost.value.post_type] || ''))

function formatDate(iso: string) {
  const d = new Date(iso)
  return `${d.getMonth()+1}/${d.getDate()} ${d.getHours()}:${String(d.getMinutes()).padStart(2,'0')}`
}

async function load() {
  loading.value = true
  try {
    const res: any = await discussApi.listPosts(spaceId.value, {
      post_type:  filterType.value || undefined,
      chapter_id: filterChapter.value || undefined,
    })
    posts.value = res.data?.posts || []
  } catch {
    ElMessage.error('加载失败')
  } finally {
    loading.value = false
  }
}

async function loadMeta() {
  try {
    const res: any = await spaceApi.get(spaceId.value)
    spaceName.value = res.data?.name || ''
  } catch {}
}

async function loadChapters() {
  try {
    const res: any = await spaceApi.getChapters(spaceId.value)
    chapters.value = res.data?.chapters || []
  } catch {}
}

async function submitPost() {
  if (!newPost.value.content.trim()) { ElMessage.warning('请填写内容'); return }
  posting.value = true
  try {
    await discussApi.createPost(spaceId.value, {
      post_type:  newPost.value.post_type,
      title:      newPost.value.title || undefined,
      content:    newPost.value.content,
      chapter_id: newPost.value.chapter_id || undefined,
    })
    ElMessage.success('发布成功')
    newPost.value = { chapter_id: '', post_type: 'discussion', title: '', content: '' }
    showPost.value = false
    await load()
  } catch {
    ElMessage.error('发布失败')
  } finally {
    posting.value = false
  }
}

async function openPost(post: any) {
  currentPost.value = post
  showDetail.value  = true
  replyContent.value = ''
  const res: any = await discussApi.listReplies(post.post_id)
  replies.value = res.data?.replies || []
}

async function submitReply() {
  if (!replyContent.value.trim()) return
  replying.value = true
  try {
    await discussApi.createReply(currentPost.value.post_id, replyContent.value)
    replyContent.value = ''
    const res: any = await discussApi.listReplies(currentPost.value.post_id)
    replies.value = res.data?.replies || []
    currentPost.value.reply_count++
    ElMessage.success('回复成功')
  } catch {
    ElMessage.error('回复失败')
  } finally {
    replying.value = false
  }
}

async function deletePost(post: any) {
  await ElMessageBox.confirm('确认删除这个帖子？', '提示', { type: 'warning' })
  await discussApi.deletePost(post.post_id)
  showDetail.value = false
  ElMessage.success('已删除')
  await load()
}

async function deleteReply(reply: any) {
  await discussApi.deleteReply(reply.reply_id)
  replies.value = replies.value.filter(r => r.reply_id !== reply.reply_id)
  currentPost.value.reply_count = Math.max(0, currentPost.value.reply_count - 1)
  ElMessage.success('已删除')
}

onMounted(async () => {
  await loadMeta()
  await load()
  await loadChapters()
})
</script>

<style scoped>
.page { padding: 8px; }
.post-list { display: flex; flex-direction: column; gap: 10px; }
.post-card {
  background: #fafafa; border: 1px solid #e4e7ed; border-radius: 8px;
  padding: 12px 14px; cursor: pointer; transition: box-shadow .15s;
}
.post-card:hover { box-shadow: 0 2px 8px rgba(0,0,0,.1); }
.post-header { display: flex; align-items: center; gap: 6px; margin-bottom: 6px; flex-wrap: wrap; }
.post-title { font-size: 14px; font-weight: 600; color: #303133; margin-bottom: 4px; }
.type-tag { font-size: 11px; padding: 2px 7px; border-radius: 4px; font-weight: 500; }
.type-tag.note       { background: #f0f9eb; color: #2e7d32; }
.type-tag.question   { background: #fff3e0; color: #e65100; }
.type-tag.discussion { background: #e3f2fd; color: #1565c0; }
.chapter-hint { font-size: 11px; color: #909399; background: #f5f7fa; padding: 2px 7px; border-radius: 4px; }
.post-author { font-size: 12px; color: #606266; margin-left: auto; }
.post-time   { font-size: 12px; color: #c0c4cc; }
.post-content {
  font-size: 13px; color: #303133; line-height: 1.7;
  overflow: hidden; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical;
}
.post-footer { display: flex; gap: 14px; margin-top: 8px; font-size: 12px; color: #909399; }
.type-btn { padding: 6px 14px; border-radius: 20px; border: 1px solid #dcdfe6;
  font-size: 13px; cursor: pointer; color: #606266; user-select: none; }
.type-btn.active { border-color: #409eff; color: #409eff; background: #ecf5ff; }
.detail-post { background: #f7f8fa; border-radius: 8px; padding: 12px 16px; margin-bottom: 16px; }
.reply-list { max-height: 300px; overflow-y: auto; display: flex; flex-direction: column;
  gap: 10px; margin-bottom: 16px; }
.reply-item { padding: 10px 14px; border-radius: 8px; background: #fff; border: 1px solid #e4e7ed; }
.reply-meta { display: flex; align-items: center; gap: 8px; margin-bottom: 6px; }
.reply-author { font-size: 12px; color: #606266; font-weight: 500; }
.reply-time   { font-size: 12px; color: #c0c4cc; }
.reply-content { font-size: 13px; color: #303133; line-height: 1.7; }
</style>
