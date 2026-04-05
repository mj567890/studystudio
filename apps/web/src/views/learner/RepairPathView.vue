<template>
  <div class="page">
    <el-card>
      <template #header>
        <span>学习路径</span>
        <div style="float:right;display:flex;gap:8px">
          <el-select v-model="topicKey" placeholder="选择主题" size="small"
            style="width:200px" :loading="domainsLoading">
            <el-option v-for="d in domains" :key="d.domain_tag"
              :label="d.domain_tag" :value="d.domain_tag" />
          </el-select>
          <el-button type="primary" size="small" :loading="loading" @click="load">生成路径</el-button>
        </div>
      </template>

      <div v-if="path">
        <el-alert v-if="path.is_truncated" type="info" show-icon :closable="false"
          :title="`路径共 ${path.total_steps} 步，当前显示最基础的 ${path.path_steps?.length} 步`"
          style="margin-bottom:16px" />

        <el-steps direction="vertical" :active="path.path_steps?.length">
          <el-step v-for="(step, idx) in path.path_steps" :key="step.ref_id"
            :title="step.title"
            :description="`第 ${step.step_no} 步 · 深度 ${step.dependency_depth}`" />
        </el-steps>

        <div style="margin-top:24px;text-align:center">
          <el-button type="primary"
            @click="router.push({ path:'/tutorial', query:{ topic: topicKey } })">
            前往教程学习
          </el-button>
          <el-button @click="router.push({ path:'/chat', query:{ topic: topicKey } })">
            向 AI 提问
          </el-button>
        </div>
      </div>
      <el-empty v-else-if="!loading" description="选择主题并点击生成路径" />
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { learnerApi, knowledgeApi } from '@/api'

const router  = useRouter()
const route   = useRoute()
const topicKey = ref((route.query.topic as string) || '')
const loading  = ref(false)
const domainsLoading = ref(false)
const path     = ref<any>(null)
const domains  = ref<any[]>([])

async function load() {
  if (!topicKey.value) return
  loading.value = true
  try {
    const res: any = await learnerApi.getRepairPath(topicKey.value)
    path.value = res.data
  } finally { loading.value = false }
}

onMounted(async () => {
  domainsLoading.value = true
  try {
    const res: any = await knowledgeApi.getDomains()
    domains.value = res.data?.domains || []
  } finally { domainsLoading.value = false }
  if (topicKey.value) load()
})
</script>
<style scoped>.page { padding: 8px; }</style>
