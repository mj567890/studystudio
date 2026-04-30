<template>
  <el-dialog
    :model-value="visible"
    :title="`精调章节：${chapter?.title || ''}`"
    width="720px"
    destroy-on-close
    @update:model-value="(v: boolean) => !v && $emit('close')"
  >
    <!-- 版本信息 -->
    <div v-if="detail" class="refine-meta">
      <el-tag size="small" type="info" effect="plain">
        版本 {{ detail.refinement_version }}
      </el-tag>
      <span v-if="detail.refined_at" class="refine-meta-time">
        上次精调：{{ formatTime(detail.refined_at) }}
      </span>
    </div>

    <!-- 套用模板 -->
    <div class="refine-section" v-if="templates.length">
      <div class="refine-label">套用模板</div>
      <el-select
        v-model="selectedTemplateId"
        placeholder="选择已有模板快速填入指令…"
        clearable
        size="small"
        style="width: 100%"
        @change="applyTemplate"
      >
        <el-option
          v-for="t in templates"
          :key="t.template_id"
          :label="t.name"
          :value="t.template_id"
        >
          <span>{{ t.name }}</span>
          <span style="float:right;color:#909399;font-size:12px;margin-left:8px">{{ t.content?.substring(0, 40) }}…</span>
        </el-option>
      </el-select>
    </div>

    <!-- 修改指令 -->
    <div class="refine-section">
      <div class="refine-label">修改指令</div>
      <el-input
        v-model="instruction"
        type="textarea"
        :rows="10"
        placeholder="输入修改指令，AI 将按你的要求重写本章。&#10;&#10;例如：&quot;增加实操案例，弱化理论推导&quot;、&quot;加入航空维修安全规范&quot;、&quot;难度下调，适配中职基础&quot;"
      />
      <!-- 快捷指令 -->
      <div class="refine-presets">
        <el-button
          v-for="p in presets"
          :key="p"
          size="small"
          plain
          @click="fillPreset(p)"
        >{{ p }}</el-button>
      </div>
    </div>

    <!-- 自动联动 -->
    <div class="refine-section">
      <div class="refine-label">自动联动</div>
      <el-checkbox v-model="autoRegenQuiz">重新生成章节测验</el-checkbox>
      <el-checkbox v-model="autoRegenDiscussion" style="margin-left: 16px">重新生成讨论题</el-checkbox>
    </div>

    <!-- 提示 -->
    <el-alert
      type="warning"
      :closable="false"
      show-icon
      style="margin-bottom: 8px"
    >
      <template #title>
        当前内容将被覆盖，精调后可点击"回滚"恢复到上一版本
      </template>
    </el-alert>

    <!-- 底部操作 -->
    <template #footer>
      <div style="display: flex; justify-content: space-between; align-items: center">
        <el-button
          v-if="detail?.has_previous_content"
          type="danger"
          plain
          size="small"
          :loading="rollingBack"
          @click="$emit('rollback')"
        >回滚到上一版本</el-button>
        <span v-else></span>
        <div>
          <el-button @click="$emit('close')">取消</el-button>
          <el-button
            type="primary"
            :loading="submitting"
            :disabled="!instruction.trim()"
            @click="$emit('submit', instruction.trim(), autoRegenQuiz, autoRegenDiscussion)"
          >执行精调</el-button>
        </div>
      </div>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import { adminApi, templateApi } from '@/api'

const props = defineProps<{
  visible: boolean
  chapter: { chapter_id: string; title: string } | null
  submitting: boolean
  rollingBack: boolean
}>()

defineEmits<{
  close: []
  submit: [instruction: string, autoRegenQuiz: boolean, autoRegenDiscussion: boolean]
  rollback: []
}>()

const instruction = ref('')
const autoRegenQuiz = ref(true)
const autoRegenDiscussion = ref(false)
const detail = ref<any>(null)
const templates = ref<any[]>([])
const selectedTemplateId = ref<string | null>(null)

const presets = [
  '增加实操案例',
  '强化理论知识',
  '降低难度',
  '增加代码示例',
  '修正内容错误',
]

function fillPreset(text: string) {
  instruction.value = instruction.value ? instruction.value + '；' + text : text
}

function applyTemplate(templateId: string | null) {
  if (!templateId) return
  const t = templates.value.find((x: any) => x.template_id === templateId)
  if (t) instruction.value = t.content || ''
  selectedTemplateId.value = null
}

function formatTime(iso: string) {
  if (!iso) return ''
  return new Date(iso).toLocaleString('zh-CN')
}

watch(() => [props.visible, props.chapter], async ([vis, ch]) => {
  if (!vis || !ch) {
    instruction.value = ''
    detail.value = null
    return
  }
  // 每次打开时重置表单
  instruction.value = ''
  autoRegenQuiz.value = true
  autoRegenDiscussion.value = false

  // 并行加载章节详情 + 模板列表
  try {
    const [detailRes, tmplRes] = await Promise.all([
      adminApi.getChapterDetail((ch as any).chapter_id),
      templateApi.list(),
    ])
    detail.value = detailRes.data ?? null
    templates.value = tmplRes.data?.templates || []
  } catch {
    detail.value = null
    templates.value = []
  }
})
</script>

<style scoped>
.refine-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
}
.refine-meta-time {
  color: #909399;
  font-size: 12px;
}
.refine-section {
  margin-bottom: 16px;
}
.refine-label {
  font-size: 13px;
  font-weight: 600;
  color: #303133;
  margin-bottom: 6px;
}
.refine-presets {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 8px;
}
</style>
