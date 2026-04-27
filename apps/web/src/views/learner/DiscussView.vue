<template>
  <div class="page">
    <div class="page-header">
      <span class="page-title">💬 讨论</span>
      <span class="page-sub">我加入的课程的最新动态</span>
    </div>

    <!-- 课程入口 -->
    <div v-if="spaces.length" class="space-nav">
      <router-link
        v-for="sp in spaces" :key="sp.space_id"
        :to="`/spaces/${sp.space_id}/posts`"
        class="space-chip"
      >{{ sp.name }}</router-link>
    </div>

    <div v-if="loading" style="text-align:center;padding:60px">
      <el-icon class="is-loading" style="font-size:32px"><Loading /></el-icon>
    </div>

    <el-empty v-else-if="posts.length === 0"
      description="还没有讨论，去课程里发第一帖吧"
      style="padding:60px 0" />

    <div v-else class="post-list">
      <div v-for="post in posts" :key="post.post_id"
        class="post-card" @click="openPost(post)">
        <div class="post-header">
          <span :class="['type-tag', post.post_type]">{{ typeLabel(post.post_type) }}</span>
          <span v-if="post.status === 'resolved'" class="resolved-tag">✓ 已解决</span>
          <span class="space-badge">{{ post.space_name }}</span>
          <span class="post-author">{{ post.username }}</span>
          <span class="post-time">{{ formatDate(post.created_at) }}</span>
        </div>
        <div class="post-content">{{ post.content }}</div>
        <div class="post-footer">
          <span>💬 {{ post.reply_count }} 条回复</span>
          <span>👍 {{ post.likes }}</span>
          <span class="goto-link"
            @click.stop="$router.push(`/spaces/${post.space_id}/posts`)">
            前往课程讨论区 →
          </span>
        </div>
      </div>
    </div>

    <!-- 帖子详情 dialog -->
    <el-dialog v-model="showDetail"
      :title="currentPost?.content?.slice(0,30) + '...'"
      width="620px">
      <div v-if="currentPost">
        <div class="detail-post">
          <div style="display:flex;gap:6px;align-items:center;margin-bottom:8px">
            <span :class="['type-tag', currentPost.post_type]">
              {{ typeLabel(currentPost.post_type) }}
            </span>
            <span v-if="currentPost.status==='resolved'" class="resolved-tag">✓ 已解决</span>
            <span class="space-badge">{{ currentPost.space_name }}</span>
          </div>
          <p style="color:#303133;line-height:1.8;margin:0">{{ currentPost.content }}</p>
          <div style="color:#909399;font-size:12px;margin-top:8px;display:flex;gap:12px">
            <span>{{ currentPost.username }}</span>
            <span>{{ formatDate(currentPost.created_at) }}</span>

          </div>
        </div>

        <div class="reply-list">
          <div v-for="r in replies" :key="r.reply_id"
            :class="['reply-item', { 'ai-reply': r.is_ai }]">
            <div class="reply-meta">
              <span v-if="r.is_ai" class="ai-tag">🤖 AI 引导</span>
              <span v-else class="reply-author">{{ r.username }}</span>
              <span class="reply-time">{{ formatDate(r.created_at) }}</span>
            </div>
            <div class="reply-content">{{ r.content }}</div>
          </div>
          <el-empty v-if="replies.length === 0" description="还没有回复" :image-size="50" />
        </div>

        <div class="reply-input">
          <el-input v-model="replyContent" type="textarea" :rows="3"
            placeholder="写下你的回复…" />
          <el-button type="primary" size="small" :loading="replying"
            style="margin-top:8px;width:100%" @click="submitReply">
            回复
          </el-button>
        </div>
      </div>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { discussApi, spaceApi } from '@/api'

const loading = ref(false)
const posts   = ref<any[]>([])
const spaces  = ref<any[]>([])

const showDetail   = ref(false)
const currentPost  = ref<any>(null)
const replies      = ref<any[]>([])
const replyContent = ref('')
const replying     = ref(false)

const postTypes = [
  { value: 'note',       label: '📝 笔记' },
  { value: 'question',   label: '🤔 求助' },
  { value: 'discussion', label: '🎯 讨论' },
]

function typeLabel(t: string) {
  return postTypes.find(p => p.value === t)?.label || t
}

function formatDate(iso: string) {
  const d = new Date(iso)
  const now = new Date()
  const diff = (now.getTime() - d.getTime()) / 1000
  if (diff < 60) return '刚刚'
  if (diff < 3600) return `${Math.floor(diff/60)}分钟前`
  if (diff < 86400) return `${Math.floor(diff/3600)}小时前`
  return `${d.getMonth()+1}/${d.getDate()}`
}

async function load() {
  loading.value = true
  try {
    const res: any = await discussApi.feed(50)
    posts.value = res.data?.posts || []
  } catch {
    ElMessage.error('加载失败')
  } finally {
    loading.value = false
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
    await load()
    ElMessage.success('回复成功')
  } catch {
    ElMessage.error('回复失败')
  } finally {
    replying.value = false
  }
}


onMounted(async () => {
  await load()
  try {
    const res: any = await spaceApi.list()
    spaces.value = (Array.isArray(res.data) ? res.data : res.data?.spaces || []).filter((s: any) => s.my_role)
  } catch {}
})
</script>

<style scoped>
.page { padding: 8px; }
.page-header { display: flex; align-items: baseline; gap: 12px; margin-bottom: 16px; }
.page-title { font-size: 18px; font-weight: 600; color: #303133; }
.page-sub   { font-size: 13px; color: #909399; }
.post-list  { display: flex; flex-direction: column; gap: 10px; }
.post-card  {
  background: #fff; border: 1px solid #e4e7ed; border-radius: 8px;
  padding: 12px 14px; cursor: pointer; transition: box-shadow .15s;
}
.post-card:hover { box-shadow: 0 2px 8px rgba(0,0,0,.08); }
.post-header { display: flex; align-items: center; gap: 6px; margin-bottom: 8px; flex-wrap: wrap; }
.type-tag { font-size: 11px; padding: 2px 7px; border-radius: 4px; font-weight: 500; }
.type-tag.stuck   { background: #fff3e0; color: #e65100; }
.type-tag.tip     { background: #e8f5e9; color: #2e7d32; }
.type-tag.discuss { background: #e3f2fd; color: #1565c0; }
.resolved-tag { font-size: 11px; color: #67c23a; background: #f0f9eb; padding: 2px 7px; border-radius: 4px; }
.space-badge  { font-size: 11px; color: #409eff; background: #ecf5ff; padding: 2px 7px; border-radius: 4px; }
.post-author  { font-size: 12px; color: #606266; margin-left: auto; }
.post-time    { font-size: 12px; color: #c0c4cc; }
.post-content {
  font-size: 13px; color: #303133; line-height: 1.7;
  overflow: hidden; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical;
}
.post-footer { display: flex; gap: 14px; margin-top: 8px; font-size: 12px; color: #909399; }
.goto-link   { margin-left: auto; color: #409eff; cursor: pointer; }
.goto-link:hover { text-decoration: underline; }
.detail-post { background: #f7f8fa; border-radius: 8px; padding: 12px 16px; margin-bottom: 16px; }
.reply-list  { max-height: 300px; overflow-y: auto; display: flex; flex-direction: column;
  gap: 10px; margin-bottom: 16px; }
.reply-item  { padding: 10px 14px; border-radius: 8px; background: #fff; border: 1px solid #e4e7ed; }
.reply-item.ai-reply { background: #f0f7ff; border-color: #cce0ff; }
.reply-meta  { display: flex; align-items: center; gap: 8px; margin-bottom: 6px; }
.ai-tag      { font-size: 11px; color: #409eff; font-weight: 500; }
.reply-author{ font-size: 12px; color: #606266; font-weight: 500; }
.reply-time  { font-size: 12px; color: #c0c4cc; margin-left: auto; }
.reply-content { font-size: 13px; color: #303133; line-height: 1.7; }
.space-nav {
  display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 16px;
}
.space-chip {
  display: inline-flex; align-items: center;
  padding: 5px 14px; border-radius: 20px;
  background: #f0f4ff; color: #4070f4;
  font-size: 13px; font-weight: 500;
  border: 1px solid #c7d5fb;
  text-decoration: none; transition: all .15s;
}
.space-chip:hover {
  background: #4070f4; color: #fff;
  border-color: #4070f4; box-shadow: 0 2px 8px rgba(64,112,244,.3);
}
</style>
