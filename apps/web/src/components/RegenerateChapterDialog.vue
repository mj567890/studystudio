<template>
  <el-dialog
    :model-value="visible"
    :title="`重新生成章节：${chapter?.title || ''}`"
    width="720px"
    destroy-on-close
    @update:model-value="(v: boolean) => !v && $emit('close')"
  >
    <!-- 模板选择 -->
    <div class="regen-section">
      <div class="regen-label">模板选择</div>
      <el-radio-group v-model="mode" class="regen-radio-group">
        <el-radio value="original">使用课程原模板</el-radio>
        <el-radio value="custom">选择其他模板</el-radio>
      </el-radio-group>
    </div>

    <!-- 模板预览 -->
    <div class="regen-section" v-if="mode === 'original'">
      <div class="regen-label">原模板内容预览</div>
      <el-input
        :model-value="originalTemplatePreview"
        type="textarea"
        :rows="4"
        readonly
        class="regen-preview"
      />
      <div v-if="!originalTemplatePreview" class="regen-muted">无法获取原模板内容，将使用系统默认模板</div>
    </div>

    <div class="regen-section" v-if="mode === 'custom'">
      <div class="regen-label">选择模板</div>
      <el-select
        v-model="selectedTemplateId"
        placeholder="选择模板..."
        size="small"
        style="width: 100%"
        @change="onTemplateSelect"
      >
        <el-option
          v-for="t in templates"
          :key="t.template_id"
          :label="t.name"
          :value="t.template_id"
        >
          <span>{{ t.name }}</span>
          <span style="float:right;color:#909399;font-size:12px;margin-left:8px">{{ t.content?.substring(0, 50) }}…</span>
        </el-option>
      </el-select>
      <div v-if="selectedTemplateContent" class="regen-section" style="margin-top:12px">
        <div class="regen-label">选中模板内容预览</div>
        <el-input
          :model-value="selectedTemplateContentPreview"
          type="textarea"
          :rows="3"
          readonly
          class="regen-preview"
        />
      </div>
    </div>

    <!-- 提示 -->
    <el-alert
      type="info"
      :closable="false"
      show-icon
      style="margin-bottom: 8px"
    >
      <template #title>
        重新生成将完全重写本章内容。所选模板中的【图表要求】和教学约束会自动触发图表生成。
      </template>
    </el-alert>

    <template #footer>
      <el-button @click="$emit('close')">取消</el-button>
      <el-button
        type="primary"
        :loading="submitting"
        @click="$emit('submit', activeInstruction)"
      >执行重新生成</el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { templateApi } from '@/api'

const props = defineProps<{
  visible: boolean
  chapter: { chapter_id: string; title: string } | null
  submitting: boolean
}>()

defineEmits<{
  close: []
  submit: [teacherInstruction: string]
}>()

const mode = ref<'original' | 'custom'>('original')
const templates = ref<any[]>([])
const selectedTemplateId = ref<string | null>(null)
const selectedTemplateContent = ref('')
const originalTemplateContent = ref('')

const originalTemplatePreview = computed(() => {
  if (!originalTemplateContent.value) return ''
  return originalTemplateContent.value.substring(0, 300) + (originalTemplateContent.value.length > 300 ? '…' : '')
})

const selectedTemplateContentPreview = computed(() => {
  if (!selectedTemplateContent.value) return ''
  return selectedTemplateContent.value.substring(0, 300) + (selectedTemplateContent.value.length > 300 ? '…' : '')
})

// 实际传给后端的模板内容
const activeInstruction = computed(() => {
  if (mode.value === 'original') return originalTemplateContent.value
  return selectedTemplateContent.value
})

function onTemplateSelect(templateId: string | null) {
  if (!templateId) {
    selectedTemplateContent.value = ''
    return
  }
  const t = templates.value.find((x: any) => x.template_id === templateId)
  selectedTemplateContent.value = t?.content || ''
}

// 重置状态 + 加载模板列表
watch(() => [props.visible, props.chapter], async ([vis]) => {
  if (!vis) {
    mode.value = 'original'
    selectedTemplateId.value = null
    selectedTemplateContent.value = ''
    originalTemplateContent.value = ''
    return
  }
  try {
    const tmplRes = await templateApi.list()
    const all = tmplRes.data?.templates || []
    templates.value = all
    // 尝试获取原模板：优先 is_system 的"系统默认"
    const sysDefault = all.find((t: any) => t.is_system && t.name === '系统默认')
    originalTemplateContent.value = sysDefault?.content || ''
  } catch {
    templates.value = []
  }
})
</script>

<style scoped>
.regen-section {
  margin-bottom: 16px;
}
.regen-label {
  font-size: 13px;
  font-weight: 600;
  color: #303133;
  margin-bottom: 6px;
}
.regen-radio-group {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.regen-preview {
  opacity: 0.85;
}
.regen-muted {
  color: #909399;
  font-size: 12px;
  margin-top: 4px;
}
</style>
