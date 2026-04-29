<template>
  <div class="template-selector">
    <div style="display:flex;align-items:center;gap:8px">
      <el-select
        :model-value="modelValue"
        :placeholder="placeholder"
        size="small"
        clearable
        filterable
        style="flex:1"
        @update:model-value="$emit('update:modelValue', $event)"
        @change="onChange"
      >
        <el-option
          v-for="t in templates"
          :key="t.template_id"
          :label="t.name + (t.is_system ? ' [系统]' : '')"
          :value="t.template_id"
        />
      </el-select>
      <el-button size="small" @click="startCreate" title="基于当前模板新建">+</el-button>
    </div>

    <!-- 预览选中的模板内容 -->
    <div
      v-if="selectedTemplate"
      style="font-size:12px;color:#909399;margin-top:4px;line-height:1.5"
    >
      {{ selectedTemplate.content.substring(0, 120) }}{{ selectedTemplate.content.length > 120 ? '…' : '' }}
    </div>

    <!-- 新建/编辑对话框 -->
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

    <!-- 查看模板内容对话框 -->
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
import { ref, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { templateApi } from '@/api'

const props = withDefaults(defineProps<{
  modelValue?: string | null
  placeholder?: string
  defaultTemplateName?: string  // 加载后自动选中指定名称的模板
}>(), {
  placeholder: '选择课程模板（可选）',
})

const emit = defineEmits<{
  'update:modelValue': [value: string | null]
  'select': [content: string]
}>()

const templates = ref<any[]>([])
const showCreate = ref(false)
const showManager = ref(false)
const showView = ref(false)
const saving = ref(false)
const editingTemplate = ref<any | null>(null)
const viewingTemplate = ref<any | null>(null)

const form = ref({ name: '', content: '' })

const selectedTemplate = computed(() =>
  props.modelValue
    ? templates.value.find(t => t.template_id === props.modelValue) || null
    : null
)

function onChange(templateId: string | null) {
  editingTemplate.value = null
  if (templateId) {
    const tmpl = templates.value.find(t => t.template_id === templateId)
    if (tmpl) {
      emit('select', tmpl.content)
    }
  } else {
    emit('select', '')
  }
}

function startCreate() {
  editingTemplate.value = null
  // 以当前选中模板为起点（若有），否则以系统默认模板为起点
  const baseTemplate = selectedTemplate.value
    || templates.value.find(t => t.name === '系统默认' && t.is_system)
  form.value = {
    name: '',
    content: baseTemplate ? baseTemplate.content : '',
  }
  showCreate.value = true
}

function viewFromManager(row: any) {
  viewingTemplate.value = row
  showView.value = true
}

function selectFromManager(row: any) {
  emit('update:modelValue', row.template_id)
  emit('select', row.content)
  showManager.value = false
}

function editFromManager(row: any) {
  editingTemplate.value = row
  form.value.name = row.name
  form.value.content = row.content
  showManager.value = false
  showCreate.value = true
}

async function deleteTemplate(row: any) {
  try {
    await (ElMessageBox as any).confirm(`确定删除模板「${row.name}」？此操作不可撤销。`, '确认删除', {
      confirmButtonText: '删除',
      cancelButtonText: '取消',
      type: 'warning',
    })
  } catch {
    return
  }
  try {
    await templateApi.delete(row.template_id)
    ElMessage.success('模板已删除')
    templates.value = templates.value.filter(t => t.template_id !== row.template_id)
    if (props.modelValue === row.template_id) {
      emit('update:modelValue', null)
      emit('select', '')
    }
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.msg || '删除失败')
  }
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
      const idx = templates.value.findIndex(
        t => t.template_id === editingTemplate.value!.template_id
      )
      if (idx >= 0) templates.value[idx] = res.data
      emit('update:modelValue', editingTemplate.value!.template_id)
      emit('select', form.value.content.trim())
    } else {
      const res = await templateApi.create({
        name: form.value.name.trim(),
        content: form.value.content.trim(),
      })
      ElMessage.success('模板已创建')
      templates.value.push(res.data)
      emit('update:modelValue', res.data.template_id)
      emit('select', form.value.content.trim())
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
  try {
    const res = await templateApi.list()
    templates.value = res.data.templates || []
    // 指定了默认模板名且当前未选中 → 自动选中
    if (props.defaultTemplateName && !props.modelValue) {
      const match = templates.value.find(t => t.name === props.defaultTemplateName)
      if (match) {
        emit('update:modelValue', match.template_id)
        emit('select', match.content)
      }
    }
  } catch {
    // silent
  }
})
</script>
