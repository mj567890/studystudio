<template>
  <el-dialog
    :model-value="visible"
    :title="title"
    width="480px"
    :close-on-click-modal="false"
    @update:model-value="$emit('update:visible', $event)"
  >
    <div v-if="loading" style="text-align:center; padding:20px">
      <el-icon class="is-loading" :size="32"><Loading /></el-icon>
      <p style="margin-top:8px; color:#909399">正在分析影响范围...</p>
    </div>

    <template v-else>
      <!-- 影响范围数据 -->
      <el-descriptions v-if="impact" :column="1" border size="small" style="margin-bottom:16px">
        <el-descriptions-item v-if="impact.member_count !== undefined" label="成员数">
          {{ impact.member_count }} 人
        </el-descriptions-item>
        <el-descriptions-item v-if="impact.document_count !== undefined" label="文档数">
          {{ impact.document_count }} 个
        </el-descriptions-item>
        <el-descriptions-item v-if="impact.entity_count !== undefined" label="知识点数">
          {{ impact.entity_count }} 个
        </el-descriptions-item>
        <el-descriptions-item v-if="impact.discussion_posts !== undefined" label="讨论帖">
          {{ impact.discussion_posts }} 条
        </el-descriptions-item>
        <el-descriptions-item v-if="impact.blueprint_count !== undefined" label="课程蓝图">
          {{ impact.blueprint_count }} 个
        </el-descriptions-item>
        <el-descriptions-item v-if="impact.fork_count !== undefined" label="已被 Fork">
          {{ impact.fork_count }} 次
        </el-descriptions-item>
      </el-descriptions>

      <!-- 警告信息 -->
      <el-alert
        :title="warningTitle"
        :description="warningDescription"
        type="warning"
        show-icon
        :closable="false"
        style="margin-bottom:16px"
      />

      <!-- 确认勾选（仅在需要确认时显示） -->
      <template v-if="requiresConfirmation">
        <el-checkbox v-model="confirmed" style="margin-bottom:12px">
          {{ confirmationText }}
        </el-checkbox>
      </template>

      <!-- 拒绝原因（空间被 fork 等） -->
      <el-alert
        v-if="blocked"
        :title="blockedReason"
        type="error"
        show-icon
        :closable="false"
        style="margin-bottom:12px"
      />
    </template>

    <template #footer>
      <el-button @click="$emit('update:visible', false)">取消</el-button>
      <el-button
        :type="confirmButtonType"
        :disabled="!canConfirm"
        :loading="submitting"
        @click="$emit('confirm')"
      >
        {{ confirmButtonText }}
      </el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'

const props = defineProps<{
  visible: boolean
  title: string
  type: 'delete-space' | 'permanent-delete' | 'set-public' | 'delete-chapter'
  impact: Record<string, any> | null
  loading: boolean
  submitting: boolean
  blocked: boolean
  blockedReason: string
}>()

defineEmits<{
  'update:visible': [value: boolean]
  confirm: []
}>()

const confirmed = ref(false)

// 每次打开弹窗重置勾选
watch(() => props.visible, (v) => {
  if (v) confirmed.value = false
})

const requiresConfirmation = computed(() => {
  return ['permanent-delete', 'set-public'].includes(props.type)
})

const confirmationText = computed(() => {
  if (props.type === 'permanent-delete') {
    return '我已阅读并理解上述风险，确认要彻底删除此空间，此操作不可逆。'
  }
  if (props.type === 'set-public') {
    return '我已阅读并理解：公开课程后，上传的文档将共享给 Fork 用户；被 Fork 后无法强制删除已共享的文档；因主动公开导致的内容扩散，系统不承担责任。'
  }
  return '我已阅读并理解'
})

const canConfirm = computed(() => {
  if (props.blocked) return false
  if (props.submitting) return false
  if (requiresConfirmation.value && !confirmed.value) return false
  return true
})

const confirmButtonText = computed(() => {
  if (props.type === 'permanent-delete') return '确认彻底删除'
  if (props.type === 'set-public') return '确认公开'
  if (props.type === 'delete-chapter') return '确认删除章节'
  return '移入回收站'
})

const confirmButtonType = computed(() => {
  if (props.type === 'set-public') return 'success'
  return 'danger'
})

const warningTitle = computed(() => {
  if (props.type === 'set-public') return '公开课程须知'
  if (props.type === 'permanent-delete') return '彻底删除警告'
  return '删除确认'
})

const warningDescription = computed(() => {
  if (props.impact?.warning_text) return props.impact.warning_text
  if (props.type === 'permanent-delete') {
    return '彻底删除后，所有学员的学习进度、掌握度、讨论帖、测验成绩将被永久清除，此操作不可逆。'
  }
  if (props.type === 'delete-space') {
    return '空间将移入回收站，30 天后自动清理。在此期间可以随时还原。'
  }
  return ''
})
</script>
