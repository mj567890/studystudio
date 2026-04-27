<template>
  <div class="page">
    <el-page-header @back="$router.push('/spaces')" :content="space?.name || '加载中...'" style="margin-bottom:12px">
      <template #extra>
        <el-button size="small" @click="router.push(`/spaces/${spaceId}/posts`)">
          💬 讨论区
        </el-button>
      </template>
    </el-page-header>

    <el-card v-loading="loading">
      <template #header>
        <div style="display:flex; align-items:center; justify-content:space-between">
          <span>空间信息</span>
          <el-tag v-if="space?.my_role" size="small" :type="roleTag(space.my_role)">
            我是 {{ roleLabel(space.my_role) }}
          </el-tag>
        </div>
      </template>

      <el-descriptions :column="2" border v-if="space">
        <el-descriptions-item label="名称">
          <el-input v-if="editable" v-model="editForm.name" size="small" />
          <span v-else>{{ space.name || '-' }}</span>
        </el-descriptions-item>

        <el-descriptions-item label="可见性">
          <el-select v-if="editable" v-model="editForm.visibility" size="small" style="width:160px">
            <el-option label="🔒 私有" value="private" />
            <el-option label="🌐 公开（出现在发现页）" value="public" />
          </el-select>
          <el-tag v-else size="small" :type="visibilityTag(space.visibility)">
            {{ visibilityLabel(space.visibility) }}
          </el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="成员数">{{ space.member_count }}</el-descriptions-item>
        <el-descriptions-item label="描述" :span="2">
          <el-input v-if="editable" v-model="editForm.description" type="textarea" :rows="2" size="small" />
          <span v-else style="white-space:pre-wrap">{{ space.description || '-' }}</span>
        </el-descriptions-item>
      </el-descriptions>

      <div v-if="canManage" style="margin-top:12px; text-align:right">
        <template v-if="!editable">
          <el-button size="small" @click="startEdit">编辑</el-button>
        </template>
        <template v-else>
          <el-button size="small" @click="editable = false">取消</el-button>
          <el-button size="small" type="primary" :loading="saving" @click="saveEdit">保存</el-button>
        </template>
      </div>
    </el-card>

    <el-card v-if="canManage && space?.visibility !== 'public'" style="margin-top:12px">
      <template #header><span>邀请码</span></template>
      <div v-if="space?.invite_code" class="invite-row">
        <div class="invite-info">
          <div class="invite-code">{{ space.invite_code }}</div>
          <div class="invite-link">
            加入链接:
            <el-input size="small" readonly :model-value="inviteUrl" style="width:340px; margin-left:4px">
              <template #append>
                <el-button @click="copyLink">复制</el-button>
              </template>
            </el-input>
          </div>
        </div>
        <div class="invite-actions">
          <el-popconfirm title="重置后旧邀请码将失效,确定继续?" @confirm="resetCode">
            <template #reference><el-button size="small">重置</el-button></template>
          </el-popconfirm>
          <el-popconfirm title="废除后任何人都无法用旧邀请码加入,确定继续?" @confirm="revokeCode">
            <template #reference><el-button size="small" type="danger">废除</el-button></template>
          </el-popconfirm>
        </div>
      </div>
      <div v-else class="invite-empty">
        <span style="color:#909399">当前未设置邀请码</span>
        <el-button size="small" type="primary" @click="resetCode">生成邀请码</el-button>
      </div>
    </el-card>

    <el-card style="margin-top:12px">
      <template #header>
        <span>成员 ({{ members.length }})</span>
      </template>
      <el-table :data="members" v-loading="loadingMembers" size="small">
        <el-table-column prop="nickname" label="昵称" width="140" />
        <el-table-column prop="email" label="邮箱" show-overflow-tooltip />
        <el-table-column label="角色" width="120">
          <template #default="{ row }">
            <el-tag size="small" :type="roleTag(row.role)">{{ roleLabel(row.role) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="加入时间" width="170">
          <template #default="{ row }">{{ formatDate(row.joined_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="140">
          <template #default="{ row }">
            <el-button v-if="canRemove(row)" size="small" text type="danger"
              @click="removeMember(row)">
              {{ isSelf(row) ? '退出空间' : '移除' }}
            </el-button>
            <span v-else style="color:#c0c4cc; font-size:12px">-</span>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 学习路径 -->
    <el-card style="margin-top:12px" v-if="blueprint">
      <template #header>
        <div style="display:flex;align-items:center;justify-content:space-between">
          <span>学习路径</span>
          <div style="display:flex;align-items:center;gap:10px">
            <el-tag size="small" :type="blueprintStatusTag(blueprint.status)">
              {{ blueprintStatusLabel(blueprint.status) }}
            </el-tag>
            <el-button size="small" type="primary"
              :loading="regenerating"
              :disabled="blueprint.status === 'generating'"
              @click="regeneratePath">
              重新生成路径
            </el-button>
          </div>
        </div>
      </template>
      <div style="color:#606266;font-size:13px">
        <span>蓝图：{{ blueprint.title }}</span>
        <span style="margin-left:16px;color:#909399">主题：{{ blueprint.topic_key }}</span>
      </div>
      <div v-if="regenerating" style="margin-top:12px">
        <el-progress :percentage="Math.round(regenProgress)"
          :stroke-width="8" striped striped-flow :duration="10" />
        <p style="text-align:center;color:#909399;font-size:12px;margin-top:6px">
          AI 正在重新生成，通常需要 1-2 分钟…
        </p>
      </div>
    </el-card>

    <!-- 知识点列表 -->
    <el-card style="margin-top:12px" v-loading="loadingEntities">
      <template #header>
        <div style="display:flex;align-items:center;justify-content:space-between">
          <span>知识点（已审核）<el-tag size="small" style="margin-left:8px">{{ entityTotal }}</el-tag></span>
          <el-input v-model="entitySearch" placeholder="搜索知识点" clearable size="small"
            style="width:200px" prefix-icon="Search" />
        </div>
      </template>
      <el-empty v-if="filteredEntities.length === 0" description="暂无已审核知识点" />
      <el-table v-else :data="filteredEntities" size="small" max-height="400">
        <el-table-column prop="canonical_name" label="名称" min-width="140" />
        <el-table-column prop="entity_type" label="类型" width="90" />
        <el-table-column prop="domain_tag" label="领域" width="120" show-overflow-tooltip />
        <el-table-column prop="short_definition" label="定义" show-overflow-tooltip />
        <el-table-column label="核心" width="60">
          <template #default="{ row }">
            <el-tag v-if="row.is_core" size="small" type="warning">核心</el-tag>
          </template>
        </el-table-column>

      </el-table>
    </el-card>

  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { spaceApi, blueprintApi } from '@/api'
import { useAuthStore } from '@/stores/auth'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

const spaceId = computed(() => route.params.space_id as string)

const loading = ref(false)
const loadingMembers = ref(false)
const saving = ref(false)
const editable = ref(false)

const space = ref<any>(null)
const members = ref<any[]>([])
const editForm = ref<any>({ name: '', description: '', visibility: 'private' })

const canManage = computed(() => ['owner', 'admin'].includes(space.value?.my_role))
const inviteUrl = computed(() =>
  space.value?.invite_code
    ? `${window.location.origin}/join/${space.value.invite_code}`
    : ''
)

async function load() {
    loadEntities()
  loading.value = true
  try {
    const res: any = await spaceApi.get(spaceId.value)
    space.value = res.data
  } catch {
    router.push('/spaces')
    return
  } finally { loading.value = false }
  await loadMembers()
}

async function loadMembers() {
  loadingMembers.value = true
  try {
    const res: any = await spaceApi.listMembers(spaceId.value)
    members.value = res.data || []
  } finally { loadingMembers.value = false }
}

function startEdit() {
  editForm.value = {
    name: space.value.name || '',
    description: space.value.description || '',
    visibility: space.value.visibility || 'private',
  }
  editable.value = true
}

async function saveEdit() {
  saving.value = true
  try {
    const res: any = await spaceApi.update(spaceId.value, editForm.value)
    space.value = res.data
    editable.value = false
    ElMessage.success('已保存')
  } catch {} finally { saving.value = false }
}

async function resetCode() {
  try {
    const res: any = await spaceApi.resetInviteCode(spaceId.value)
    space.value = { ...space.value, invite_code: res.data.invite_code }
    ElMessage.success('邀请码已生成')
  } catch {}
}

async function revokeCode() {
  try {
    await spaceApi.revokeInviteCode(spaceId.value)
    space.value = { ...space.value, invite_code: null }
    ElMessage.success('邀请码已废除')
  } catch {}
}

async function copyLink() {
  const url = inviteUrl.value
  // 优先走现代 API(需 HTTPS 或 localhost)
  if (navigator.clipboard && window.isSecureContext) {
    try {
      await navigator.clipboard.writeText(url)
      ElMessage.success('已复制链接')
      return
    } catch { /* 继续走 fallback */ }
  }
  // 回退:临时 textarea + execCommand('copy'),兼容 HTTP 环境
  try {
    const ta = document.createElement('textarea')
    ta.value = url
    ta.style.position = 'fixed'
    ta.style.top = '0'
    ta.style.left = '0'
    ta.style.opacity = '0'
    document.body.appendChild(ta)
    ta.focus()
    ta.select()
    const ok = document.execCommand('copy')
    document.body.removeChild(ta)
    if (ok) {
      ElMessage.success('已复制链接')
    } else {
      ElMessage.warning('复制失败,请手动选中复制')
    }
  } catch {
    ElMessage.warning('复制失败,请手动选中复制')
  }
}

function isSelf(row: any) { return row.user_id === auth.user?.user_id }
function canRemove(row: any): boolean {
  if (row.role === 'owner') return false
  if (isSelf(row)) return true
  return canManage.value
}

async function removeMember(row: any) {
  const selfLeave = isSelf(row)
  const title = selfLeave ? '退出空间' : '移除成员'
  const msg = selfLeave
    ? `确定要退出「${space.value.name}」?`
    : `确定要移除「${row.nickname || row.email}」?`
  try {
    await ElMessageBox.confirm(msg, title, { type: 'warning' })
  } catch { return }
  try {
    await spaceApi.removeMember(spaceId.value, row.user_id)
    ElMessage.success(selfLeave ? '已退出空间' : '已移除成员')
    if (selfLeave) {
      router.push('/spaces')
    } else {
      await load()
    }
  } catch {}
}

function formatDate(d: string) {
  return d ? new Date(d).toLocaleString('zh-CN') : '-'
}
function visibilityLabel(v: string) { return { private:'私有', shared:'私有', public:'公开' }[v] || v }
function visibilityTag(v: string): any { return { private:'info', shared:'info', public:'success' }[v] || '' }
function roleLabel(r: string) { return { owner:'创建者', admin:'协管', member:'成员' }[r] || r }
function roleTag(r: string): any { return { owner:'danger', admin:'warning', member:'' }[r] || '' }

// 蓝图 / 学习路径
const blueprint     = ref<any>(null)
const regenerating  = ref(false)
const regenProgress = ref(0)
let _regenPoll: any = null
let _regenTimer: any = null

async function loadBlueprint() {
  try {
    const res: any = await spaceApi.getBlueprint(spaceId.value)
    blueprint.value = res.data
  } catch {}
}

function blueprintStatusLabel(s: string) {
  return { draft:'草稿', generating:'生成中', review:'待审核', published:'已发布', archived:'已归档' }[s] || s
}
function blueprintStatusTag(s: string): any {
  return { draft:'info', generating:'warning', review:'', published:'success', archived:'info' }[s] || ''
}

async function regeneratePath() {
  if (!blueprint.value?.topic_key) return
  regenerating.value = true
  regenProgress.value = 0
  try {
    await blueprintApi.generate(blueprint.value.topic_key, true)
    // 轮询状态
    _regenTimer = setInterval(() => {
      if (regenProgress.value < 95) regenProgress.value += regenProgress.value < 30 ? 3 : 1
    }, 1000)
    _regenPoll = setInterval(async () => {
      try {
        const res: any = await blueprintApi.getStatus(blueprint.value.topic_key)
        const st = res.data?.status
        if (st === 'published' || st === 'failed') {
          clearInterval(_regenPoll); clearInterval(_regenTimer)
          regenProgress.value = 100
          regenerating.value = false
          await loadBlueprint()
          ElMessage[st === 'published' ? 'success' : 'error'](
            st === 'published' ? '路径重新生成完成' : '生成失败，请重试'
          )
        }
      } catch {}
    }, 3000)
  } catch {
    regenerating.value = false
    ElMessage.error('触发失败，请重试')
  }
}

// 知识点列表
const entities        = ref<any[]>([])
const entityTotal     = ref(0)
const loadingEntities = ref(false)
const entitySearch    = ref('')
const filteredEntities = computed(() =>
  entities.value.filter(e =>
    !entitySearch.value ||
    e.canonical_name.includes(entitySearch.value) ||
    (e.domain_tag || '').includes(entitySearch.value)
  )
)

async function loadEntities() {
  if (!spaceId.value) return
  loadingEntities.value = true
  try {
    const res: any = await spaceApi.listEntities(spaceId.value)
    entities.value  = res.data.data.entities
    entityTotal.value = res.data.data.total
  } catch {} finally {
    loadingEntities.value = false
  }
}


watch(spaceId, () => { load(); loadBlueprint() })
onMounted(() => { load(); loadBlueprint() })
</script>

<style scoped>
.page { padding: 8px; }
.invite-row { display:flex; align-items:center; justify-content:space-between; gap:12px }
.invite-info { flex:1; }
.invite-code { font-family: monospace; font-size: 22px; font-weight: bold; color: #409eff; letter-spacing: 2px; }
.invite-link { margin-top: 8px; font-size: 12px; color: #606266; display:flex; align-items:center; }
.invite-actions { display:flex; gap:8px; }
.invite-empty { display:flex; align-items:center; justify-content:space-between; }
</style>
