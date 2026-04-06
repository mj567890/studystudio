<template>
  <div class="page">
    <el-card v-loading="loading">
      <template #header>
        <div class="toolbar">
          <span>知识库管理</span>
          <div class="toolbar-actions">
            <el-input
              v-model="newDomain"
              size="small"
              clearable
              placeholder="输入新领域名，例如 web-security"
              style="width: 240px"
              @keyup.enter="createDomain"
            />
            <el-button size="small" type="primary" :loading="creating" @click="createDomain">
              新建领域
            </el-button>
            <el-button size="small" @click="load">刷新</el-button>
          </div>
        </div>
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
import { ElMessage } from 'element-plus'
import { useRouter } from 'vue-router'
import { adminApi, knowledgeApi } from '@/api'

const router = useRouter()
const loading = ref(false)
const creating = ref(false)
const domains = ref<any[]>([])
const newDomain = ref('')

async function load() {
  loading.value = true
  try {
    const res: any = await knowledgeApi.getDomains()
    domains.value = res.data?.domains || []
  } finally {
    loading.value = false
  }
}

async function createDomain() {
  const name = newDomain.value.trim()
  if (!name) {
    ElMessage.warning('请输入领域名')
    return
  }

  creating.value = true
  try {
    await adminApi.createKnowledgeSpace({ name, space_type: 'global' })
    ElMessage.success('领域已创建')
    newDomain.value = ''
    await load()
  } finally {
    creating.value = false
  }
}

function goLearn(domain: string) {
  router.push({ path: '/tutorial', query: { topic: domain } })
}

function goReview(domain: string) {
  router.push('/admin/review')
}

onMounted(load)
</script>

<style scoped>
.page {
  padding: 8px;
}

.toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.toolbar-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}
</style>
