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
        <el-descriptions-item v-if="impact.entity_count !== undefined" label="知识点">
          {{ impact.entity_count }} 个
        </el-descriptions-item>
        <el-descriptions-item v-if="impact.blueprint_count !== undefined" label="课程蓝图">
          {{ impact.blueprint_count }} 个
        </el-descriptions-item>
        <el-descriptions-item v-if="impact.discussion_posts !== undefined" label="讨论帖">
          {{ impact.discussion_posts }} 条
        </el-descriptions-item>
        <el-descriptions-item v-if="impact.quiz_attempts !== undefined" label="测验记录">
          {{ impact.quiz_attempts }} 条
        </el-descriptions-item>
        <el-descriptions-item v-if="impact.fork_count !== undefined" label="Fork 引用">
          <span :style="impact.fork_count > 0 ? 'color:#e6a23c' : 'color:#67c23a'">
            {{ impact.fork_count }} 个
          </span>
        </el-descriptions-item>
        <el-descriptions-item v-if="impact.learning_records !== undefined" label="学习记录">
          {{ impact.learning_records }} 条
        </el-descriptions-item>
      </el-descriptions>

      <!-- 警告文本 -->
      <el-alert
        v-if="warningText"
        :title="warningText"
        type="warning"
        :closable="false"
        show-icon
        style="margin-bottom:16px"
      />

      <!-- 不可操作提示 -->
      <el-alert
        v-if="blocked"
        :title="blockedReason"
        type="error"
        :closable="false"
        show-icon
        style="margin-bottom:16px"
      />

      <!-- 确认勾选框 -->
      <el-checkbox v-if="!blocked" v-model="confirmed" style="margin-top:4px">
        {{ confirmLabel }}
      </el-checkbox>
    </template>

    <template #footer>
      <el-button @click="$emit('update:visible', false)">取消</el-button>
      <el-button
        v-if="!blocked"
        :type="confirmButtonType"
        :loading="submitting"
        :disabled="!confirmed"
        @click="$emit('confirm')"
      >
        {{ confirmButtonText }}
      </el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'

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

const warningText = computed(() => {
  if (props.type === 'permanent-delete') {
    return '彻底删除后，所有学员的学习进度、掌握度、讨论帖将被永久清除，不可恢复。'
  }
  if (props.type === 'delete-space') {
    return '删除后空间将进入回收站，30 天后自动彻底删除。如有 fork 引用则文档保留。'
  }
  if (props.type === 'set-public') {
    return '设为公开后，所有注册用户均可查看和搜索到此空间的课程内容。你将承担内容合规责任。'
  }
  return ''
})

const confirmLabel = computed(() => {
  if (props.type === 'permanent-delete') return '我已知晓，确认彻底删除此空间及其所有数据'
  if (props.type === 'delete-space') return '我已知晓，确认将此空间移入回收站'
  if (props.type === 'set-public') return '我已知晓公开的风险，确认设为公开'
  return '我已知晓，确认继续'
})

const confirmButtonText = computed(() => {
  if (props.type === 'permanent-delete') return '彻底删除'
  if (props.type === 'delete-space') return '移到回收站'
  return '确认'
})

const confirmButtonType = computed(() => {
  return props.type === 'permanent-delete' || props.type === 'delete-space' ? 'danger' : 'primary'
})
</script>
```

Wait, I need to add the `computed` import. Let me fix this.<｜end▁of▁thinking｜>

<｜DSML｜tool_calls>
<｜DSML｜invoke name="Write">
<｜DSML｜parameter name="content" string="true"><template>
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
        <el-descriptions-item v-if="impact.entity_count !== undefined" label="知识点">
          {{ impact.entity_count }} 个
        </el-descriptions-item>
        <el-descriptions-item v-if="impact.blueprint_count !== undefined" label="课程蓝图">
          {{ impact.blueprint_count }} 个
        </el-descriptions-item>
        <el-descriptions-item v-if="impact.discussion_posts !== undefined" label="讨论帖">
          {{ impact.discussion_posts }} 条
        </el-descriptions-item>
        <el-descriptions-item v-if="impact.quiz_attempts !== undefined" label="测验记录">
          {{ impact.quiz_attempts }} 条
        </el-descriptions-item>
        <el-descriptions-item v-if="impact.fork_count !== undefined" label="Fork 引用">
          <span :style="impact.fork_count > 0 ? 'color:#e6a23c' : 'color:#67c23a'">
            {{ impact.fork_count }} 个
          </span>
        </el-descriptions-item>
        <el-descriptions-item v-if="impact.learning_records !== undefined" label="学习记录">
          {{ impact.learning_records }} 条
        </el-descriptions-item>
      </el-descriptions>

      <!-- 警告文本 -->
      <el-alert
        v-if="warningText"
        :title="warningText"
        type="warning"
        :closable="false"
        show-icon
        style="margin-bottom:16px"
      />

      <!-- 不可操作提示 -->
      <el-alert
        v-if="blocked"
        :title="blockedReason"
        type="error"
        :closable="false"
        show-icon
        style="margin-bottom:16px"
      />

      <!-- 确认勾选框 -->
      <el-checkbox v-if="!blocked" v-model="confirmed" style="margin-top:4px">
        {{ confirmLabel }}
      </el-checkbox>
    </template>

    <template #footer>
      <el-button @click="$emit('update:visible', false)">取消</el-button>
      <el-button
        v-if="!blocked"
        :type="confirmButtonType"
        :loading="submitting"
        :disabled="!confirmed"
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

watch(() => props.visible, (v) => {
  if (v) confirmed.value = false
})

const warningText = computed(() => {
  if (props.type === 'permanent-delete') {
    return '彻底删除后，所有学员的学习进度、掌握度、讨论帖将被永久清除，不可恢复。'
  }
  if (props.type === 'delete-space') {
    return '删除后空间将进入回收站，30 天后自动彻底删除。如有 fork 引用则文档保留。'
  }
  if (props.type === 'set-public') {
    return '设为公开后，所有注册用户均可查看和搜索到此空间的课程内容。你将承担内容合规责任。'
  }
  return ''
})

const confirmLabel = computed(() => {
  if (props.type === 'permanent-delete') return '我已知晓，确认彻底删除此空间及其所有数据'
  if (props.type === 'delete-space') return '我已知晓，确认将此空间移入回收站'
  if (props.type === 'set-public') return '我已知晓公开的风险，确认设为公开'
  return '我已知晓，确认继续'
})

const confirmButtonText = computed(() => {
  if (props.type === 'permanent-delete') return '彻底删除'
  if (props.type === 'delete-space') return '移到回收站'
  return '确认'
})

const confirmButtonType = computed(() => {
  return props.type === 'permanent-delete' || props.type === 'delete-space' ? 'danger' : 'primary'
})
</script>
