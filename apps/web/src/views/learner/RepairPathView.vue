<template>
  <div class="page">
    <el-card>
      <template #header>
        <span>我的学习路径</span>
        <div style="float:right;display:flex;gap:8px;align-items:center">
          <el-select v-model="topicKey" placeholder="选择主题" size="small"
            style="width:200px" :loading="domainsLoading" @change="onTopicChange">
            <el-option v-for="d in domains" :key="d.domain_tag"
              :label="`${d.domain_tag}（${d.space_type === 'global' ? '全局' : '私有'}）`"
              :value="d.domain_tag" />
          </el-select>
          <el-button type="primary" size="small"
            :loading="generating || pathLoading"
            :disabled="!topicKey"
            @click="generate">
            {{ path ? '重新生成' : '生成路径' }}
          </el-button>
        </div>
      </template>

      <!-- Layer 1: 教学指导输入 -->
      <div style="margin-bottom:16px">
        <el-input
          v-model="teacherInstruction"
          type="textarea"
          :rows="2"
          size="small"
          clearable
          placeholder="教学指导（可选）：例如，侧重实操案例、减少理论推导、适配中职学生基础"
          style="font-size:12px" />
        <div style="font-size:11px;color:#909399;margin-top:2px">
          AI 将按照你的教学要求生成课程内容。留空则使用默认风格
        </div>
      </div>

      <!-- 生成中 -->
      <div v-if="generating" style="padding:40px 24px">
        <div style="text-align:center;margin-bottom:20px">
          <el-icon class="is-loading" style="font-size:32px;color:#409eff"><Loading /></el-icon>
          <p style="color:#606266;margin-top:12px;font-size:15px;font-weight:500">{{ generatingMsg }}</p>
        </div>
        <el-progress
          :percentage="Math.round(fakeProgress)"
          :stroke-width="10"
          striped
          striped-flow
          :duration="10"
          style="margin-bottom:12px" />
        <p style="text-align:center;color:#909399;font-size:12px">
          AI 正在生成课程结构，通常需要 1-2 分钟
        </p>
      </div>

      <!-- 路径加载中 -->
      <div v-else-if="pathLoading" style="text-align:center;padding:40px">
        <el-icon class="is-loading" style="font-size:32px"><Loading /></el-icon>
      </div>

      <!-- 有路径 -->
      <div v-else-if="path">
        <el-alert v-if="path.is_truncated" type="info" show-icon :closable="false"
          :title="`路径共 ${path.total_steps} 步，当前显示最基础的 ${path.path_steps?.length} 步`"
          style="margin-bottom:16px" />

        <el-steps direction="vertical" :active="path.path_steps?.length">
          <el-step v-for="(step, idx) in path.path_steps" :key="step.chapter_id || step.ref_id"
            :title="step.title"
            :description="`第 ${idx + 1} 步 · ${step.stage_title || ''} · 预计 ${step.estimated_minutes || 30} 分钟`">
            <template #title>
              <span>{{ step.title }}</span>
              <el-tag v-if="step.priority === 'foundation'" type="danger" size="small" style="margin-left:8px">⭐ 必修</el-tag>
              <el-tag v-else-if="step.priority === 'enrichment'" type="info" size="small" style="margin-left:8px">📖 拓展</el-tag>
            </template>
          </el-step>
        </el-steps>

        <div style="margin-top:24px;text-align:center">
          <el-button type="primary"
            @click="router.push({ path:'/tutorial', query:{ topic: topicKey } })">
            开始学习 →
          </el-button>
          <el-button @click="router.push({ path:'/chat', query:{ topic: topicKey } })">
            向 AI 提问
          </el-button>
        </div>
      </div>

      <!-- 未选主题 -->
      <el-empty v-else-if="!topicKey" description="请先选择一个学习主题" />

      <!-- 选了但无路径 -->
      <el-empty v-else description="该课程暂无学习路径，请先上传资料生成课程" />
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { learnerApi, knowledgeApi, blueprintApi } from '@/api'
import { ElMessage } from 'element-plus'

const router       = useRouter()
const route        = useRoute()
const topicKey     = ref((route.query.topic as string) || localStorage.getItem('last_topic') || '')
const pathLoading  = ref(false)
const domainsLoading = ref(false)
const generating   = ref(false)
const generatingMsg = ref('正在生成蓝图…')
const teacherInstruction = ref('')
const path         = ref<any>(null)
const domains      = ref<any[]>([])
let pollTimer: any = null
let progressTimer: any = null
const fakeProgress = ref(0)

// 加载路径结果
async function loadPath() {
  if (!topicKey.value) return
  pathLoading.value = true
  path.value = null
  try {
    const res: any = await learnerApi.getRepairPath(topicKey.value)
    path.value = res.data?.path_steps?.length ? res.data : null
  } catch {
    path.value = null
  } finally {
    pathLoading.value = false
  }
}

// 轮询蓝图状态
function startPolling() {
  stopPolling()
  const msgs = ['正在分析知识结构…', '正在规划学习阶段…', '正在生成章节内容…', '即将完成，请稍候…']
  let i = 0
  generatingMsg.value = msgs[0]
  fakeProgress.value = 0

  // 模拟进度：每秒增长，最多到95%，完成后跳到100%
  progressTimer = setInterval(() => {
    if (fakeProgress.value < 95) {
      const step = fakeProgress.value < 30 ? 3 : fakeProgress.value < 60 ? 2 : 0.5
      fakeProgress.value = Math.min(95, fakeProgress.value + step)
    }
  }, 1000)

  pollTimer = setInterval(async () => {
    generatingMsg.value = msgs[Math.min(++i, msgs.length - 1)]
    try {
      const res: any = await blueprintApi.getStatus(topicKey.value)
      const status = res.data?.status
      if (status === 'published') {
        fakeProgress.value = 100
        stopPolling()
        generating.value = false
        await loadPath()
      } else if (status === 'failed') {
        stopPolling()
        generating.value = false
        ElMessage.error('蓝图生成失败，请重试')
      }
    } catch { /* 忽略轮询中的网络抖动 */ }
  }, 3000)
}

function stopPolling() {
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null }
  if (progressTimer) { clearInterval(progressTimer); progressTimer = null }
}

// 触发生成
async function generate() {
  if (!topicKey.value) return
  localStorage.setItem('last_topic', topicKey.value)
  generating.value = true
  path.value = null
  try {
    await blueprintApi.generate(topicKey.value, !!path.value, teacherInstruction.value || undefined)
    startPolling()
  } catch {
    generating.value = false
    ElMessage.error('触发失败，请重试')
  }
}

function onTopicChange() {
  path.value = null
  stopPolling()
  generating.value = false
  loadPath()
}

onMounted(async () => {
  domainsLoading.value = true
  try {
    const res: any = await knowledgeApi.getDomains()
    domains.value = res.data?.domains || []
  } finally {
    domainsLoading.value = false
  }
  if (topicKey.value) {
    // 先查蓝图状态，如果正在生成则自动恢复轮询
    try {
      const res: any = await blueprintApi.getStatus(topicKey.value)
      const status = res.data?.status
      if (status === 'generating') {
        generating.value = true
        startPolling()
      } else {
        loadPath()
      }
    } catch {
      loadPath()
    }
  }
})

onUnmounted(() => { stopPolling() })
</script>

<style scoped>
.page { padding: 8px; }
</style>
