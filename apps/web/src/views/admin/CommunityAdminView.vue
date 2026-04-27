<template>
  <div>
    <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:16px">
      <span style="font-size:15px;color:#606266">
        待审核 <el-badge :value="pendingItems.length" :hidden="pendingItems.length===0" style="margin-left:4px" />
      </span>
      <el-button size="small" @click="load">刷新</el-button>
    </div>

    <div v-if="loading" style="padding:40px 0">
      <el-skeleton :rows="4" animated />
    </div>
    <el-empty v-else-if="pendingItems.length === 0" description="暂无待审核内容" />
    <el-card
      v-else
      v-for="item in pendingItems"
      :key="item.curation_id"
      style="margin-bottom:12px"
    >
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px">
        <span style="font-weight:600;font-size:15px">{{ item.canonical_name }}</span>
        <el-tag size="small" type="info">{{ item.space_name }}</el-tag>
      </div>
      <div style="font-size:12px;color:#999;margin-bottom:4px">{{ item.domain_tag }}</div>
      <div style="font-size:13px;color:#555;margin-bottom:8px">{{ item.short_definition || '暂无定义' }}</div>
      <div v-if="item.note" style="font-size:12px;color:#777;margin-bottom:8px;font-style:italic">
        💬 {{ item.note }}
      </div>
      <div style="margin-bottom:10px">
        <el-tag v-for="tag in item.tags" :key="tag" size="small" style="margin-right:4px">{{ tag }}</el-tag>
      </div>
      <div style="font-size:11px;color:#bbb;margin-bottom:10px">
        提交时间：{{ formatTime(item.curated_at) }}
      </div>
      <div style="display:flex;gap:8px">
        <el-button type="success" size="small" :loading="reviewing===item.curation_id+'approved'"
          @click="review(item.curation_id, 'approved')">批准</el-button>
        <el-button type="danger" size="small" :loading="reviewing===item.curation_id+'rejected'"
          @click="review(item.curation_id, 'rejected')">拒绝</el-button>
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { communityApi } from '@/api'

const pendingItems = ref<any[]>([])
const loading      = ref(false)
const reviewing    = ref('')

async function load() {
  loading.value = true
  try {
    const res = await communityApi.listPending({ limit: 100 })
    pendingItems.value = res.data || []
  } catch {
    ElMessage.error('加载失败')
  } finally {
    loading.value = false
  }
}

async function review(curationId: string, status: 'approved' | 'rejected') {
  reviewing.value = curationId + status
  try {
    await communityApi.review(curationId, status)
    ElMessage.success(status === 'approved' ? '已批准' : '已拒绝')
    pendingItems.value = pendingItems.value.filter(i => i.curation_id !== curationId)
  } catch {
    ElMessage.error('操作失败')
  } finally {
    reviewing.value = ''
  }
}

function formatTime(iso: string) {
  return new Date(iso).toLocaleString('zh-CN')
}

onMounted(load)
</script>
