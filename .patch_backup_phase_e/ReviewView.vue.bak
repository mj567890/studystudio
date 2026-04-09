<template>
  <div class="page">
    <el-card>
      <template #header>
        <div class="header-row">
          <span>知识点审核</span>
          <div class="header-actions">
            <el-tag type="danger" v-if="activeTab === 'pending'">待审核 {{ entities.length }} 个</el-tag>
            <el-tag type="success" v-else-if="activeTab === 'approved'">已通过 {{ entities.length }} 个</el-tag>
            <el-tag v-else>已驳回 {{ entities.length }} 个</el-tag>
            <el-button size="small" @click="load">刷新</el-button>
          </div>
        </div>
      </template>

      <div class="toolbar">
        <el-tabs v-model="activeTab" @tab-change="handleTabChange">
          <el-tab-pane label="待审核" name="pending" />
          <el-tab-pane label="已通过" name="approved" />
          <el-tab-pane label="已驳回" name="rejected" />
        </el-tabs>

        <div class="toolbar-right">
          <el-input
            v-model="domainKeyword"
            size="small"
            clearable
            placeholder="按领域筛选"
            style="width: 180px"
            @keyup.enter="load"
            @clear="load"
          />
          <template v-if="activeTab === 'pending'">
            <el-button size="small" type="success" :disabled="!selectedIds.length" @click="reviewBatch('approve')">
              一键通过
            </el-button>
            <el-button size="small" type="danger" :disabled="!selectedIds.length" @click="reviewBatch('reject')">
              一键驳回
            </el-button>
          </template>
        </div>
      </div>

      <el-empty v-if="!loading && !entities.length" description="当前列表为空" />

      <el-table
        v-else
        :data="entities"
        v-loading="loading"
        size="small"
        @selection-change="onSelectionChange"
      >
        <el-table-column v-if="activeTab === 'pending'" type="selection" width="48" />

        <el-table-column prop="canonical_name" label="知识点名称" min-width="180">
          <template #default="{ row }">
            <el-button link type="primary" @click="openDetail(row)">{{ row.canonical_name }}</el-button>
          </template>
        </el-table-column>

        <el-table-column prop="entity_type" label="类型" width="100">
          <template #default="{ row }">
            <el-tag size="small" :type="typeColor(row.entity_type)">{{ row.entity_type }}</el-tag>
          </template>
        </el-table-column>

        <el-table-column prop="domain_tag" label="领域" width="150" />

        <el-table-column prop="space_type" label="空间" width="90">
          <template #default="{ row }">
            <el-tag size="small" :type="row.space_type === 'personal' ? 'info' : ''">
              {{ row.space_type }}
            </el-tag>
          </template>
        </el-table-column>

        <el-table-column prop="short_definition" label="定义" min-width="260">
          <template #default="{ row }">
            <div class="ellipsis-two">{{ row.short_definition || '—' }}</div>
          </template>
        </el-table-column>

        <el-table-column label="操作" width="260" fixed="right">
          <template #default="{ row }">
            <div class="action-group">
              <el-button size="small" @click="openDetail(row)">查看</el-button>
              <el-button size="small" type="primary" @click="openEdit(row)">编辑</el-button>
              <template v-if="activeTab === 'pending'">
                <el-button type="success" size="small" :loading="row._loading" @click="review(row, 'approve')">通过</el-button>
                <el-button type="danger" size="small" :loading="row._loading" @click="review(row, 'reject')">驳回</el-button>
              </template>
              <template v-else>
                <el-button size="small" :loading="row._loading" @click="moveToPending(row)">退回待审</el-button>
              </template>
            </div>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog v-model="detailVisible" title="知识点详情" width="760px">
      <template v-if="currentRow">
        <div class="detail-grid">
          <div><strong>名称：</strong>{{ currentRow.canonical_name }}</div>
          <div><strong>类型：</strong>{{ currentRow.entity_type }}</div>
          <div><strong>领域：</strong>{{ currentRow.domain_tag }}</div>
          <div><strong>状态：</strong>{{ currentRow.review_status }}</div>
        </div>
        <el-divider />
        <div class="detail-block">
          <div class="detail-title">定义</div>
          <div class="detail-text">{{ currentRow.short_definition || '—' }}</div>
        </div>
        <div class="detail-block">
          <div class="detail-title">详细说明</div>
          <div class="detail-text pre-wrap">{{ currentRow.detailed_explanation || '—' }}</div>
        </div>
      </template>
    </el-dialog>

    <el-dialog v-model="editVisible" title="编辑知识点" width="760px">
      <el-form :model="editForm" label-width="110px">
        <el-form-item label="知识点名称">
          <el-input v-model="editForm.canonical_name" />
        </el-form-item>
        <el-form-item label="类型">
          <el-select v-model="editForm.entity_type" style="width: 100%">
            <el-option v-for="item in entityTypes" :key="item" :label="item" :value="item" />
          </el-select>
        </el-form-item>
        <el-form-item label="领域">
          <el-input v-model="editForm.domain_tag" />
        </el-form-item>
        <el-form-item label="定义">
          <el-input v-model="editForm.short_definition" type="textarea" :rows="3" />
        </el-form-item>
        <el-form-item label="详细说明">
          <el-input v-model="editForm.detailed_explanation" type="textarea" :rows="8" />
        </el-form-item>
        <el-form-item label="状态">
          <el-select v-model="editForm.review_status" style="width: 100%">
            <el-option label="pending" value="pending" />
            <el-option label="approved" value="approved" />
            <el-option label="rejected" value="rejected" />
          </el-select>
        </el-form-item>
        <el-form-item label="核心知识点">
          <el-switch v-model="editForm.is_core" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveEdit">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { reactive, ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { adminApi } from '@/api'

const loading = ref(false)
const saving = ref(false)
const activeTab = ref<'pending' | 'approved' | 'rejected'>('pending')
const domainKeyword = ref('')
const entities = ref<any[]>([])
const selectedIds = ref<string[]>([])
const detailVisible = ref(false)
const editVisible = ref(false)
const currentRow = ref<any>(null)
const entityTypes = ['concept', 'element', 'flow', 'case', 'defense']
const editForm = reactive<any>({
  entity_id: '',
  canonical_name: '',
  entity_type: 'concept',
  domain_tag: '',
  short_definition: '',
  detailed_explanation: '',
  review_status: 'pending',
  is_core: false,
})

const typeColor = (t: string) => ({
  concept: '', element: 'info', flow: 'warning', case: 'danger', defense: 'success'
}[t] || '')

async function load() {
  loading.value = true
  selectedIds.value = []
  try {
    const res: any = await adminApi.listEntities({
      review_status: activeTab.value,
      domain_tag: domainKeyword.value,
      limit: 200,
    })
    entities.value = res.data?.entities || []
  } finally {
    loading.value = false
  }
}

function handleTabChange() {
  load()
}

function onSelectionChange(rows: any[]) {
  selectedIds.value = rows.map(row => row.entity_id)
}

function openDetail(row: any) {
  currentRow.value = { ...row }
  detailVisible.value = true
}

function openEdit(row: any) {
  Object.assign(editForm, {
    entity_id: row.entity_id,
    canonical_name: row.canonical_name || '',
    entity_type: row.entity_type || 'concept',
    domain_tag: row.domain_tag || '',
    short_definition: row.short_definition || '',
    detailed_explanation: row.detailed_explanation || '',
    review_status: row.review_status || 'pending',
    is_core: !!row.is_core,
  })
  editVisible.value = true
}

async function saveEdit() {
  saving.value = true
  try {
    await adminApi.updateEntity({ ...editForm })
    ElMessage.success('已保存')
    editVisible.value = false
    await load()
  } finally {
    saving.value = false
  }
}

async function review(row: any, action: 'approve' | 'reject') {
  row._loading = true
  try {
    await adminApi.reviewEntity({ entity_id: row.entity_id, action })
    ElMessage.success(action === 'approve' ? '已通过' : '已驳回')
    entities.value = entities.value.filter(e => e.entity_id !== row.entity_id)
  } finally {
    row._loading = false
  }
}

async function reviewBatch(action: 'approve' | 'reject') {
  if (!selectedIds.value.length) return
  loading.value = true
  try {
    await adminApi.reviewEntitiesBatch({ entity_ids: selectedIds.value, action })
    ElMessage.success(action === 'approve' ? '批量通过完成' : '批量驳回完成')
    await load()
  } finally {
    loading.value = false
  }
}

async function moveToPending(row: any) {
  row._loading = true
  try {
    await adminApi.updateEntity({
      entity_id: row.entity_id,
      canonical_name: row.canonical_name,
      entity_type: row.entity_type,
      domain_tag: row.domain_tag,
      short_definition: row.short_definition || '',
      detailed_explanation: row.detailed_explanation || '',
      review_status: 'pending',
      is_core: !!row.is_core,
    })
    ElMessage.success('已退回待审核')
    await load()
  } finally {
    row._loading = false
  }
}

onMounted(load)
</script>

<style scoped>
.page { padding: 8px; }
.header-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.header-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}
.toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}
.toolbar-right {
  display: flex;
  align-items: center;
  gap: 8px;
}
.action-group {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.ellipsis-two {
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.detail-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}
.detail-block + .detail-block {
  margin-top: 16px;
}
.detail-title {
  font-weight: 600;
  margin-bottom: 8px;
}
.detail-text {
  line-height: 1.7;
  color: #303133;
}
.pre-wrap {
  white-space: pre-wrap;
}
</style>
