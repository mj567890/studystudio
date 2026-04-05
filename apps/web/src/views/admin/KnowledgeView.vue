<template>
  <div class="page">
    <el-card v-loading="loading">
      <template #header>
        <span>知识库管理</span>
        <el-button size="small" style="float:right" @click="load">刷新</el-button>
      </template>

      <el-table :data="domains" size="small">
        <el-table-column prop="domain_tag" label="领域标签" />
        <el-table-column prop="space_type" label="知识空间" width="100">
          <template #default="{ row }">
            <el-tag size="small" :type="row.space_type === 'global' ? 'success' : 'info'">
              {{ row.space_type }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="entity_count" label="知识点数量" width="120" />
        <el-table-column prop="core_count" label="核心知识点" width="120" />
        <el-table-column label="操作" width="200">
          <template #default="{ row }">
            <el-button size="small" @click="goLearn(row.domain_tag)">学习</el-button>
            <el-button size="small" type="primary" @click="goReview(row.domain_tag)">
              审核知识点
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { knowledgeApi } from '@/api'

const router  = useRouter()
const loading = ref(false)
const domains = ref<any[]>([])

async function load() {
  loading.value = true
  try {
    const res: any = await knowledgeApi.getDomains()
    domains.value = res.data?.domains || []
  } finally { loading.value = false }
}

function goLearn(domain: string) {
  router.push({ path: '/tutorial', query: { topic: domain } })
}

function goReview(domain: string) {
  router.push('/admin/review')
}

onMounted(load)
</script>
<style scoped>.page { padding: 8px; }</style>
