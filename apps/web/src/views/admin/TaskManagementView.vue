<template>
  <div class="task-page">
    <!-- 统计概览 -->
    <div class="stats-row">
      <el-card shadow="hover" class="stat-card">
        <el-statistic title="7天内任务总数" :value="stats.total" />
      </el-card>
      <el-card shadow="hover" class="stat-card stat-warning">
        <el-statistic title="需人工处理" :value="stats.needs_review">
          <template #suffix>
            <el-tag v-if="stats.needs_review > 0" type="danger" size="small">待处理</el-tag>
          </template>
        </el-statistic>
      </el-card>
      <el-card shadow="hover" class="stat-card stat-danger">
        <el-statistic title="最终失败" :value="stats.failed" />
      </el-card>
      <el-card shadow="hover" class="stat-card">
        <el-statistic title="重试中" :value="stats.retrying" />
      </el-card>
      <el-card shadow="hover" class="stat-card stat-success">
        <el-statistic title="24h内成功" :value="stats.succeeded_24h" />
      </el-card>
    </div>

    <!-- 筛选器 -->
    <el-card class="filter-card">
      <el-row :gutter="16" align="middle">
        <el-col :span="6">
          <el-select v-model="filterTaskName" placeholder="按任务类型筛选" clearable @change="fetchTasks()">
            <el-option v-for="t in filterOptions.task_names" :key="t.value"
              :label="t.label" :value="t.value" />
          </el-select>
        </el-col>
        <el-col :span="4">
          <el-select v-model="filterStatus" placeholder="按状态筛选" clearable @change="fetchTasks()">
            <el-option v-for="s in filterOptions.statuses" :key="s" :label="statusLabel(s)" :value="s" />
          </el-select>
        </el-col>
        <el-col :span="4">
          <el-select v-model="filterNeedsReview" placeholder="人工处理标记" clearable @change="fetchTasks()">
            <el-option label="需人工处理" :value="true" />
            <el-option label="已处理" :value="false" />
          </el-select>
        </el-col>
        <el-col :span="6">
          <el-button type="primary" @click="fetchTasks(); fetchStats()">查询</el-button>
          <el-button @click="resetFilters()">重置</el-button>
        </el-col>
        <el-col :span="4" style="text-align:right">
          <el-checkbox v-model="autoRefresh" @change="toggleAutoRefresh">
            每15秒自动刷新
          </el-checkbox>
        </el-col>
      </el-row>
    </el-card>

    <!-- 失败任务列表 -->
    <el-card class="table-card">
      <template #header>
        <div class="card-header">
          <span>任务执行记录</span>
          <div class="header-actions">
            <span v-if="selectedIds.length > 0" class="selected-hint">
              已选 {{ selectedIds.length }} 项
              <el-button size="small" type="warning" @click="batchRetry">批量重试</el-button>
            </span>
            <el-button size="small" type="primary" @click="fetchTasks(); fetchStats()">
              <el-icon><Refresh /></el-icon>刷新
            </el-button>
          </div>
        </div>
      </template>

      <el-table
        :data="tasks"
        v-loading="loading"
        stripe
        @selection-change="onSelectionChange"
        style="width:100%"
      >
        <el-table-column type="selection" width="40" />
        <el-table-column prop="task_label" label="任务类型" width="140" />
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="statusTagType(row.status)" size="small" effect="dark">
              {{ statusLabel(row.status) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="错误信息" min-width="200">
          <template #default="{ row }">
            <div class="error-cell">
              <span v-if="row.error_message" class="error-text">{{ truncate(row.error_message, 120) }}</span>
              <span v-else class="no-error">—</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="doc_title" label="关联文档" width="140">
          <template #default="{ row }">
            <span v-if="row.doc_title">{{ row.doc_title }}</span>
            <span v-else class="muted">—</span>
          </template>
        </el-table-column>
        <el-table-column prop="space_name" label="关联空间" width="120">
          <template #default="{ row }">
            <span v-if="row.space_name">{{ row.space_name }}</span>
            <span v-else class="muted">—</span>
          </template>
        </el-table-column>
        <el-table-column prop="queue_label" label="队列" width="100" />
        <el-table-column label="重试" width="80">
          <template #default="{ row }">
            <span>{{ row.retry_count }} / {{ row.max_retries }}</span>
          </template>
        </el-table-column>
        <el-table-column label="时间" width="170">
          <template #default="{ row }">
            <div class="time-cell">
              <span>{{ formatTime(row.created_at) }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="180" fixed="right">
          <template #default="{ row }">
            <div class="action-cell">
              <el-button size="small" type="primary" link @click="showDetail(row)">详情</el-button>
              <el-button
                v-if="row.status === 'failed' || row.status === 'retrying' || row.needs_manual_review"
                size="small" type="warning" link
                :loading="retryingIds.has(row.id)"
                @click="retryTask(row)"
              >
                重试
              </el-button>
              <el-button
                v-if="row.status === 'failed' || row.needs_manual_review"
                size="small" type="danger" link
                @click="cancelTask(row)"
              >
                取消
              </el-button>
            </div>
          </template>
        </el-table-column>
      </el-table>

      <div class="pagination-wrapper">
        <el-pagination
          v-model:current-page="currentPage"
          v-model:page-size="pageSize"
          :page-sizes="[10, 20, 50, 100]"
          :total="total"
          layout="total, sizes, prev, pager, next"
          @size-change="fetchTasks()"
          @current-change="fetchTasks()"
        />
      </div>
    </el-card>

    <!-- 任务详情对话框 -->
    <el-dialog v-model="detailVisible" title="任务执行详情" width="700px" destroy-on-close>
      <template v-if="detailTask">
        <el-descriptions :column="2" border>
          <el-descriptions-item label="任务类型">{{ detailTask.task_label }}</el-descriptions-item>
          <el-descriptions-item label="状态">
            <el-tag :type="statusTagType(detailTask.status)" size="small" effect="dark">
              {{ statusLabel(detailTask.status) }}
            </el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="队列">{{ detailTask.queue_label }}</el-descriptions-item>
          <el-descriptions-item label="重试次数">{{ detailTask.retry_count }} / {{ detailTask.max_retries }}</el-descriptions-item>
          <el-descriptions-item label="关联文档">{{ detailTask.doc_title || '—' }}</el-descriptions-item>
          <el-descriptions-item label="关联空间">{{ detailTask.space_name || '—' }}</el-descriptions-item>
          <el-descriptions-item label="创建时间">{{ formatTime(detailTask.created_at) }}</el-descriptions-item>
          <el-descriptions-item label="完成时间">{{ formatTime(detailTask.completed_at) || '—' }}</el-descriptions-item>
          <el-descriptions-item label="需人工处理" :span="2">
            <el-tag v-if="detailTask.needs_manual_review" type="danger">是（已两次失败，需管理员介入）</el-tag>
            <span v-else>否</span>
          </el-descriptions-item>
          <el-descriptions-item v-if="detailTask.manual_action_taken" label="已执行操作">
            {{ detailTask.manual_action_taken }} <span v-if="detailTask.manual_action_by">({{ detailTask.manual_action_by }})</span>
            <span v-if="detailTask.manual_action_at"> — {{ formatTime(detailTask.manual_action_at) }}</span>
          </el-descriptions-item>
          <el-descriptions-item v-if="detailTask.error_message" label="错误信息" :span="2">
            <div class="error-detail">{{ detailTask.error_message }}</div>
          </el-descriptions-item>
        </el-descriptions>

        <div v-if="detailTask.error_traceback" style="margin-top:16px">
          <h4>完整堆栈</h4>
          <pre class="traceback-block">{{ detailTask.error_traceback }}</pre>
        </div>

        <div style="margin-top:16px; text-align:right">
          <el-button
            v-if="detailTask.status === 'failed' || detailTask.needs_manual_review"
            type="warning" @click="retryTask(detailTask); detailVisible = false"
          >
            重新派发
          </el-button>
          <el-button
            v-if="detailTask.status === 'failed' || detailTask.needs_manual_review"
            type="danger" @click="cancelTask(detailTask); detailVisible = false"
          >
            标记取消
          </el-button>
          <el-button @click="detailVisible = false">关闭</el-button>
        </div>
      </template>
    </el-dialog>

    <!-- 按任务类型分布 -->
    <el-card v-if="stats.by_name && stats.by_name.length > 0" class="dist-card">
      <template #header><span>按任务类型分布（近7天）</span></template>
      <div class="dist-row">
        <el-tag
          v-for="item in stats.by_name" :key="item.task_name"
          :type="item.failed > 0 ? 'danger' : 'info'"
          size="small"
          class="dist-tag"
        >
          {{ item.task_label }}: {{ item.count }}
          <template v-if="item.failed > 0">（失败{{ item.failed }}）</template>
        </el-tag>
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Refresh } from '@element-plus/icons-vue'
import { adminApi } from '@/api'

const route = useRoute()
const loading = ref(false)
const autoRefresh = ref(false)
const tasks = ref<any[]>([])
const stats = ref<any>({})
const total = ref(0)
const currentPage = ref(1)
const pageSize = ref(20)
const detailVisible = ref(false)
const detailTask = ref<any>(null)
const retryingIds = ref(new Set<string>())
const selectedIds = ref<string[]>([])

const filterTaskName = ref('')
const filterStatus = ref('')
const filterNeedsReview = ref<boolean | null>(null)
const filterOptions = ref<any>({ task_names: [], queues: [], statuses: ['failed', 'retrying', 'succeeded', 'cancelled'] })

let _timer: any = null

onMounted(() => {
  const statusParam = route.query.status as string
  if (statusParam && ['failed', 'retrying', 'succeeded', 'cancelled', 'running'].includes(statusParam)) {
    filterStatus.value = statusParam
  }
  fetchFilters()
  fetchTasks()
  fetchStats()
})

onUnmounted(() => {
  clearInterval(_timer)
})

function formatTime(iso: string | null): string {
  if (!iso) return '—'
  const d = new Date(iso)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getMonth() + 1}/${d.getDate()} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}

function truncate(text: string, maxLen: number): string {
  if (!text) return ''
  return text.length > maxLen ? text.slice(0, maxLen) + '…' : text
}

function statusLabel(status: string): string {
  const map: Record<string, string> = {
    pending: '等待中', retrying: '重试中', failed: '已失败',
    succeeded: '已成功', cancelled: '已取消',
  }
  return map[status] || status
}

function statusTagType(status: string): string {
  const map: Record<string, string> = {
    pending: 'info', retrying: 'warning', failed: 'danger',
    succeeded: 'success', cancelled: 'info',
  }
  return map[status] || 'info'
}

async function fetchFilters() {
  try {
    const res: any = await adminApi.getTaskFilters()
    filterOptions.value = res.data || filterOptions.value
  } catch { /* ignore */ }
}

async function fetchStats() {
  try {
    const res: any = await adminApi.getTaskStats()
    stats.value = res.data || {}
  } catch { /* ignore */ }
}

async function fetchTasks() {
  loading.value = true
  try {
    const params: any = { page: currentPage.value, page_size: pageSize.value }
    if (filterTaskName.value) params.task_name = filterTaskName.value
    if (filterStatus.value) params.status = filterStatus.value
    if (filterNeedsReview.value !== null) params.needs_review = filterNeedsReview.value

    // 默认查询失败/需人工处理的任务；有筛选条件时查询全量
    let res: any
    if (filterTaskName.value || filterStatus.value || filterNeedsReview.value !== null) {
      res = await adminApi.listTasks(params)
    } else {
      res = await adminApi.listFailedTasks(params)
    }
    tasks.value = res.data?.tasks || []
    total.value = res.data?.total || 0
  } catch {
    ElMessage.error('加载任务列表失败')
  } finally {
    loading.value = false
  }
}

function resetFilters() {
  filterTaskName.value = ''
  filterStatus.value = ''
  filterNeedsReview.value = null
  currentPage.value = 1
  fetchTasks()
}

async function retryTask(row: any) {
  retryingIds.value.add(row.id)
  try {
    const res: any = await adminApi.retryTask(row.id)
    if (res.data?.success) {
      ElMessage.success(res.data?.message || '已重新派发')
      fetchTasks()
      fetchStats()
    } else {
      ElMessage.warning(res.msg || '重试失败')
    }
  } catch {
    ElMessage.error('重试请求失败')
  } finally {
    retryingIds.value.delete(row.id)
  }
}

async function cancelTask(row: any) {
  try {
    await ElMessageBox.confirm(`确认取消此 ${row.task_label} 任务？取消后系统不会再次自动重试。`, '取消任务', {
      confirmButtonText: '确认取消',
      cancelButtonText: '返回',
      type: 'warning',
    })
  } catch { return }

  try {
    const res: any = await adminApi.cancelTask(row.id)
    if (res.data?.success) {
      ElMessage.success(res.data?.message || '已取消')
      fetchTasks()
      fetchStats()
    } else {
      ElMessage.warning(res.msg || '取消失败')
    }
  } catch {
    ElMessage.error('取消请求失败')
  }
}

async function batchRetry() {
  try {
    await ElMessageBox.confirm(`确认批量重试所选的 ${selectedIds.value.length} 个任务？`, '批量重试', {
      confirmButtonText: '确认', cancelButtonText: '返回', type: 'warning',
    })
  } catch { return }

  try {
    const res: any = await adminApi.batchRetryTasks({ execution_ids: selectedIds.value })
    if (res.data?.success) {
      ElMessage.success(res.data?.message || '批量重试已提交')
      fetchTasks()
      fetchStats()
    } else {
      ElMessage.warning(res.msg || '批量重试失败')
    }
  } catch {
    ElMessage.error('批量重试请求失败')
  }
}

function showDetail(row: any) {
  detailTask.value = row
  detailVisible.value = true
}

function onSelectionChange(rows: any[]) {
  selectedIds.value = rows.map(r => r.id)
}

function toggleAutoRefresh(val: boolean) {
  if (val) {
    _timer = setInterval(() => { fetchTasks(); fetchStats() }, 15000)
  } else {
    clearInterval(_timer)
  }
}
</script>

<style scoped>
.task-page { padding: 0; }
.stats-row { display: flex; gap: 12px; margin-bottom: 16px; flex-wrap: wrap; }
.stat-card { flex: 1; min-width: 140px; }
.stat-card :deep(.el-statistic__head) { font-size: 13px; color: #909399; }
.stat-warning :deep(.el-statistic__number) { color: #e6a23c; }
.stat-danger :deep(.el-statistic__number) { color: #f56c6c; }
.stat-success :deep(.el-statistic__number) { color: #67c23a; }

.filter-card { margin-bottom: 16px; }
.table-card { margin-bottom: 16px; }
.card-header { display: flex; justify-content: space-between; align-items: center; }
.header-actions { display: flex; align-items: center; gap: 8px; }
.selected-hint { color: #e6a23c; font-size: 13px; }

.error-cell { font-size: 13px; }
.error-text { color: #f56c6c; }
.no-error { color: #c0c4cc; }
.muted { color: #c0c4cc; }

.action-cell { display: flex; gap: 4px; flex-wrap: wrap; }

.error-detail {
  background: #fef0f0; border: 1px solid #fde2e2; border-radius: 4px;
  padding: 12px; font-size: 13px; color: #f56c6c; max-height: 200px; overflow-y: auto;
  word-break: break-all; white-space: pre-wrap;
}

.traceback-block {
  background: #1d2b3a; color: #e0e0e0; border-radius: 4px;
  padding: 12px; font-size: 12px; max-height: 300px; overflow-y: auto;
  white-space: pre-wrap; word-break: break-all;
}

.pagination-wrapper { margin-top: 16px; display: flex; justify-content: flex-end; }
.time-cell { font-size: 12px; color: #909399; }
.dist-card { margin-top: 16px; }
.dist-row { display: flex; gap: 8px; flex-wrap: wrap; }
.dist-tag { cursor: default; }
</style>
