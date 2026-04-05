<template>
  <div class="page">
    <el-card>
      <template #header>
        <span>知识点审核</span>
        <el-tag type="danger" style="float:right;margin-top:2px" v-if="entities.length">
          待审核 {{ entities.length }} 个
        </el-tag>
      </template>

      <el-empty v-if="!loading && !entities.length" description="暂无待审核知识点 🎉" />

      <el-table :data="entities" v-loading="loading" size="small">
        <el-table-column prop="canonical_name" label="知识点名称" min-width="140" />
        <el-table-column prop="entity_type" label="类型" width="90">
          <template #default="{ row }">
            <el-tag size="small" :type="typeColor(row.entity_type)">{{ row.entity_type }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="domain_tag" label="领域" width="130" />
        <el-table-column prop="space_type" label="空间" width="80">
          <template #default="{ row }">
            <el-tag size="small" :type="row.space_type === 'personal' ? 'info' : ''">
              {{ row.space_type }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="short_definition" label="定义" show-overflow-tooltip />
        <el-table-column label="操作" width="180" fixed="right">
          <template #default="{ row }">
            <el-button type="success" size="small" :loading="row._loading"
              @click="review(row, 'approve')">✓ 通过</el-button>
            <el-button type="danger" size="small" :loading="row._loading"
              @click="review(row, 'reject')">✗ 驳回</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { adminApi } from '@/api'

const loading  = ref(false)
const entities = ref<any[]>([])

const typeColor = (t: string) => ({
  concept: '', element: 'info', flow: 'warning', case: 'danger', defense: 'success'
}[t] || '')

async function load() {
  loading.value = true
  try {
    const res: any = await adminApi.listPendingEntities()
    entities.value = res.data?.entities || []
  } finally { loading.value = false }
}

async function review(row: any, action: 'approve' | 'reject') {
  row._loading = true
  try {
    await adminApi.reviewEntity({ entity_id: row.entity_id, action })
    ElMessage.success(action === 'approve' ? '已通过' : '已驳回')
    entities.value = entities.value.filter(e => e.entity_id !== row.entity_id)
  } finally { row._loading = false }
}

onMounted(load)
</script>
<style scoped>.page { padding: 8px; }</style>
