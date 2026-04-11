<template>
  <div class="notes-page">
    <!-- 顶部工具栏 -->
    <div class="toolbar">
      <span class="page-title">我的笔记</span>
      <div class="toolbar-right">
        <el-input
          v-model="keyword" placeholder="搜索笔记…" size="small"
          style="width:200px;margin-right:8px" clearable
          @input="onSearch"
        />
        <el-select v-model="filterTopic" size="small" style="width:160px;margin-right:8px"
          placeholder="全部主题" clearable @change="loadNotes">
          <el-option v-for="t in topics" :key="t" :label="t" :value="t" />
        </el-select>
        <el-button size="small" type="primary" @click="openCreate">+ 新建笔记</el-button>
      </div>
    </div>

    <!-- 加载中 -->
    <div v-if="loading" style="text-align:center;padding:60px">
      <el-icon class="is-loading" style="font-size:28px;color:#409eff"><Loading /></el-icon>
    </div>

    <!-- 空状态 -->
    <el-empty v-else-if="notes.length === 0"
      description="暂无笔记，在 AI 对话中点「存为笔记」或手动新建"
      style="margin-top:60px"
    />

    <!-- 笔记网格 -->
    <div v-else class="notes-grid">
      <div
        v-for="note in notes" :key="note.note_id"
        class="note-card"
        @click="openEdit(note)"
      >
        <div class="note-card-header">
          <span class="note-title">{{ note.title || '无标题' }}</span>
          <el-button
            link size="small" type="danger"
            @click.stop="removeNote(note.note_id)"
          >删除</el-button>
        </div>
        <div class="note-preview">{{ preview(note.content) }}</div>
        <div class="note-meta">
          <span v-if="note.chapter_title" class="note-chapter">
            📖 {{ note.chapter_title }}
          </span>
          <span v-if="note.source_type === 'ai_chat'" class="note-source">AI</span>
          <span class="note-date">{{ formatDate(note.updated_at) }}</span>
        </div>
        <div v-if="note.tags?.length" class="note-tags">
          <el-tag v-for="tag in note.tags" :key="tag" size="small" effect="plain"
            style="margin:2px">{{ tag }}</el-tag>
        </div>
      </div>
    </div>

    <!-- 新建/编辑弹窗 -->
    <el-dialog
      v-model="dialogVisible"
      :title="editNote ? '编辑笔记' : '新建笔记'"
      width="640px"
      :close-on-click-modal="false"
    >
      <div style="display:flex;flex-direction:column;gap:12px">
        <el-input v-model="form.title" placeholder="笔记标题（留空自动生成）" />
        <el-input
          v-model="form.content"
          type="textarea" :rows="10"
          placeholder="笔记内容…"
        />
        <el-input v-model="tagsInput" placeholder="标签（用空格分隔，如：SQL注入 网络安全）"
          @blur="parseTags" />
      </div>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveNote">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Loading } from '@element-plus/icons-vue'
import { notesApi } from '@/api'

const notes       = ref<any[]>([])
const loading     = ref(false)
const keyword     = ref('')
const filterTopic = ref('')
let searchTimer: ReturnType<typeof setTimeout> | null = null

const topics = computed(() => {
  const set = new Set(notes.value.map(n => n.topic_key).filter(Boolean))
  return Array.from(set)
})

// ── 弹窗状态 ────────────────────────────────────────────────────
const dialogVisible = ref(false)
const saving        = ref(false)
const editNote      = ref<any>(null)
const form          = ref({ title: '', content: '' })
const tagsInput     = ref('')

// ── 数据加载 ─────────────────────────────────────────────────────
async function loadNotes() {
  loading.value = true
  try {
    const res: any = await notesApi.list({
      topic_key: filterTopic.value || undefined,
      keyword:   keyword.value || undefined,
    })
    notes.value = res.data?.notes || []
  } catch {
    ElMessage.error('加载笔记失败')
  } finally {
    loading.value = false
  }
}

function onSearch() {
  if (searchTimer) clearTimeout(searchTimer)
  searchTimer = setTimeout(loadNotes, 400)
}

// ── 工具函数 ─────────────────────────────────────────────────────
function preview(content: string) {
  return content.replace(/\n/g, ' ').slice(0, 100) + (content.length > 100 ? '…' : '')
}

function formatDate(iso: string) {
  if (!iso) return ''
  const d = new Date(iso)
  return `${d.getMonth() + 1}/${d.getDate()} ${d.getHours()}:${String(d.getMinutes()).padStart(2, '0')}`
}

function parseTags() {
  // 空格分隔的标签在保存时处理
}

// ── 新建 / 编辑 ──────────────────────────────────────────────────
function openCreate() {
  editNote.value = null
  form.value     = { title: '', content: '' }
  tagsInput.value = ''
  dialogVisible.value = true
}

function openEdit(note: any) {
  editNote.value  = note
  form.value      = { title: note.title, content: note.content }
  tagsInput.value = (note.tags || []).join(' ')
  dialogVisible.value = true
}

async function saveNote() {
  if (!form.value.content.trim()) {
    ElMessage.warning('内容不能为空')
    return
  }
  const tags = tagsInput.value.split(/\s+/).filter(Boolean)
  saving.value = true
  try {
    if (editNote.value) {
      await notesApi.update(editNote.value.note_id, {
        title:   form.value.title,
        content: form.value.content,
        tags,
      })
      ElMessage.success('已保存')
    } else {
      await notesApi.create({
        title:   form.value.title,
        content: form.value.content,
        tags,
      })
      ElMessage.success('笔记已创建')
    }
    dialogVisible.value = false
    await loadNotes()
  } catch {
    ElMessage.error('保存失败')
  } finally {
    saving.value = false
  }
}

// ── 删除 ─────────────────────────────────────────────────────────
async function removeNote(noteId: string) {
  try {
    await ElMessageBox.confirm('确认删除这条笔记？', '提示', {
      confirmButtonText: '删除', cancelButtonText: '取消', type: 'warning',
    })
    await notesApi.remove(noteId)
    notes.value = notes.value.filter(n => n.note_id !== noteId)
    ElMessage.success('已删除')
  } catch { /* 取消 */ }
}

onMounted(loadNotes)
</script>

<style scoped>
.notes-page {
  padding: 16px;
  max-width: 1100px;
  margin: 0 auto;
}
.toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 20px;
  flex-wrap: wrap;
  gap: 8px;
}
.page-title {
  font-size: 20px;
  font-weight: 600;
  color: #303133;
}
.toolbar-right {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 4px;
}
.notes-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 14px;
}
.note-card {
  background: #fff;
  border: 1px solid #e4e7ed;
  border-radius: 10px;
  padding: 14px 16px;
  cursor: pointer;
  transition: box-shadow .15s, border-color .15s;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.note-card:hover {
  border-color: #409eff;
  box-shadow: 0 2px 12px rgba(64,158,255,.12);
}
.note-card-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 8px;
}
.note-title {
  font-size: 14px;
  font-weight: 600;
  color: #303133;
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.note-preview {
  font-size: 13px;
  color: #606266;
  line-height: 1.6;
  overflow: hidden;
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
}
.note-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: #909399;
  flex-wrap: wrap;
}
.note-chapter {
  background: #f0f7ff;
  color: #409eff;
  padding: 1px 6px;
  border-radius: 4px;
  max-width: 160px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.note-source {
  background: #f0f9eb;
  color: #67c23a;
  padding: 1px 6px;
  border-radius: 4px;
  font-weight: 500;
}
.note-date { margin-left: auto; }
.note-tags { display: flex; flex-wrap: wrap; gap: 2px; }
</style>
