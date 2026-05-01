import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import { adminApi } from '@/api'

export interface ChapterForRegenerate {
  chapter_id: string
  title: string
}

export function useRegenerateChapter(onSuccess?: () => void) {
  const dialogVisible = ref(false)
  const regenerating = ref(false)
  const currentChapter = ref<ChapterForRegenerate | null>(null)

  function open(chapter: ChapterForRegenerate) {
    currentChapter.value = chapter
    dialogVisible.value = true
  }

  function close() {
    dialogVisible.value = false
    currentChapter.value = null
  }

  async function submit(teacherInstruction: string) {
    if (!currentChapter.value) return
    regenerating.value = true
    try {
      await adminApi.regenerateChapter(
        currentChapter.value.chapter_id,
        teacherInstruction ? { teacher_instruction: teacherInstruction } : undefined
      )
      ElMessage.success('重新生成完成')
      dialogVisible.value = false
      currentChapter.value = null
      onSuccess?.()
    } catch (err: any) {
      const msg = err?.response?.data?.detail?.msg || err?.response?.data?.msg || err?.message || '未知错误'
      ElMessage.error('重新生成失败：' + msg)
      throw err
    } finally {
      regenerating.value = false
    }
  }

  return {
    dialogVisible,
    regenerating,
    currentChapter,
    open,
    close,
    submit,
  }
}
