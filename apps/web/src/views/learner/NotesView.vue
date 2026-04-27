<template>
  <div class="notes-layout">
    <!-- 左侧笔记本侧边栏 -->
    <div class="nb-sidebar">
      <div class="nb-header">
        <span class="nb-title">笔记本</span>
        <el-button link size="small" @click="openCreateNb">＋</el-button>
      </div>
      <div
        class="nb-item"
        :class="{ active: selectedNbId === '' }"
        @click="selectedNbId = ''; loadNotes()"
      >
        <span>📋 全部笔记</span>
        <span class="nb-count">{{ notes.length }}</span>
      </div>
      <div
        class="nb-item"
        :class="{ active: selectedNbId === '__none__' }"
        @click="selectedNbId = '__none__'; loadNotes()"
      >
        <span>📎 未归档</span>
      </div>
      <div
        v-for="nb in notebooks" :key="nb.notebook_id"
        class="nb-item"
        :class="{ active: selectedNbId === nb.notebook_id }"
        @click="selectedNbId = nb.notebook_id; loadNotes()"
      >
        <span class="nb-name">📓 {{ nb.name }}</span>
        <span class="nb-count">{{ nb.note_count }}</span>
        <el-dropdown trigger="click" @click.stop size="small">
          <span class="nb-more" @click.stop>⋯</span>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item @click="renameNb(nb)">重命名</el-dropdown-item>
              <el-dropdown-item @click="deleteNb(nb)" style="color:#f56c6c">删除笔记本</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </div>
    </div>

    <!-- 右侧主区域 -->
    <div class="notes-main">
      <div class="toolbar">
        <span class="page-title">
          {{ selectedNbId === '' ? '全部笔记' : selectedNbId === '__none__' ? '未归档' : currentNbName }}
        </span>
        <el-button
          v-if="dueCount > 0"
          type="warning" size="small"
          style="margin-right:12px"
          @click="startReview"
        >
          🔔 待复习 {{ dueCount }} 条
        </el-button>
        <div class="toolbar-right">
          <el-input
            v-model="keyword" placeholder="搜索笔记…" size="small"
            style="width:180px;margin-right:8px" clearable @input="onSearch"
          />
          <el-button size="small" type="primary" @click="openCreate">＋ 新建笔记</el-button>
        </div>
      </div>

      <!-- 实体过滤提示条 -->
      <div v-if="entityFilter" class="entity-filter-bar">
        <span style="font-size:13px;color:#606266">
          按知识点过滤：<strong>{{ entityFilter.canonical_name }}</strong>
        </span>
        <el-button link size="small" @click="entityFilter = null">清除过滤</el-button>
        <el-button link size="small" type="primary" @click="openEntityNotes(entityFilter)">
          查看此知识点全部笔记 →
        </el-button>
      </div>

      <div v-if="loading" style="text-align:center;padding:60px">
        <el-icon class="is-loading" style="font-size:28px;color:#409eff"><Loading /></el-icon>
      </div>

      <el-empty v-else-if="filteredNotes.length === 0"
        description="暂无笔记" style="margin-top:60px" />

      <div v-else class="notes-grid">
        <div
          v-for="note in filteredNotes" :key="note.note_id"
          class="note-card"
          :class="{ selected: selectedIds.has(note.note_id) }"
          @click="onCardClick(note)"
        >
          <div class="note-card-header">
            <el-checkbox
              :model-value="selectedIds.has(note.note_id)"
              @click.stop
              @change="toggleSelect(note.note_id)"
              style="margin-right:6px"
            />
            <span class="note-title">{{ note.title || '无标题' }}</span>
            <div class="note-actions" @click.stop>
              <el-dropdown trigger="click" size="small">
                <el-button link size="small" style="color:#909399">⋯</el-button>
                <template #dropdown>
                  <el-dropdown-menu>
                    <el-dropdown-item @click="openMoveDialog(note)">移动到笔记本</el-dropdown-item>
                    <el-dropdown-item @click="removeNote(note.note_id)" style="color:#f56c6c">删除</el-dropdown-item>
                  </el-dropdown-menu>
                </template>
              </el-dropdown>
            </div>
          </div>
          <div class="note-preview">{{ preview(note.content) }}</div>
          <div class="note-meta">
            <span v-if="note.chapter_title" class="note-chapter">📖 {{ note.chapter_title }}</span>
            <span v-if="note.source_type === 'ai_chat'" class="note-source">AI</span>
            <span class="note-date">{{ formatDate(note.updated_at) }}</span>
          </div>
          <div v-if="note.tags?.length" class="note-tags">
            <el-tag v-for="tag in note.tags" :key="tag" size="small" effect="plain"
              style="margin:2px">{{ tag }}</el-tag>
          </div>
          <!-- Phase 9.2：关联的知识实体 -->
          <div v-if="note.linked_entities?.length" class="note-entities">
            <el-tooltip
              v-for="ent in note.linked_entities.slice(0, 4)" :key="ent.entity_id"
              :content="ent.short_definition" placement="top" :show-after="300"
            >
              <el-tag
                size="small" type="info" effect="light"
                style="margin:2px;cursor:pointer;max-width:140px;overflow:hidden;text-overflow:ellipsis"
                @click.stop="filterByEntity(ent)"
              >
                📌 {{ ent.canonical_name }}
              </el-tag>
            </el-tooltip>
            <el-tag v-if="note.linked_entities.length > 4" size="small" effect="plain"
              style="margin:2px">+{{ note.linked_entities.length - 4 }}</el-tag>
          </div>
        </div>
      </div>
    </div>

    <!-- 多选操作栏 -->
    <div v-if="selectedIds.size > 0" class="bulk-bar">
      <span>已选 {{ selectedIds.size }} 条</span>
      <el-button size="small" @click="selectedIds.clear()">取消选择</el-button>
      <el-button size="small" type="primary" :loading="merging" @click="doAiMerge">
        ✨ AI 整理成一篇
      </el-button>
    </div>

    <!-- AI 整理预览弹窗 -->
    <el-dialog v-model="mergeDialogVisible" title="AI 整理结果" width="680px" :close-on-click-modal="false">
      <div style="display:flex;flex-direction:column;gap:12px">
        <el-input v-model="mergeResult.title" placeholder="标题" />
        <el-input v-model="mergeResult.content" type="textarea" :rows="14" />
        <el-select v-model="mergeResult.notebook_id" placeholder="保存到笔记本（可选）" clearable style="width:100%">
          <el-option v-for="nb in notebooks" :key="nb.notebook_id" :label="nb.name" :value="nb.notebook_id" />
        </el-select>
      </div>
      <template #footer>
        <el-button @click="mergeDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveMerged">保存笔记</el-button>
      </template>
    </el-dialog>

    <!-- 复习模式弹窗 -->
    <el-dialog
      v-model="reviewVisible"
      title="复习模式"
      width="660px"
      :close-on-click-modal="false"
      :show-close="true"
    >
      <div v-if="reviewNotes.length === 0" style="text-align:center;padding:40px;color:#909399">
        🎉 今日复习完成！
      </div>
      <div v-else>
        <div style="margin-bottom:12px;color:#909399;font-size:13px">
          {{ reviewIndex + 1 }} / {{ reviewNotes.length }}
        </div>
        <div class="review-card">
          <div class="review-title">{{ reviewNotes[reviewIndex]?.title || '无标题' }}</div>
          <div v-if="reviewNotes[reviewIndex]?.chapter_title" class="review-chapter">
            📖 {{ reviewNotes[reviewIndex].chapter_title }}
          </div>
          <div class="review-content" v-show="showContent">
            {{ reviewNotes[reviewIndex]?.content }}
          </div>
          <el-button
            v-if="!showContent"
            style="margin-top:16px;width:100%"
            @click="showContent = true"
          >显示内容</el-button>
        </div>
        <div v-if="showContent" style="display:flex;gap:12px;margin-top:16px;justify-content:center">
          <el-button type="success" @click="markAndNext">✓ 已掌握，下一条</el-button>
          <el-button @click="skipAndNext">跳过</el-button>
        </div>
        <div v-else style="text-align:center;margin-top:8px;color:#c0c4cc;font-size:12px">
          先回忆一下这条笔记的内容…
        </div>
      </div>
    </el-dialog>

    <!-- 新建/编辑笔记弹窗 -->
    <el-dialog v-model="noteDialogVisible" :title="editNote ? '编辑笔记' : '新建笔记'"
      width="640px" :close-on-click-modal="false">
      <div style="display:flex;flex-direction:column;gap:12px">
        <el-input v-model="form.title" placeholder="笔记标题（留空自动生成）" />
        <el-input v-model="form.content" type="textarea" :rows="10" placeholder="笔记内容…" />
        <el-input v-model="tagsInput" placeholder="标签（空格分隔）" />
        <el-select v-model="form.notebook_id" placeholder="选择笔记本（可选）" clearable style="width:100%">
          <el-option v-for="nb in notebooks" :key="nb.notebook_id"
            :label="nb.name" :value="nb.notebook_id" />
        </el-select>
      </div>
      <template #footer>
        <el-button @click="noteDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveNote">保存</el-button>
      </template>
    </el-dialog>

    <!-- Phase 9.2 知识点笔记弹窗 -->
    <el-dialog v-model="entityDialogVisible" :title="`知识点笔记：${entityFilter?.canonical_name || ''}`"
      width="640px" :close-on-click-modal="false">
      <div v-if="entityDetailLoading" style="text-align:center;padding:40px">
        <el-icon class="is-loading" style="font-size:24px;color:#409eff"><Loading /></el-icon>
      </div>
      <el-empty v-else-if="entityNotes.length === 0" description="该知识点暂无关联笔记" />
      <div v-else style="display:flex;flex-direction:column;gap:12px">
        <div v-for="en in entityNotes" :key="en.note_id" class="entity-note-card">
          <div class="entity-note-title">{{ en.title || '无标题' }}</div>
          <div class="entity-note-preview">{{ preview(en.content) }}</div>
          <div class="entity-note-meta">
            <span v-if="en.chapter_title">📖 {{ en.chapter_title }}</span>
            <span>{{ formatDate(en.updated_at) }}</span>
          </div>
        </div>
      </div>
    </el-dialog>

    <!-- 移动笔记弹窗 -->
    <el-dialog v-model="moveDialogVisible" title="移动到笔记本" width="360px">
      <el-select v-model="moveTargetNbId" placeholder="选择笔记本" clearable style="width:100%">
        <el-option v-for="nb in notebooks" :key="nb.notebook_id"
          :label="nb.name" :value="nb.notebook_id" />
      </el-select>
      <template #footer>
        <el-button @click="moveDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="confirmMove">确认移动</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Loading } from '@element-plus/icons-vue'
import { notesApi, notebooksApi, reviewApi } from '@/api'

const notes      = ref<any[]>([])
const notebooks  = ref<any[]>([])
const loading    = ref(false)
const keyword    = ref('')
const selectedNbId = ref('')
let searchTimer: ReturnType<typeof setTimeout> | null = null

const currentNbName = computed(() =>
  notebooks.value.find(nb => nb.notebook_id === selectedNbId.value)?.name || ''
)

// Phase 9.2：知识点过滤与分组
const entityFilter    = ref<any>(null)
const groupByEntity   = ref(false)
const entityNotes     = ref<any[]>([])
const entityDialogVisible = ref(false)
const entityDetailLoading = ref(false)

const filteredNotes = computed(() => {
  let list = notes.value
  if (keyword.value.trim()) {
    const kw = keyword.value.toLowerCase()
    list = list.filter(n =>
      n.title.toLowerCase().includes(kw) || n.content.toLowerCase().includes(kw)
    )
  }
  if (selectedNbId.value === '__none__') {
    list = list.filter(n => !n.notebook_id)
  }
  if (entityFilter.value) {
    list = list.filter(n =>
      (n.linked_entities || []).some((e: any) => e.entity_id === entityFilter.value.entity_id)
    )
  }
  return list
})

function filterByEntity(ent: any) {
  if (entityFilter.value?.entity_id === ent.entity_id) {
    entityFilter.value = null  // 再次点击取消过滤
  } else {
    entityFilter.value = ent
    keyword.value = ''
  }
}

async function openEntityNotes(ent: any) {
  entityFilter.value = ent
  entityDetailLoading.value = true
  entityDialogVisible.value = true
  try {
    const res: any = await notesApi.getByEntity(ent.entity_id)
    entityNotes.value = res.data?.notes || []
  } catch {
    entityNotes.value = []
  } finally {
    entityDetailLoading.value = false
  }
}

// 弹窗状态
const noteDialogVisible = ref(false)
const saving = ref(false)
const editNote = ref<any>(null)
const form = ref({ title: '', content: '', notebook_id: '' })
const tagsInput = ref('')

const selectedIds = ref<Set<string>>(new Set())
const merging = ref(false)
const mergeDialogVisible = ref(false)
const mergeResult = ref({ title: '', content: '', notebook_id: '' })

function toggleSelect(noteId: string) {
  const s = new Set(selectedIds.value)
  s.has(noteId) ? s.delete(noteId) : s.add(noteId)
  selectedIds.value = s
}

function onCardClick(note: any) {
  if (selectedIds.value.size > 0) {
    toggleSelect(note.note_id)
  } else {
    openEdit(note)
  }
}

async function doAiMerge() {
  if (selectedIds.value.size < 2) { ElMessage.warning('请至少选择 2 条笔记'); return }
  merging.value = true
  try {
    const res: any = await notesApi.aiMerge(Array.from(selectedIds.value))
    mergeResult.value = { title: res.data.title, content: res.data.content, notebook_id: '' }
    mergeDialogVisible.value = true
  } catch { ElMessage.error('AI 整理失败，请稍后重试') }
  finally { merging.value = false }
}

async function saveMerged() {
  if (!mergeResult.value.content.trim()) { ElMessage.warning('内容不能为空'); return }
  saving.value = true
  try {
    const res: any = await notesApi.create({
      title: mergeResult.value.title,
      content: mergeResult.value.content,
    })
    if (mergeResult.value.notebook_id) {
      await notebooksApi.moveNote(res.data.note_id, mergeResult.value.notebook_id)
    }
    mergeDialogVisible.value = false
    selectedIds.value = new Set()
    ElMessage.success('已保存为新笔记')
    await Promise.all([loadNotes(), loadNotebooks()])
  } catch { ElMessage.error('保存失败') }
  finally { saving.value = false }
}

const dueCount    = ref(0)
const reviewVisible = ref(false)
const reviewNotes   = ref<any[]>([])
const reviewIndex   = ref(0)
const showContent   = ref(false)

async function loadDueCount() {
  try {
    const res: any = await reviewApi.getDue()
    dueCount.value = res.data?.total_due || 0
  } catch { /* 静默失败 */ }
}

async function startReview() {
  const res: any = await reviewApi.getDue()
  reviewNotes.value = res.data?.notes || []
  reviewIndex.value = 0
  showContent.value = false
  reviewVisible.value = true
}

async function markAndNext() {
  const note = reviewNotes.value[reviewIndex.value]
  if (!note) return
  await reviewApi.markReviewed(note.note_id)
  dueCount.value = Math.max(0, dueCount.value - 1)
  nextReviewNote()
}

function skipAndNext() {
  nextReviewNote()
}

function nextReviewNote() {
  if (reviewIndex.value < reviewNotes.value.length - 1) {
    reviewIndex.value++
    showContent.value = false
  } else {
    reviewNotes.value = []
  }
}

const moveDialogVisible = ref(false)
const moveTargetNote = ref<any>(null)
const moveTargetNbId = ref('')

async function loadNotes() {
  loading.value = true
  try {
    const params: any = {}
    if (selectedNbId.value && selectedNbId.value !== '__none__') {
      params.notebook_id = selectedNbId.value
    }
    const res: any = await notesApi.list(params)
    notes.value = res.data?.notes || []
  } catch { ElMessage.error('加载笔记失败') }
  finally { loading.value = false }
}

async function loadNotebooks() {
  const res: any = await notebooksApi.list()
  notebooks.value = res.data?.notebooks || []
}

function onSearch() {
  if (searchTimer) clearTimeout(searchTimer)
  searchTimer = setTimeout(loadNotes, 400)
}

function preview(content: string) {
  return content.replace(/\n/g, ' ').slice(0, 100) + (content.length > 100 ? '…' : '')
}

function formatDate(iso: string) {
  if (!iso) return ''
  const d = new Date(iso)
  return `${d.getMonth()+1}/${d.getDate()} ${d.getHours()}:${String(d.getMinutes()).padStart(2,'0')}`
}

function openCreate() {
  editNote.value = null
  form.value = { title: '', content: '', notebook_id: selectedNbId.value !== '__none__' ? selectedNbId.value : '' }
  tagsInput.value = ''
  noteDialogVisible.value = true
}

function openEdit(note: any) {
  editNote.value = note
  form.value = { title: note.title, content: note.content, notebook_id: note.notebook_id || '' }
  tagsInput.value = (note.tags || []).join(' ')
  noteDialogVisible.value = true
}

async function saveNote() {
  if (!form.value.content.trim()) { ElMessage.warning('内容不能为空'); return }
  const tags = tagsInput.value.split(/\s+/).filter(Boolean)
  saving.value = true
  try {
    if (editNote.value) {
      await notesApi.update(editNote.value.note_id, {
        title: form.value.title, content: form.value.content, tags
      })
      if (form.value.notebook_id !== (editNote.value.notebook_id || '')) {
        await notebooksApi.moveNote(editNote.value.note_id, form.value.notebook_id || null)
      }
    } else {
      const res: any = await notesApi.create({
        title: form.value.title, content: form.value.content, tags
      })
      if (form.value.notebook_id) {
        await notebooksApi.moveNote(res.data.note_id, form.value.notebook_id)
      }
    }
    ElMessage.success('已保存')
    noteDialogVisible.value = false
    await Promise.all([loadNotes(), loadNotebooks()])
  } catch { ElMessage.error('保存失败') }
  finally { saving.value = false }
}

async function removeNote(noteId: string) {
  try {
    await ElMessageBox.confirm('确认删除这条笔记？', '提示', {
      confirmButtonText: '删除', cancelButtonText: '取消', type: 'warning'
    })
    await notesApi.remove(noteId)
    notes.value = notes.value.filter(n => n.note_id !== noteId)
    await loadNotebooks()
    ElMessage.success('已删除')
  } catch { /* 取消 */ }
}

function openMoveDialog(note: any) {
  moveTargetNote.value = note
  moveTargetNbId.value = note.notebook_id || ''
  moveDialogVisible.value = true
}

async function confirmMove() {
  if (!moveTargetNote.value) return
  await notebooksApi.moveNote(moveTargetNote.value.note_id, moveTargetNbId.value || null)
  moveDialogVisible.value = false
  ElMessage.success('已移动')
  await Promise.all([loadNotes(), loadNotebooks()])
}

// 笔记本操作
async function openCreateNb() {
  try {
    const { value } = await (ElMessageBox as any).prompt('笔记本名称', '新建笔记本', {
      confirmButtonText: '创建', cancelButtonText: '取消',
      inputValidator: (v: string) => v.trim() ? true : '名称不能为空'
    })
    await notebooksApi.create({ name: value.trim() })
    await loadNotebooks()
    ElMessage.success('笔记本已创建')
  } catch { /* 取消 */ }
}

async function renameNb(nb: any) {
  try {
    const { value } = await (ElMessageBox as any).prompt('新名称', '重命名笔记本', {
      confirmButtonText: '确认', cancelButtonText: '取消',
      inputValue: nb.name,
      inputValidator: (v: string) => v.trim() ? true : '名称不能为空'
    })
    await notebooksApi.rename(nb.notebook_id, value.trim())
    await loadNotebooks()
  } catch { /* 取消 */ }
}

async function deleteNb(nb: any) {
  try {
    await ElMessageBox.confirm(
      `删除「${nb.name}」后，笔记本内的笔记将变为未归档状态。确认删除？`, '提示',
      { confirmButtonText: '删除', cancelButtonText: '取消', type: 'warning' }
    )
    await notebooksApi.remove(nb.notebook_id)
    if (selectedNbId.value === nb.notebook_id) selectedNbId.value = ''
    await Promise.all([loadNotebooks(), loadNotes()])
    ElMessage.success('已删除')
  } catch { /* 取消 */ }
}

onMounted(() => Promise.all([loadNotes(), loadNotebooks(), loadDueCount()]))
</script>

<style scoped>
.notes-layout {
  display: flex;
  height: calc(100vh - 64px);
  overflow: hidden;
}
.nb-sidebar {
  width: 200px;
  flex-shrink: 0;
  background: #f7f8fa;
  border-right: 1px solid #e4e7ed;
  display: flex;
  flex-direction: column;
  padding: 12px 0;
  overflow-y: auto;
}
.nb-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 12px 8px;
}
.nb-title { font-weight: 600; font-size: 13px; color: #303133; }
.nb-item {
  display: flex;
  align-items: center;
  padding: 7px 12px;
  cursor: pointer;
  border-radius: 6px;
  margin: 1px 6px;
  font-size: 13px;
  color: #606266;
  gap: 4px;
}
.nb-item:hover { background: #edf2fc; }
.nb-item.active { background: #ecf5ff; color: #409eff; font-weight: 500; }
.nb-name { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.nb-count { font-size: 11px; color: #909399; margin-left: auto; }
.nb-more { padding: 0 4px; color: #909399; }
.notes-main {
  flex: 1;
  overflow-y: auto;
  padding: 16px 20px;
}
.toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 16px;
  flex-wrap: wrap;
  gap: 8px;
}
.page-title { font-size: 18px; font-weight: 600; color: #303133; }
.toolbar-right { display: flex; align-items: center; }
.notes-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 12px;
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
.note-card:hover { border-color: #409eff; box-shadow: 0 2px 12px rgba(64,158,255,.12); }
.note-card-header { display: flex; align-items: flex-start; justify-content: space-between; gap: 8px; }
.note-title {
  font-size: 14px; font-weight: 600; color: #303133;
  flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.note-preview {
  font-size: 13px; color: #606266; line-height: 1.6;
  overflow: hidden; display: -webkit-box;
  -webkit-line-clamp: 3; -webkit-box-orient: vertical;
}
.note-meta { display: flex; align-items: center; gap: 6px; font-size: 12px; color: #909399; flex-wrap: wrap; }
.note-chapter {
  background: #f0f7ff; color: #409eff; padding: 1px 6px; border-radius: 4px;
  max-width: 140px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.note-source { background: #f0f9eb; color: #67c23a; padding: 1px 6px; border-radius: 4px; }
.note-date { margin-left: auto; }
.note-tags { display: flex; flex-wrap: wrap; gap: 2px; }
.review-card {
  background: #f7f8fa;
  border-radius: 10px;
  padding: 20px;
  min-height: 160px;
}
.review-title {
  font-size: 18px;
  font-weight: 600;
  color: #303133;
  margin-bottom: 8px;
}
.review-chapter {
  font-size: 12px;
  color: #409eff;
  margin-bottom: 12px;
}
.review-content {
  font-size: 14px;
  color: #606266;
  line-height: 1.8;
  white-space: pre-wrap;
  max-height: 320px;
  overflow-y: auto;
}
.note-entities { display: flex; flex-wrap: wrap; gap: 2px; }
.note-card.selected { border-color: #409eff; background: #f0f7ff; }
/* Phase 9.2 实体过滤条 */
.entity-filter-bar {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 8px 14px;
  margin-bottom: 12px;
  background: #ecf5ff;
  border-radius: 8px;
  border: 1px solid #d9ecff;
}

/* Phase 9.2 知识点笔记弹窗 */
.entity-note-card {
  background: #f7f8fa;
  border-radius: 8px;
  padding: 12px 14px;
  border: 1px solid #e4e7ed;
}
.entity-note-title {
  font-size: 14px; font-weight: 600; color: #303133; margin-bottom: 6px;
}
.entity-note-preview {
  font-size: 13px; color: #606266; line-height: 1.6;
  overflow: hidden; display: -webkit-box;
  -webkit-line-clamp: 2; -webkit-box-orient: vertical;
}
.entity-note-meta {
  margin-top: 6px; font-size: 12px; color: #909399;
  display: flex; gap: 12px;
}

.bulk-bar {
  position: fixed;
  bottom: 24px;
  left: 50%;
  transform: translateX(-50%);
  background: #fff;
  border: 1px solid #dcdfe6;
  border-radius: 24px;
  padding: 10px 20px;
  display: flex;
  align-items: center;
  gap: 12px;
  box-shadow: 0 4px 16px rgba(0,0,0,.12);
  font-size: 13px;
  z-index: 100;
}
</style>
