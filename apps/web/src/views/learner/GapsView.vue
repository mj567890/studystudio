<template>
  <div class="page">
    <el-card>
      <template #header>
        <span>知识漏洞报告</span>
        <div style="float:right;display:flex;gap:8px">
          <el-select v-model="topicKey" placeholder="选择主题" size="small"
            style="width:200px" :loading="domainsLoading">
            <el-option v-for="d in domains" :key="d.domain_tag"
              :label="`${d.domain_tag}（${d.space_type === 'global' ? '全局' : '私有'}）`"
              :value="d.domain_tag" />
          </el-select>
          <el-button type="primary" size="small" :loading="loading" @click="load">查询</el-button>
        </div>
      </template>

      <div v-if="report" v-loading="loading">
        <el-row :gutter="16" style="margin-bottom:20px">
          <el-col :span="8">
            <el-statistic title="薄弱点" :value="report.weak_points?.length || 0">
              <template #suffix><span style="color:#f56c6c"> 个</span></template>
            </el-statistic>
          </el-col>
          <el-col :span="8">
            <el-statistic title="不确定点" :value="report.uncertain_points?.length || 0">
              <template #suffix><span style="color:#e6a23c"> 个</span></template>
            </el-statistic>
          </el-col>
          <el-col :span="8">
            <el-statistic title="已掌握" :value="report.mastered_points?.length || 0">
              <template #suffix><span style="color:#67c23a"> 个</span></template>
            </el-statistic>
          </el-col>
        </el-row>

        <div style="margin-bottom:16px;text-align:right">
          <el-button type="primary" size="small"
            @click="router.push({ path:'/path', query:{ topic: topicKey } })">
            生成学习路径 →
          </el-button>
        </div>

        <h4 style="color:#f56c6c;margin-bottom:8px">🔴 薄弱点（需重点补习）</h4>
        <el-table :data="report.weak_points" size="small" style="margin-bottom:20px">
          <el-table-column prop="canonical_name" label="知识点" />
          <el-table-column prop="domain_tag" label="领域" width="140" />
          <el-table-column label="掌握度" width="160">
            <template #default="{ row }">
              <el-progress :percentage="Math.round(row.mastery_score*100)"
                status="exception" :stroke-width="6" />
            </template>
          </el-table-column>
        </el-table>

        <h4 style="color:#e6a23c;margin-bottom:8px">🟡 不确定点（需巩固）</h4>
        <el-table :data="report.uncertain_points" size="small">
          <el-table-column prop="canonical_name" label="知识点" />
          <el-table-column prop="domain_tag" label="领域" width="140" />
          <el-table-column label="掌握度" width="160">
            <template #default="{ row }">
              <el-progress :percentage="Math.round(row.mastery_score*100)"
                status="warning" :stroke-width="6" />
            </template>
          </el-table-column>
        </el-table>
      </div>
      <el-empty v-else-if="!loading" description="选择主题并点击查询" />
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
const report   = ref<any>(null)
const domains  = ref<any[]>([])

async function load() {
  if (!topicKey.value) return
  loading.value = true
  try {
    const res: any = await learnerApi.getGaps(topicKey.value)
    report.value = res.data
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
