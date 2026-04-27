<template>
  <div class="page">
    <!-- 系统初始化向导（首次使用） -->
    <el-alert v-if="!initStatus?.init_completed && initStatus?.needs_seed"
      type="warning" show-icon :closable="false" style="margin-bottom:20px">
      <template #title>系统尚未初始化，请先导入种子知识库</template>
      <template #default>
        <el-button type="primary" size="small" :loading="seeding" @click="doSeed"
          style="margin-top:8px">
          一键导入种子知识库
        </el-button>
        <el-button size="small" :loading="prebuilding" @click="doPrebuild"
          style="margin-top:8px;margin-left:8px">
          预生成冷启动题库
        </el-button>
      </template>
    </el-alert>

    <!-- 统计卡片 -->
    <el-row :gutter="16" style="margin-bottom:20px">
      <el-col :span="6">
        <el-card class="stat-card">
          <el-statistic title="活跃用户" :value="stats.active_users || 0" />
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card class="stat-card">
          <el-statistic title="已审核知识点" :value="stats.approved_entities || 0" />
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card class="stat-card" :class="{ 'has-pending': stats.pending_entities > 0 }">
          <el-statistic title="待审核知识点" :value="stats.pending_entities || 0">
            <template #suffix>
              <el-button v-if="stats.pending_entities > 0" type="danger" text size="small"
                @click="router.push('/admin/review')">去审核</el-button>
            </template>
          </el-statistic>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card class="stat-card">
          <el-statistic title="学习对话总数" :value="stats.total_conversations || 0" />
        </el-card>
      </el-col>
    </el-row>

    <!-- 快捷操作 -->
    <el-row :gutter="16">
      <el-col :span="12">
        <el-card>
          <template #header>快捷操作</template>
          <el-space direction="vertical" style="width:100%">
            <el-button style="width:100%;justify-content:flex-start"
              @click="router.push('/admin/review')">
              知识审核
              <el-badge v-if="stats.pending_entities > 0"
                :value="stats.pending_entities" style="margin-left:8px" />
            </el-button>
            <el-button style="width:100%;justify-content:flex-start"
              @click="router.push('/admin/users')">用户管理</el-button>
            <el-button style="width:100%;justify-content:flex-start"
              @click="router.push('/admin/knowledge')">知识库管理</el-button>
            <el-button style="width:100%;justify-content:flex-start"
              @click="router.push('/admin/config')">系统配置</el-button>
          </el-space>
        </el-card>
      </el-col>

      <el-col :span="12">
        <el-card>
          <template #header>系统状态</template>
          <el-descriptions :column="1" size="small" border>
            <el-descriptions-item label="知识库初始化">
              <el-tag :type="initStatus?.init_completed ? 'success' : 'warning'">
                {{ initStatus?.init_completed ? '已完成' : '未完成' }}
              </el-tag>
            </el-descriptions-item>
            <el-descriptions-item label="总文档数">
              {{ stats.total_documents || 0 }} 份
            </el-descriptions-item>
            <el-descriptions-item label="总知识点数">
              {{ (stats.approved_entities || 0) + (stats.pending_entities || 0) }} 个
            </el-descriptions-item>
          </el-descriptions>
        </el-card>
      </el-col>
    </el-row>

    <!-- 运维摘要 -->
    <el-row :gutter="16" style="margin-top:20px">
      <el-col :span="12">
        <el-card class="ops-card" shadow="hover">
          <template #header>
            <div class="ops-card-header">
              <span>管线状态</span>
              <el-tag :type="pipelineHealth.tagType" size="small" effect="dark">
                {{ pipelineHealth.statusText }}
              </el-tag>
            </div>
          </template>
          <div class="ops-card-body">
            <div class="ops-metric" v-if="pipelineHealth.totalDocs > 0">
              <span class="ops-metric-label">文档总数</span>
              <span class="ops-metric-value">{{ pipelineHealth.totalDocs }}</span>
            </div>
            <div class="ops-metric" :class="{ 'ops-metric--warn': pipelineHealth.stuckDocs > 0 }">
              <span class="ops-metric-label">卡住</span>
              <span class="ops-metric-value">{{ pipelineHealth.stuckDocs }}</span>
            </div>
            <div class="ops-metric" :class="{ 'ops-metric--danger': pipelineHealth.failedDocs > 0 }">
              <span class="ops-metric-label">失败</span>
              <span class="ops-metric-value">{{ pipelineHealth.failedDocs }}</span>
            </div>
            <div v-if="pipelineHealth.totalDocs === 0" class="ops-metric--empty">
              暂无文档处理管线数据
            </div>
          </div>
          <div class="ops-card-footer">
            <el-button size="small" text type="primary" @click="router.push('/admin/system-health')">
              查看系统监控
            </el-button>
          </div>
        </el-card>
      </el-col>

      <el-col :span="12">
        <el-card class="ops-card" shadow="hover">
          <template #header>
            <div class="ops-card-header">
              <span>任务状态</span>
              <el-tag :type="taskHealth.tagType" size="small" effect="dark">
                {{ taskHealth.statusText }}
              </el-tag>
            </div>
          </template>
          <div class="ops-card-body">
            <div class="ops-metric">
              <span class="ops-metric-label">24h内成功</span>
              <span class="ops-metric-value ops-metric--success">{{ taskHealth.succeeded24h }}</span>
            </div>
            <div class="ops-metric" :class="{ 'ops-metric--warn': taskHealth.needsReview > 0 }">
              <span class="ops-metric-label">需人工处理</span>
              <span class="ops-metric-value">{{ taskHealth.needsReview }}</span>
            </div>
            <div class="ops-metric" :class="{ 'ops-metric--danger': taskHealth.failed > 0 }">
              <span class="ops-metric-label">最终失败</span>
              <span class="ops-metric-value">{{ taskHealth.failed }}</span>
            </div>
          </div>
          <div class="ops-card-footer">
            <el-button size="small" text type="primary" @click="router.push('/admin/tasks')">
              查看任务管理
            </el-button>
          </div>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { adminApi } from '@/api'

const router     = useRouter()
const stats      = ref<any>({})
const initStatus = ref<any>(null)
const seeding    = ref(false)
const prebuilding = ref(false)

// 运维摘要数据
const pipelineHealth = reactive({
  totalDocs: 0,
  stuckDocs: 0,
  failedDocs: 0,
  statusText: '加载中…',
  tagType: 'info' as 'success' | 'warning' | 'danger' | 'info',
})

const taskHealth = reactive({
  succeeded24h: 0,
  needsReview: 0,
  failed: 0,
  statusText: '加载中…',
  tagType: 'info' as 'success' | 'warning' | 'danger' | 'info',
})

async function load() {
  try {
    const [statsRes, initRes]: any[] = await Promise.all([
      adminApi.getStats(),
      adminApi.getInitStatus(),
    ])
    stats.value      = statsRes.data || {}
    initStatus.value = initRes.data || {}
  } catch { /* 静默降级 */ }

  // 并行加载管线 + 任务摘要
  loadOpsSummary()
}

async function loadOpsSummary() {
  // 管线状态
  try {
    const pipeRes: any = await adminApi.getPipelineStatus()
    const data = pipeRes?.data || {}
    const byStatus = data.documents_by_status || {}
    pipelineHealth.totalDocs = Object.values(byStatus).reduce((a: number, b: any) => a + (b as number), 0) as number
    pipelineHealth.stuckDocs = (data.stuck_documents || []).length
    pipelineHealth.failedDocs = byStatus.failed || 0

    if (pipelineHealth.stuckDocs > 0 || pipelineHealth.failedDocs > 0) {
      pipelineHealth.statusText = '需关注'
      pipelineHealth.tagType = pipelineHealth.stuckDocs > 0 ? 'warning' : 'danger'
    } else if (pipelineHealth.totalDocs > 0) {
      pipelineHealth.statusText = '运行正常'
      pipelineHealth.tagType = 'success'
    } else {
      pipelineHealth.statusText = '暂无数据'
      pipelineHealth.tagType = 'info'
    }
  } catch {
    pipelineHealth.statusText = '获取失败'
    pipelineHealth.tagType = 'danger'
  }

  // 任务状态
  try {
    const taskRes: any = await adminApi.getTaskStats()
    const data = taskRes?.data || {}
    taskHealth.succeeded24h = data.succeeded_24h || 0
    taskHealth.needsReview = data.needs_review || 0
    taskHealth.failed = data.failed || 0

    if (taskHealth.failed > 0 || taskHealth.needsReview > 0) {
      taskHealth.statusText = '需关注'
      taskHealth.tagType = taskHealth.failed > 0 ? 'danger' : 'warning'
    } else {
      taskHealth.statusText = '运行正常'
      taskHealth.tagType = 'success'
    }
  } catch {
    taskHealth.statusText = '获取失败'
    taskHealth.tagType = 'danger'
  }
}

async function doSeed() {
  seeding.value = true
  try {
    const res: any = await adminApi.seedKnowledge()
    ElMessage.success(res.data?.message || '种子知识库导入完成')
    await load()
  } finally { seeding.value = false }
}

async function doPrebuild() {
  prebuilding.value = true
  try {
    const res: any = await adminApi.prebuildBanks()
    ElMessage.success(res.data?.message || '题库生成任务已触发')
  } finally { prebuilding.value = false }
}

onMounted(load)
</script>

<style scoped>
.page { padding: 8px; }
.stat-card { text-align: center; }
.has-pending { border-color: #f56c6c; }

/* ── 运维摘要卡片 ── */
.ops-card { min-height: 160px; }
.ops-card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.ops-card-body {
  display: flex;
  gap: 24px;
  padding: 4px 0 8px;
}
.ops-metric {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
}
.ops-metric-label {
  font-size: 12px;
  color: #909399;
}
.ops-metric-value {
  font-size: 24px;
  font-weight: 700;
  color: #303133;
}
.ops-metric--warn .ops-metric-value { color: #e6a23c; }
.ops-metric--danger .ops-metric-value { color: #f56c6c; }
.ops-metric--success .ops-metric-value { color: #67c23a; }
.ops-metric--empty {
  width: 100%;
  text-align: center;
  color: #c0c4cc;
  font-size: 13px;
  padding: 12px 0;
}
.ops-card-footer {
  display: flex;
  justify-content: flex-end;
  padding-top: 4px;
  border-top: 1px solid #ebeef5;
}
</style>
