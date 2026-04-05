<template>
  <div class="page">
    <!-- 系统初始化向导（首次使用） -->
    <el-alert v-if="!initStatus?.init_completed && initStatus?.needs_seed"
      type="warning" show-icon :closable="false" style="margin-bottom:20px">
      <template #title>🚀 系统尚未初始化，请先导入种子知识库</template>
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
              📋 知识点审核
              <el-badge v-if="stats.pending_entities > 0"
                :value="stats.pending_entities" style="margin-left:8px" />
            </el-button>
            <el-button style="width:100%;justify-content:flex-start"
              @click="router.push('/admin/users')">👥 用户管理</el-button>
            <el-button style="width:100%;justify-content:flex-start"
              @click="router.push('/admin/knowledge')">📚 知识库管理</el-button>
            <el-button style="width:100%;justify-content:flex-start"
              @click="router.push('/admin/config')">⚙️ 系统配置</el-button>
          </el-space>
        </el-card>
      </el-col>

      <el-col :span="12">
        <el-card>
          <template #header>系统状态</template>
          <el-descriptions :column="1" size="small" border>
            <el-descriptions-item label="知识库初始化">
              <el-tag :type="initStatus?.init_completed ? 'success' : 'warning'">
                {{ initStatus?.init_completed ? '✅ 已完成' : '⚠️ 未完成' }}
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
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { adminApi } from '@/api'

const router     = useRouter()
const stats      = ref<any>({})
const initStatus = ref<any>(null)
const seeding    = ref(false)
const prebuilding = ref(false)

async function load() {
  try {
    const [statsRes, initRes]: any[] = await Promise.all([
      adminApi.getStats(),
      adminApi.getInitStatus(),
    ])
    stats.value      = statsRes.data || {}
    initStatus.value = initRes.data || {}
  } catch {}
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
</style>
