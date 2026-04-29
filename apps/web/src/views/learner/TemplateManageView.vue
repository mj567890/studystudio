<template>
  <div class="page">
    <el-card>
      <template #header>
        <span>课程模板管理</span>
        <el-button type="primary" size="small" style="float:right" @click="startCreate">+ 新建模板</el-button>
      </template>

      <el-table :data="templates" size="small" max-height="600" v-loading="loading">
        <el-table-column prop="name" label="名称" min-width="150">
          <template #default="{ row }">
            <span>{{ row.name }}</span>
            <el-tag v-if="row.is_system" size="small" type="info" style="margin-left:6px">系统</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="content" label="教学指令预览" min-width="400">
          <template #default="{ row }">
            <span style="font-size:12px;color:#606266">{{ row.content.substring(0, 100) }}{{ row.content.length > 100 ? '…' : '' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="200" fixed="right">
          <template #default="{ row }">
            <el-button size="small" text type="info" @click="viewTemplate(row)">查看</el-button>
            <el-button size="small" text type="primary" @click="forkTemplate(row)">以此为基础新建</el-button>
          </template>
        </el-table-column>
      </el-table>

      <el-empty v-if="!loading && !templates.length" description="暂无模板" />
    </el-card>

    <!-- 新建 / 编辑对话框 -->
    <el-dialog
      v-model="showCreate"
      :title="editingTemplate ? '编辑模板' : '新建模板'"
      width="480px"
      :close-on-click-modal="false"
    >
      <el-form :model="form" label-position="top">
        <el-form-item label="模板名称">
          <el-input v-model="form.name" maxlength="100" placeholder="例如：我的安全实操模板" />
        </el-form-item>
        <el-form-item label="教学指令内容">
          <el-input
            v-model="form.content"
            type="textarea"
            :rows="8"
            placeholder="描述你希望 AI 以什么风格和方式生成课程内容..."
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showCreate = false">取消</el-button>
        <el-button type="primary" @click="handleSave" :loading="saving">
          {{ editingTemplate ? '保存' : '创建' }}
        </el-button>
      </template>
    </el-dialog>

    <!-- 查看对话框 -->
    <el-dialog
      v-model="showView"
      :title="viewingTemplate?.name || '查看模板'"
      width="560px"
      :close-on-click-modal="false"
    >
      <div style="max-height:400px;overflow-y:auto;white-space:pre-wrap;font-size:13px;line-height:1.8;color:#303133;background:#f5f7fa;padding:16px;border-radius:6px">
        {{ viewingTemplate?.content }}
      </div>
      <template #footer>
        <el-button @click="showView = false">关闭</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { templateApi } from '@/api'

const templates = ref<any[]>([])
const loading = ref(false)
const showCreate = ref(false)
const showView = ref(false)
const saving = ref(false)
const editingTemplate = ref<any | null>(null)
const viewingTemplate = ref<any | null>(null)
const form = ref({ name: '', content: '' })

function startCreate() {
  editingTemplate.value = null
  form.value = { name: '', content: '' }
  showCreate.value = true
}

function forkTemplate(row: any) {
  editingTemplate.value = null
  form.value = {
    name: '',
    content: row.content,
  }
  showCreate.value = true
}

function viewTemplate(row: any) {
  viewingTemplate.value = row
  showView.value = true
}

async function handleSave() {
  if (!form.value.name.trim() || !form.value.content.trim()) {
    ElMessage.warning('名称和内容不能为空')
    return
  }
  saving.value = true
  try {
    if (editingTemplate.value) {
      const res = await templateApi.update(editingTemplate.value.template_id, {
        name: form.value.name.trim(),
        content: form.value.content.trim(),
      })
      ElMessage.success('模板已更新')
      const idx = templates.value.findIndex(t => t.template_id === editingTemplate.value!.template_id)
      if (idx >= 0) templates.value[idx] = res.data
    } else {
      const res = await templateApi.create({
        name: form.value.name.trim(),
        content: form.value.content.trim(),
      })
      ElMessage.success('模板已创建')
      templates.value.push(res.data)
    }
    showCreate.value = false
    editingTemplate.value = null
    form.value = { name: '', content: '' }
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.msg || '操作失败')
  } finally {
    saving.value = false
  }
}

onMounted(async () => {
  loading.value = true
  try {
    const res = await templateApi.list()
    templates.value = res.data.templates || []
  } catch {
    // silent
  } finally {
    loading.value = false
  }
})
</script>

<style scoped>
.page { padding: 8px; }
</style>
