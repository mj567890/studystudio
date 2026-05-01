<template>
  <el-dialog
    :model-value="visible"
    title="经验校准 — 补答 5 道题"
    width="800px"
    destroy-on-close
    :close-on-click-modal="false"
    @update:model-value="(v: boolean) => !v && emit('update:visible', false)"
  >
    <div v-if="loading" style="text-align:center;padding:60px 0">
      <el-icon class="is-loading" :size="32"><Loading /></el-icon>
      <p style="color:#909399;margin-top:12px">AI 正在生成校准题...</p>
    </div>

    <div v-else-if="completed" style="text-align:center;padding:40px 0">
      <el-result
        icon="success"
        title="经验校准完成"
        :sub-title="`已答 ${answeredCount}/${questions.length} 题，置信度 ${(confidenceScore * 100).toFixed(0)}%`"
      >
        <template #extra>
          <el-button type="primary" @click="emit('update:visible', false)">关闭</el-button>
        </template>
      </el-result>
    </div>

    <div v-else-if="!questions.length && !loading" style="text-align:center;padding:40px 0">
      <p style="color:#909399">暂无可用的校准题，请稍后重试</p>
      <el-button style="margin-top:12px" @click="emit('update:visible', false)">关闭</el-button>
    </div>

    <div v-else style="display:flex;gap:20px">
      <!-- 左侧：题目区 -->
      <div style="flex:2;max-height:55vh;overflow-y:auto;padding-right:8px">
        <div style="margin-bottom:14px;padding:10px 14px;background:#ecf5ff;border-radius:8px">
          <p style="margin:0;font-size:13px;color:#409EFF">
            以下 5 道题帮你把一线经验注入课程。每题可跳过，答得越认真课程越接地气。
          </p>
        </div>

        <div
          v-for="(q, qi) in questions"
          :key="q.id"
          style="margin-bottom:16px;padding:14px;background:#fff;border:1px solid #e4e7ed;border-radius:8px"
        >
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
            <strong style="font-size:14px">题 {{ qi + 1 }}/{{ questions.length }}：{{ q.title }}</strong>
            <el-tag size="small" type="info">{{ qi + 1 }}/{{ questions.length }}</el-tag>
          </div>

          <!-- 多选 -->
          <el-checkbox-group
            v-if="q.type === 'multi_select'"
            v-model="answers[q.id]"
            style="display:flex;flex-direction:column;gap:6px"
          >
            <el-checkbox v-for="opt in q.options" :key="opt.id" :label="opt" :value="opt" style="margin-right:0">
              {{ opt.label }}
            </el-checkbox>
          </el-checkbox-group>

          <!-- 单选 -->
          <el-radio-group
            v-else-if="q.type === 'single_select'"
            v-model="answers[q.id]"
            style="display:flex;flex-direction:column;gap:6px"
          >
            <el-radio v-for="opt in q.options" :key="opt.id" :value="opt" style="margin-right:0">
              {{ opt.label }}
            </el-radio>
          </el-radio-group>

          <!-- 排序 -->
          <div v-else-if="q.type === 'ranking'" style="display:flex;flex-direction:column;gap:6px">
            <p style="font-size:12px;color:#909399;margin:2px 0">选择前 5 项（按重要性排序）</p>
            <el-checkbox-group v-model="answers[q.id]" :max="5" style="display:flex;flex-direction:column;gap:6px">
              <el-checkbox v-for="opt in q.options" :key="opt.id" :label="opt" :value="opt" style="margin-right:0">
                {{ opt.label }}
              </el-checkbox>
            </el-checkbox-group>
          </div>

          <!-- 跳过 -->
          <div style="margin-top:8px;padding-top:6px;border-top:1px dashed #e4e7ed">
            <el-button text size="small" type="info" @click="skipQuestion(q.id)">
              {{ q.skip_option || '不清楚 / 跳过' }}
            </el-button>
          </div>

          <!-- 为什么问 -->
          <div style="margin-top:4px;font-size:12px;color:#909399">
            {{ q.why_ask }}
          </div>
        </div>
      </div>

      <!-- 右侧：摘要卡 -->
      <div style="flex:1;min-width:180px">
        <el-card shadow="never" style="background:#fafbfc;position:sticky;top:0">
          <template #header>
            <span style="font-size:14px;font-weight:600">经验摘要</span>
          </template>
          <div v-if="answeredCount === 0" style="color:#909399;font-size:13px;text-align:center;padding:16px 0">
            回答题目后，这里会实时显示你的经验贡献
          </div>
          <div v-else>
            <p style="font-size:13px;color:#606266;margin:6px 0">
              已答 {{ answeredCount }}/{{ questions.length }} 题
            </p>
            <p style="font-size:13px;color:#606266;margin:6px 0">
              置信度：
              <el-tag :type="confidenceTag" size="small">
                {{ (confidenceScore * 100).toFixed(0) }}%
              </el-tag>
            </p>
            <p v-if="answeredCount < 3" style="font-size:12px;color:#e6a23c;margin-top:8px">
              建议至少回答 3 题以获得更好的课程质量
            </p>
            <p v-else style="font-size:12px;color:#67c23a;margin-top:8px">
              经验校准良好，AI 会充分使用你的经验数据
            </p>
          </div>
        </el-card>
      </div>
    </div>

    <template #footer>
      <span v-if="!loading && !completed && questions.length">
        <el-button @click="emit('update:visible', false)">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="submitCalibration">
          {{ regenAfterSubmit ? '保存并重建课程' : '保存校准数据' }}
        </el-button>
      </span>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { watch } from 'vue'
import { Loading } from '@element-plus/icons-vue'
import { useCalibration } from '@/composables/useCalibration'

const props = defineProps<{
  visible: boolean
  topicKey: string
  spaceId: string
  regenAfterSubmit?: boolean
}>()

const emit = defineEmits<{
  (e: 'update:visible', value: boolean): void
  (e: 'done', result: { confidenceScore: number; answeredCount: number; answers: Record<string, any> }): void
}>()

const {
  loading,
  submitting,
  questions,
  answers,
  completed,
  answeredCount,
  confidenceScore,
  confidenceTag,
  skipQuestion,
  submit,
} = useCalibration((result) => {
  emit('done', result)
})

// 当对话框打开时，自动加载题目
watch(() => props.visible, (newVal) => {
  if (newVal && props.topicKey && props.spaceId) {
    // 通过 composable 的 open 方法触发加载
    // open 方法通过 dialogVisible 控制，但这里我们直接用 visible prop
    // 手动触发加载
    loading.value = true
    questions.value = []
    answers.value = {}
    completed.value = false

    import('@/api').then(({ blueprintApi }) => {
      blueprintApi.getCalibrationQuestions(props.topicKey, {
        space_id: props.spaceId,
        selected_proposal_id: '',
        adjustments: {},
      }).then((res: any) => {
        questions.value = res.data?.questions || []
        for (const q of questions.value) {
          if (q.type === 'multi_select' || q.type === 'ranking') {
            answers.value[q.id] = []
          } else {
            answers.value[q.id] = null
          }
        }
      }).catch((e: any) => {
        // silently handle
        questions.value = []
      }).finally(() => {
        loading.value = false
      })
    })
  }
})

// 包装 submit，加入 regenAfterSubmit 参数
async function submitCalibration() {
  // 使用 composable 的 submit，但覆盖 regenAfterSubmit
  // 由于 composable 中 submit 使用的是内部 regenAfterSubmit，这里直接构造 payload
  const { blueprintApi } = await import('@/api')

  const payload: Record<string, any> = {}
  for (const q of questions.value) {
    const answer = answers.value[q.id]
    if (answer === 'skip' || answer === null || answer === undefined) {
      payload[q.id] = q.type === 'multi_select' || q.type === 'ranking' ? [] : 'skip'
    } else if (Array.isArray(answer)) {
      payload[q.id] = answer.map((opt: any) => ({
        id: opt.id,
        label: opt.label,
        entity_id: opt.entity_id || '',
      }))
    } else if (typeof answer === 'object') {
      payload[q.id] = [{
        id: answer.id,
        label: answer.label,
        entity_id: answer.entity_id || '',
      }]
    } else {
      payload[q.id] = 'skip'
    }
  }

  submitting.value = true
  try {
    const res: any = await blueprintApi.submitCalibration(props.topicKey, {
      space_id: props.spaceId,
      answers: payload,
      regenerate: props.regenAfterSubmit ?? false,
    })
    completed.value = true
    const data = res.data
    emit('done', {
      confidenceScore: data?.confidence_score ?? confidenceScore.value,
      answeredCount: data?.questions_answered ?? answeredCount.value,
      answers: payload,
    })
  } catch (e: any) {
    // Error handled by composable's ElMessage
  } finally {
    submitting.value = false
  }
}
</script>
