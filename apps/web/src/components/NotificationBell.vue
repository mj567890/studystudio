<template>
  <el-popover placement="bottom-end" :width="360" trigger="click"
    @show="loadNotifications">
    <template #reference>
      <el-badge :value="unreadCount" :hidden="!unreadCount" :max="99">
        <el-button text style="font-size:18px">
          <el-icon><Bell /></el-icon>
        </el-button>
      </el-badge>
    </template>
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px">
      <span style="font-weight:600;font-size:14px">消息通知</span>
      <el-button v-if="unreadCount" link type="primary" size="small"
        @click="markAllRead">全部已读</el-button>
    </div>
    <el-empty v-if="!loading && !notifications.length"
      description="暂无通知" :image-size="60" />
    <div v-else style="max-height:380px;overflow-y:auto">
      <div v-for="n in notifications" :key="n.id"
        class="notif-item"
        :class="{ 'notif-item--merged': n.type === 'blueprint_merged' }"
        :style="{opacity: n.is_read ? 0.5 : 1}">
        <div style="font-size:13px;font-weight:500;color:#303133">{{ n.title }}</div>
        <!-- 课程更新消息：解析 JSON 展示变更摘要 -->
        <div v-if="n.type === 'blueprint_merged' && parseMergeMsg(n.message)" style="margin-top:4px">
          <div style="font-size:12px;color:#606266;margin-bottom:4px">
            <span v-if="parseMergeMsg(n.message)?.new" style="margin-right:8px">
              ✨ 新增 {{ parseMergeMsg(n.message).new }} 章
            </span>
            <span v-if="parseMergeMsg(n.message)?.enhanced">
              📝 增强 {{ parseMergeMsg(n.message).enhanced }} 章
            </span>
          </div>
          <div style="display:flex;gap:8px">
            <el-button size="small" type="primary" plain @click.stop="goToCourse(parseMergeMsg(n.message))">
              查看变更
            </el-button>
            <el-button size="small" @click.stop="dismissNotif(n)">忽略</el-button>
          </div>
        </div>
        <div v-else-if="n.message" style="font-size:12px;color:#909399;margin-top:3px">{{ n.message }}</div>
        <div style="font-size:11px;color:#c0c4cc;margin-top:4px">{{ fmtTime(n.created_at) }}</div>
      </div>
    </div>
    <div v-if="loading" style="text-align:center;padding:12px;color:#909399;font-size:12px">
      加载中…
    </div>
  </el-popover>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { http } from '@/api'

const router = useRouter()
const notifications = ref<any[]>([])
const unreadCount = ref(0)
const loading = ref(false)
let timer: ReturnType<typeof setInterval>

function parseMergeMsg(msg: string) {
  if (!msg) return null
  try {
    return JSON.parse(msg)
  } catch {
    return null
  }
}

async function loadNotifications() {
  loading.value = true
  try {
    const res: any = await http.get('/notifications?unread_only=true&limit=10')
    notifications.value = res.data?.notifications || []
    unreadCount.value = res.data?.unread_count || 0
  } catch {
    // silently fail
  } finally {
    loading.value = false
  }
}

async function markAllRead() {
  try {
    await http.post('/notifications/read-all')
    unreadCount.value = 0
    notifications.value.forEach((n: any) => (n.is_read = true))
  } catch { /* ignore */ }
}

async function handleClick(n: any) {
  if (!n.is_read) {
    try {
      await http.post(`/notifications/${n.id}/read`)
      n.is_read = true
      unreadCount.value = Math.max(0, unreadCount.value - 1)
    } catch { /* ignore */ }
  }
  // 跳转到对应资源
  if (n.target_type === 'document' && n.target_id) {
    router.push('/upload')
  }
}

function goToCourse(meta: any) {
  if (meta?.topic_key) {
    router.push(`/tutorial?topic=${meta.topic_key}`)
  }
}

async function dismissNotif(n: any) {
  try {
    await http.post(`/notifications/${n.id}/dismiss`)
    n.is_read = true
    unreadCount.value = Math.max(0, unreadCount.value - 1)
  } catch { /* ignore */ }
}

function fmtTime(iso: string) {
  if (!iso) return ''
  const d = new Date(iso)
  const now = new Date()
  const diffMin = Math.floor((now.getTime() - d.getTime()) / 60000)
  if (diffMin < 1) return '刚刚'
  if (diffMin < 60) return `${diffMin} 分钟前`
  if (diffMin < 1440) return `${Math.floor(diffMin / 60)} 小时前`
  return d.toLocaleDateString()
}

onMounted(() => {
  loadNotifications()
  timer = setInterval(loadNotifications, 30000) // 30秒轮询
})

onUnmounted(() => {
  clearInterval(timer)
})
</script>

<style scoped>
.notif-item {
  padding: 10px 12px;
  border-radius: 6px;
  cursor: pointer;
  transition: background 0.15s;
}
.notif-item:hover {
  background: #f5f7fa;
}
.notif-item--merged {
  background: #f0f7ff;
  border: 1px solid #d9ecff;
}
</style>
