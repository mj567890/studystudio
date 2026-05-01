import { ref, computed } from 'vue'
import { ElMessage } from 'element-plus'
import { blueprintApi } from '@/api'
import type { CalibrationQuestion } from '@/api'

export function useCalibration(onSuccess?: (result: {
  confidenceScore: number
  answeredCount: number
  answers: Record<string, any>
}) => void) {
  const dialogVisible = ref(false)
  const loading = ref(false)
  const submitting = ref(false)
  const questions = ref<CalibrationQuestion[]>([])
  const answers = ref<Record<string, any>>({})
  const completed = ref(false)
  const topicKey = ref('')
  const spaceId = ref('')
  const regenAfterSubmit = ref(false)

  const answeredCount = computed(() => {
    let count = 0
    for (const [, answer] of Object.entries(answers.value)) {
      if (answer === 'skip' || answer === '' || answer === null) continue
      if (Array.isArray(answer) && answer.length === 0) continue
      count++
    }
    return count
  })

  const confidenceScore = computed(() => {
    return Math.min(1.0, answeredCount.value / Math.max(5, questions.value.length || 5))
  })

  const confidenceTag = computed(() => {
    const ratio = answeredCount.value / Math.max(5, questions.value.length || 5)
    if (ratio >= 0.8) return 'success'
    if (ratio >= 0.6) return 'warning'
    return 'danger'
  })

  function open(topic: string, sid: string, regenerate = false) {
    topicKey.value = topic
    spaceId.value = sid
    regenAfterSubmit.value = regenerate
    dialogVisible.value = true
    completed.value = false
    loadQuestions()
  }

  function close() {
    dialogVisible.value = false
  }

  async function loadQuestions() {
    questions.value = []
    answers.value = {}
    loading.value = true
    try {
      const res = await blueprintApi.getCalibrationQuestions(topicKey.value, {
        space_id: spaceId.value,
        selected_proposal_id: '',  // 补答场景无方案 ID
        adjustments: {},
      })
      questions.value = res.data?.questions || []

      // 初始化答案
      for (const q of questions.value) {
        if (q.type === 'multi_select' || q.type === 'ranking') {
          answers.value[q.id] = []
        } else {
          answers.value[q.id] = null
        }
      }
    } catch (e: any) {
      ElMessage.error('生成校准题失败：' + (e?.response?.data?.detail?.msg || '未知错误'))
      questions.value = []
    } finally {
      loading.value = false
    }
  }

  function skipQuestion(qid: string) {
    answers.value[qid] = 'skip'
  }

  function buildCalibrationPayload(): Record<string, any> {
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
    return payload
  }

  async function submit() {
    if (!topicKey.value || !spaceId.value) return
    submitting.value = true
    const payload = buildCalibrationPayload()
    try {
      const res = await blueprintApi.submitCalibration(topicKey.value, {
        space_id: spaceId.value,
        answers: payload,
        regenerate: regenAfterSubmit.value,
      })
      completed.value = true
      const data = res.data
      ElMessage.success(
        regenAfterSubmit.value
          ? '经验校准已保存，课程重建已启动'
          : '经验校准已保存'
      )
      onSuccess?.({
        confidenceScore: data?.confidence_score ?? confidenceScore.value,
        answeredCount: data?.questions_answered ?? answeredCount.value,
        answers: payload,
      })
    } catch (e: any) {
      ElMessage.error(e?.response?.data?.detail?.msg || '保存校准数据失败')
    } finally {
      submitting.value = false
    }
  }

  return {
    dialogVisible,
    loading,
    submitting,
    questions,
    answers,
    completed,
    topicKey,
    spaceId,
    answeredCount,
    confidenceScore,
    confidenceTag,
    regenAfterSubmit,
    open,
    close,
    loadQuestions,
    skipQuestion,
    submit,
  }
}
