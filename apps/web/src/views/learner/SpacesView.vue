<template>
  <div class="page">
    <el-card>
      <template #header>
        <span>我的课程</span>
        <el-button size="small" type="primary" style="float:right; margin-left:8px"
          @click="joinDialog = true">
          <el-icon><Plus /></el-icon> 加入课程
        </el-button>
        <el-button size="small" style="float:right" @click="$router.push('/spaces/trash')">
          <el-icon><Delete /></el-icon> 回收站
        </el-button>
        <el-button size="small" style="float:right" @click="load">刷新</el-button>
      </template>

      <el-table :data="spaces" v-loading="loading" size="small"
        @row-click="onRowClick" style="cursor:pointer">
        <el-table-column prop="name" label="名称" min-width="180">
          <template #default="{ row }">
            <el-icon style="vertical-align:middle"><FolderOpened /></el-icon>
            <span style="margin-left:6px">{{ row.name || '(未命名)' }}</span>
            <el-tag v-if="row.fork_from_space_id" size="small" type="info"
              style="margin-left:6px">Fork</el-tag>
          </template>
        </el-table-column>

        <el-table-column label="可见性" width="100">
          <template #default="{ row }">
            <el-tag size="small" :type="visibilityTag(row.visibility)">{{ visibilityLabel(row.visibility) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="我的角色" width="100">
          <template #default="{ row }">
            <el-tag v-if="row.my_role" size="small" :type="roleTag(row.my_role)">
              {{ roleLabel(row.my_role) }}
            </el-tag>
            <span v-else style="color:#999">-</span>
          </template>
        </el-table-column>
        <el-table-column prop="member_count" label="成员数" width="90" align="center" />
        <el-table-column prop="description" label="描述" show-overflow-tooltip />
        <el-table-column label="操作" width="160">
          <template #default="{ row }">
            <el-button size="small" text type="primary" @click.stop="goDetail(row)">
              管理
            </el-button>
            <el-button
              v-if="canFork(row)"
              size="small" text type="warning"
              @click.stop="openForkDialog(row)">
              Fork
            </el-button>
          </template>
        </el-table-column>
      </el-table>

      <div v-if="!loading && spaces.length === 0" class="empty">
        你还没有课程，去上传资料创建吧
      </div>
    </el-card>

    <!-- 加入课程 dialog -->
    <el-dialog v-model="joinDialog" title="加入课程" width="420px">
      <el-form @submit.prevent>
        <el-form-item label="邀请码">
          <el-input v-model="joinCode" placeholder="请输入 8 位邀请码"
            maxlength="32" style="text-transform:uppercase"
            @keydown.enter="doJoin" />
        </el-form-item>
        <p style="color:#909399; font-size:12px; margin: 0 0 8px 0">
          向课程创建者索取邀请码，或通过收到的邀请链接加入。
        </p>
      </el-form>
      <template #footer>
        <el-button @click="joinDialog = false">取消</el-button>
        <el-button type="primary" :loading="joining" @click="doJoin">加入</el-button>
      </template>
    </el-dialog>

    <!-- Fork 确认 dialog -->
    <el-dialog v-model="forkDialog" title="Fork 空间" width="460px">
      <p style="margin:0 0 12px 0; color:#606266">
        将「<strong>{{ forkTarget?.name }}</strong>」的所有知识点和课程结构复制到你的新空间，你可以自由修改，不影响原作者。
      </p>
      <el-form @submit.prevent>
        <el-form-item label="新空间名称">
          <el-input v-model="forkName" :placeholder="`[Fork] ${forkTarget?.name || ''}`" maxlength="255" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="forkDialog = false">取消</el-button>
        <el-button type="warning" :loading="forking" @click="doFork">确认 Fork</el-button>
      </template>
    </el-dialog>

    <!-- Fork 进度 dialog -->
    <el-dialog v-model="forkProgressDialog" title="正在 Fork..." width="400px"
      :close-on-click-modal="false" :close-on-press-escape="false" :show-close="false">
      <div style="text-align:center; padding: 20px 0">
        <el-progress type="circle" :percentage="forkProgressPct"
          :status="forkProgressStatus" />
        <p style="margin-top:16px; color:#606266">{{ forkProgressMsg }}</p>
      </div>
      <template #footer>
        <el-button v-if="forkDone" type="primary" @click="onForkDone">
          前往新空间
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { spaceApi } from '@/api'

const router = useRouter()
const loading = ref(false)
const spaces = ref<any[]>([])

// -- 加入课程 --
const joinDialog = ref(false)
const joinCode = ref('')
const joining = ref(false)

// -- Fork --
const forkDialog = ref(false)
const forkTarget = ref<any>(null)
const forkName = ref('')
const forking = ref(false)

const forkProgressDialog = ref(false)
const forkProgressPct = ref(0)
const forkProgressStatus = ref<'' | 'success' | 'exception'>('')
const forkProgressMsg = ref('正在复制知识点和课程结构...')
const forkDone = ref(false)
const forkTaskId = ref('')
const forkTargetSpaceId = ref('')
let pollTimer: ReturnType<typeof setInterval> | null = null

async function load() {
  loading.value = true
  try {
    const res: any = await spaceApi.list()
    spaces.value = res.data || []
  } finally { loading.value = false }
}

function onRowClick(row: any) { goDetail(row) }
function goDetail(row: any) { router.push(`/spaces/${row.space_id}`) }

// Fork 按钮只对 public + allow_fork 课程（且自己不是 owner）显示
function canFork(row: any): boolean {
  if (row.visibility === 'public' && row.allow_fork !== false && row.my_role !== 'owner') return true
  return false
}

function openForkDialog(row: any) {
  forkTarget.value = row
  forkName.value = ''
  forkDialog.value = true
}

async function doFork() {
  if (!forkTarget.value) return
  forking.value = true
  try {
    const name = forkName.value.trim() || undefined
    const res: any = await spaceApi.fork(forkTarget.value.space_id, name)
    const d = res.data
    forkTaskId.value = d.task_id
    forkTargetSpaceId.value = d.target_space_id
    forkDialog.value = false
    startForkPoll()
  } catch {
    // axios 拦截器已弹错误
  } finally { forking.value = false }
}

function startForkPoll() {
  forkProgressDialog.value = true
  forkProgressPct.value = 10
  forkProgressStatus.value = ''
  forkProgressMsg.value = '正在复制知识点和课程结构...'
  forkDone.value = false

  pollTimer = setInterval(async () => {
    try {
      const res: any = await spaceApi.getForkStatus(forkTaskId.value)
      const status = res.data?.status
      if (status === 'running') {
        forkProgressPct.value = Math.min(forkProgressPct.value + 15, 85)
      } else if (status === 'done') {
        clearPoll()
        forkProgressPct.value = 100
        forkProgressStatus.value = 'success'
        forkProgressMsg.value = 'Fork 完成！新空间已就绪。'
        forkDone.value = true
        await load()
      } else if (status === 'failed') {
        clearPoll()
        forkProgressStatus.value = 'exception'
        forkProgressMsg.value = res.data?.error_msg || 'Fork 失败，请稍后重试'
        forkDone.value = true
      }
    } catch { clearPoll() }
  }, 2000)
}

function clearPoll() {
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null }
}

function onForkDone() {
  forkProgressDialog.value = false
  router.push(`/spaces/${forkTargetSpaceId.value}`)
}

async function doJoin() {
  const code = joinCode.value.trim().toUpperCase()
  if (!code) { ElMessage.warning('请输入邀请码'); return }
  joining.value = true
  try {
    const res: any = await spaceApi.joinByCode(code)
    const d = res.data
    if (d.already_member) {
      ElMessage.info(`你已经是「${d.space_name}」的成员`)
    } else {
      ElMessage.success(`已加入「${d.space_name}」`)
    }
    joinDialog.value = false
    joinCode.value = ''
    await load()
    router.push(`/spaces/${d.space_id}`)
  } catch {} finally { joining.value = false }
}

function visibilityLabel(v: string) {
  return { private: '私有', shared: '私有', public: '公开' }[v] || v
}
function visibilityTag(v: string): any {
  return { private: 'info', shared: 'info', public: 'success' }[v] || ''
}
function roleLabel(r: string) {
  return { owner: '创建者', admin: '协管', member: '成员' }[r] || r
}
function roleTag(r: string): any {
  return { owner: 'danger', admin: 'warning', member: '' }[r] || ''
}

onMounted(load)
onUnmounted(clearPoll)
</script>

<style scoped>
.page { padding: 8px; }
.empty { text-align: center; color: #909399; padding: 40px 0; }
</style>
