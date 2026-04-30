import { ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { adminApi } from '@/api'

export interface ChapterForRefine {
  chapter_id: string
  title: string
  refinement_version?: number
  refined_at?: string | null
  has_previous_content?: boolean
}

export function useRefineChapter(onSuccess?: () => void) {
  const dialogVisible = ref(false)
  const refining = ref(false)
  const rollingBack = ref(false)
  const currentChapter = ref<ChapterForRefine | null>(null)

  function open(chapter: ChapterForRefine) {
    currentChapter.value = chapter
    dialogVisible.value = true
  }

  function close() {
    dialogVisible.value = false
    currentChapter.value = null
  }

  async function submit(instruction: string, autoRegenQuiz: boolean, autoRegenDiscussion: boolean) {
    if (!currentChapter.value) return
    refining.value = true
    try {
      await adminApi.refineChapter(currentChapter.value.chapter_id, {
        instruction,
        auto_regenerate_quiz: autoRegenQuiz,
        auto_regenerate_discussion: autoRegenDiscussion,
      })
      ElMessage.success('章节已按你的指令更新')
      dialogVisible.value = false
      currentChapter.value = null
      onSuccess?.()
    } catch (err: any) {
      const msg = err?.response?.data?.detail?.msg || err?.response?.data?.msg || err?.message || '未知错误'
      ElMessage.error('精调失败：' + msg)
      throw err
    } finally {
      refining.value = false
    }
  }

  async function rollback() {
    if (!currentChapter.value) return
    try {
      await ElMessageBox.confirm(
        '确认回滚到精调前的版本？当前内容将被覆盖。',
        '回滚确认',
        { confirmButtonText: '确认回滚', cancelButtonText: '取消', type: 'warning' }
      )
    } catch { return }

    rollingBack.value = true
    try {
      const { data } = await adminApi.rollbackChapter(currentChapter.value.chapter_id)
      ElMessage.success(data?.message || '已回滚到上一版本')
      dialogVisible.value = false
      currentChapter.value = null
      onSuccess?.()
    } catch (err: any) {
      const msg = err?.response?.data?.detail?.msg || err?.response?.data?.msg || err?.message || '未知错误'
      ElMessage.error('回滚失败：' + msg)
    } finally {
      rollingBack.value = false
    }
  }

  return {
    dialogVisible,
    refining,
    rollingBack,
    currentChapter,
    open,
    close,
    submit,
    rollback,
  }
}
