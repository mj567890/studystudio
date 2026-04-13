<template>
  <div class="wall-section">
    <div class="wall-header">
      <span class="wall-title">🗣️ 学习墙</span>
      <el-button size="small" type="primary" @click="showPost = true">发帖</el-button>
    </div>

    <!-- 帖子列表 -->
    <div v-if="loading" style="text-align:center;padding:20px">
      <el-icon class="is-loading"><Loading /></el-icon>
    </div>
    <el-empty v-else-if="posts.length === 0" description="还没有帖子，来发第一帖吧" :image-size="60" />
    <div v-else class="post-list">
      <div v-for="post in posts" :key="post.post_id" class="post-card">
        <div class="post-header">
          <span :class="['post-type-tag', post.post_type]">
            {{ postTypeLabel(post.post_type) }}
          </span>
          <span v-if="post.status === 'resolved'" class="resolved-tag">✓ 已解决</span>
          <span v-if="post.is_featured" class="featured-tag">⭐ 精华</span>
          <span class="post-author">{{ post.nickname }}</span>
          <span class="post-time">{{ formatDate(post.created_at) }}</span>
        </div>
        <div class="post-content" @click="openPost(post)">{{ post.content }}</div>
        <div v-if="post.ai_reply" class="ai-reply-preview">
          <span class="ai-tag">🤖 AI 引导</span>
          <span class="ai-reply-text">{{ post.ai_reply }}</span>
        </div>
        <div class="post-footer">
          <span class="post-stat" @click="openPost(post)">💬 {{ post.reply_count }} 条回复</span>
          <span class="post-stat" @click="likePost(post)">👍 {{ post.likes }}</span>
          <span v-if="post.is_mine && post.status !== 'resolved'"
            class="post-stat resolve-btn"
            @click="resolvePost(post)">标记已解决</span>
        </div>
      </div>
    </div>

    <!-- 发帖弹窗 -->
    <el-dialog v-model="showPost" title="发帖" width="560px" :close-on-click-modal="false">
      <div style="display:flex;flex-direction:column;gap:12px">
        <div class="type-selector">
          <div
            v-for="t in postTypes" :key="t.value"
            :class="['type-btn', { active: newPost.post_type === t.value }]"
            @click="newPost.post_type = t.value"
          >{{ t.label }}</div>
        </div>
        <el-input
          v-model="newPost.content"
          type="textarea" :rows="5"
          :placeholder="postPlaceholder"
        />
      </div>
      <template #footer>
        <el-button @click="showPost = false">取消</el-button>
        <el-button type="primary" :loading="posting" @click="submitPost">发布</el-button>
      </template>
    </el-dialog>

    <!-- 帖子详情弹窗 -->
    <el-dialog v-model="showDetail" :title="currentPost?.content?.slice(0,20) + '...'" width="620px">
      <div v-if="currentPost" class="detail-content">
        <div class="detail-post">
          <span :class="['post-type-tag', currentPost.post_type]">
            {{ postTypeLabel(currentPost.post_type) }}
          </span>
          <p style="margin-top:8px;color:#303133;line-height:1.8">{{ currentPost.content }}</p>
          <div style="color:#909399;font-size:12px;margin-top:8px">
            {{ currentPost.nickname }} · {{ formatDate(currentPost.created_at) }}
          </div>
        </div>
        <div class="reply-list">
          <div v-for="r in replies" :key="r.reply_id" :class="['reply-item', { 'ai-reply': r.is_ai }]">
            <div class="reply-meta">
              <span v-if="r.is_ai" class="ai-tag">🤖 AI 引导</span>
              <span v-else class="reply-author">{{ r.nickname }}</span>
              <span class="reply-time">{{ formatDate(r.created_at) }}</span>
            </div>
            <div class="reply-content">{{ r.content }}</div>
          </div>
        </div>
        <div class="reply-input">
          <el-input v-model="replyContent" placeholder="写下你的回复…" type="textarea" :rows="3" />
          <el-button type="primary" size="small" :loading="replying"
            style="margin-top:8px;width:100%" @click="submitReply">回复</el-button>
        </div>
      </div>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { Loading } from '@element-plus/icons-vue'
import { wallApi } from '@/api'

const props = defineProps<{ chapterId: string; topicKey: string }>()

const posts   = ref<any[]>([])
const loading = ref(false)
const showPost = ref(false)
const posting  = ref(false)
const newPost  = ref({ post_type: 'stuck', content: '' })

const showDetail   = ref(false)
const currentPost  = ref<any>(null)
const replies      = ref<any[]>([])
const replyContent = ref('')
const replying     = ref(false)

const postTypes = [
  { value: 'stuck',   label: '🤔 我卡在这里了' },
  { value: 'tip',     label: '💡 我发现了个坑' },
  { value: 'discuss', label: '🎯 我有个想法' },
]

const postPlaceholder = computed(() => {
  const map: Record<string, string> = {
    stuck:   '描述一下你卡在哪里了，越具体越好…',
    tip:     '分享一个踩坑经验或注意事项…',
    discuss: '分享你的想法或联想到的实际场景…',
  }
  return map[newPost.value.post_type] || ''
})

function postTypeLabel(type: string) {
  return postTypes.find(t => t.value === type)?.label || type
}

function formatDate(iso: string) {
  const d = new Date(iso)
  return `${d.getMonth()+1}/${d.getDate()} ${d.getHours()}:${String(d.getMinutes()).padStart(2,'0')}`
}

async function loadPosts() {
  if (!props.chapterId) return
  loading.value = true
  try {
    const res: any = await wallApi.list({ chapter_id: props.chapterId })
    posts.value = res.data?.posts || []
  } catch { /* 静默 */ }
  finally { loading.value = false }
}

async function submitPost() {
  if (!newPost.value.content.trim()) { ElMessage.warning('请填写内容'); return }
  posting.value = true
  try {
    const res: any = await wallApi.create({
      chapter_id: props.chapterId,
      topic_key:  props.topicKey,
      post_type:  newPost.value.post_type,
      content:    newPost.value.content,
    })
    ElMessage.success('发布成功')
    if (res.data?.ai_reply) {
      ElMessage.info('AI 已自动给出初步引导，点击帖子查看')
    }
    newPost.value = { post_type: 'stuck', content: '' }
    showPost.value = false
    await loadPosts()
  } catch { ElMessage.error('发布失败') }
  finally { posting.value = false }
}

async function openPost(post: any) {
  currentPost.value = post
  showDetail.value = true
  replyContent.value = ''
  const res: any = await wallApi.replies(post.post_id)
  replies.value = res.data?.replies || []
}

async function submitReply() {
  if (!replyContent.value.trim()) return
  replying.value = true
  try {
    await wallApi.reply(currentPost.value.post_id, replyContent.value)
    replyContent.value = ''
    const res: any = await wallApi.replies(currentPost.value.post_id)
    replies.value = res.data?.replies || []
    await loadPosts()
    ElMessage.success('回复成功')
  } catch { ElMessage.error('回复失败') }
  finally { replying.value = false }
}

async function resolvePost(post: any) {
  await wallApi.resolve(post.post_id)
  post.status = 'resolved'
  ElMessage.success('已标记为已解决')
}

async function likePost(post: any) {
  await wallApi.like(post.post_id)
  post.likes++
}

watch(() => props.chapterId, loadPosts)
onMounted(loadPosts)
</script>

<style scoped>
.wall-section { margin-top: 24px; padding-top: 16px; border-top: 1px solid #f0f0f0; }
.wall-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; }
.wall-title { font-size: 15px; font-weight: 600; color: #303133; }
.post-list { display: flex; flex-direction: column; gap: 10px; }
.post-card {
  background: #fafafa; border: 1px solid #e4e7ed; border-radius: 8px;
  padding: 12px 14px;
}
.post-header { display: flex; align-items: center; gap: 6px; margin-bottom: 8px; flex-wrap: wrap; }
.post-type-tag {
  font-size: 11px; padding: 2px 7px; border-radius: 4px; font-weight: 500;
}
.post-type-tag.stuck   { background: #fff3e0; color: #e65100; }
.post-type-tag.tip     { background: #e8f5e9; color: #2e7d32; }
.post-type-tag.discuss { background: #e3f2fd; color: #1565c0; }
.resolved-tag { font-size: 11px; color: #67c23a; background: #f0f9eb; padding: 2px 7px; border-radius: 4px; }
.featured-tag { font-size: 11px; color: #e6a23c; background: #fdf6ec; padding: 2px 7px; border-radius: 4px; }
.post-author { font-size: 12px; color: #606266; margin-left: auto; }
.post-time   { font-size: 12px; color: #c0c4cc; }
.post-content {
  font-size: 13px; color: #303133; line-height: 1.7; cursor: pointer;
  overflow: hidden; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical;
}
.post-content:hover { color: #409eff; }
.post-footer { display: flex; gap: 14px; margin-top: 8px; }
.post-stat { font-size: 12px; color: #909399; cursor: pointer; }
.post-stat:hover { color: #409eff; }
.resolve-btn { margin-left: auto; color: #67c23a; }
.type-selector { display: flex; gap: 8px; flex-wrap: wrap; }
.type-btn {
  padding: 6px 14px; border-radius: 20px; border: 1px solid #dcdfe6;
  font-size: 13px; cursor: pointer; color: #606266;
}
.type-btn.active { border-color: #409eff; color: #409eff; background: #ecf5ff; }
.detail-post { background: #f7f8fa; border-radius: 8px; padding: 12px 16px; margin-bottom: 16px; }
.reply-list { display: flex; flex-direction: column; gap: 10px; max-height: 300px; overflow-y: auto; margin-bottom: 16px; }
.reply-item { padding: 10px 14px; border-radius: 8px; background: #fff; border: 1px solid #e4e7ed; }
.reply-item.ai-reply { background: #f0f7ff; border-color: #cce0ff; }
.reply-meta { display: flex; align-items: center; gap: 8px; margin-bottom: 6px; }
.ai-tag { font-size: 11px; color: #409eff; font-weight: 500; }
.ai-reply-preview { background: #f0f7ff; border-left: 3px solid #409eff; border-radius: 4px; padding: 8px 10px; margin: 6px 0 4px; font-size: 13px; color: #606266; line-height: 1.6; }
.ai-reply-text { margin-left: 6px; }
.reply-author { font-size: 12px; color: #606266; font-weight: 500; }
.reply-time   { font-size: 12px; color: #c0c4cc; margin-left: auto; }
.reply-content { font-size: 13px; color: #303133; line-height: 1.7; }
</style>
