<template>
  <div class="page">
    <el-tabs type="border-card" v-model="activeTab" @tab-change="onTabChange">

      <!-- ── Tab 1：知识库管理 ── -->
      <el-tab-pane label="知识库管理" name="knowledge">
        <el-card v-loading="loading" shadow="never" style="border:none">
          <template #header>
            <div class="toolbar">
              <span>知识库管理</span>
              <div class="toolbar-actions">
                <el-input
                  v-model="newDomain"
                  size="small"
                  clearable
                  placeholder="输入新领域名，例如 web-security"
                  style="width: 240px"
                  @keyup.enter="createDomain"
                />
                <el-button size="small" type="primary" :loading="creating" @click="createDomain">
                  新建领域
                </el-button>
                <el-button size="small" @click="load">刷新</el-button>
              </div>
            </div>
          </template>

          <el-table :data="domains" size="small">
            <el-table-column prop="domain_tag" label="领域标签" />
            <el-table-column prop="space_type" label="知识空间" width="100">
              <template #default="{ row }">
                <el-tag size="small" :type="row.space_type === 'global' ? 'success' : 'info'">
                  {{ row.space_type }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="entity_count" label="知识点数量" width="120" />
            <el-table-column prop="core_count" label="核心知识点" width="120" />
            <el-table-column label="操作" width="200">
              <template #default="{ row }">
                <el-button size="small" @click="goLearn(row.domain_tag)">学习</el-button>
                <el-button size="small" type="primary" @click="goReview(row.domain_tag)">
                  审核知识点
                </el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-tab-pane>

      <!-- ── Tab 2：课程管理 ── -->
      <el-tab-pane label="课程管理" name="courses">
        <div class="toolbar" style="margin-bottom:12px;display:flex;justify-content:space-between;align-items:center">
          <span></span>
          <el-button size="small" @click="loadCourses">刷新</el-button>
        </div>
        <el-table :data="courses" size="small" stripe v-loading="coursesLoading" style="width:100%">
          <el-table-column label="课程名称" min-width="160">
            <template #default="{ row }">
              <span style="font-weight:600">{{ row.name }}</span>
            </template>
          </el-table-column>
          <el-table-column label="类型" width="70" align="center">
            <template #default="{ row }">
              <el-tag size="small" :type="row.space_type === 'global' ? 'warning' : 'info'" effect="plain">
                {{ row.space_type === 'global' ? '全局' : '个人' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="章节数" width="80" align="center" prop="chapter_count" />
          <el-table-column label="有内容" width="90" align="center">
            <template #default="{ row }">
              <el-tag size="small" :type="row.content_count === row.chapter_count && row.chapter_count > 0 ? 'success' : 'warning'">
                {{ row.content_count }} / {{ row.chapter_count }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="更新时间" min-width="140">
            <template #default="{ row }">
              <span style="font-size:12px;color:#888">{{ row.bp_updated_at ? new Date(row.bp_updated_at).toLocaleString('zh-CN') : '-' }}</span>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="220" align="center">
            <template #default="{ row }">
              <el-button size="small" text type="primary" @click="openCourseDrawer(row)">查看章节</el-button>
              <el-button size="small" text type="warning" @click="regenAll(row)">全量重生成</el-button>
            </template>
          </el-table-column>
        </el-table>

        <!-- 章节抽屉 -->
        <el-drawer v-model="courseDrawerVisible" :title="currentCourse?.name + ' — 章节管理'" size="60%" destroy-on-close>
          <div v-if="courseDrawerLoading" style="text-align:center;padding:40px"><el-icon class="is-loading"><Loading /></el-icon> 加载中…</div>
          <template v-else>
            <div style="margin-bottom:12px;color:#606266;font-size:13px">
              共 {{ totalChapters }} 章，已有内容 {{ totalWithContent }} 章
              <el-tag size="small" :type="totalWithContent === totalChapters ? 'success' : 'warning'" style="margin-left:8px">
                {{ totalChapters > 0 ? Math.round(totalWithContent / totalChapters * 100) : 0 }}%
              </el-tag>
            </div>
            <el-collapse v-model="openStages">
              <el-collapse-item v-for="stage in courseStages" :key="stage.stage_id" :name="stage.stage_id">
                <template #title>
                  <span style="font-weight:600">{{ stage.title }}</span>
                  <el-tag size="small" type="info" style="margin-left:8px">{{ stage.chapters.length }} 章</el-tag>
                  <el-tag size="small" :type="stage.chapters.every((c: any) => c.has_content) ? 'success' : 'warning'" style="margin-left:4px">
                    {{ stage.chapters.filter((c: any) => c.has_content).length }} / {{ stage.chapters.length }} 有内容
                  </el-tag>
                </template>
                <el-table :data="stage.chapters" size="small" stripe>
                  <el-table-column label="#" width="45" align="center" prop="chapter_order" />
                  <el-table-column label="章节标题" min-width="220" prop="title" />
                  <el-table-column label="内容" width="80" align="center">
                    <template #default="{ row }">
                      <el-tag size="small" :type="row.has_content ? 'success' : 'danger'" round>{{ row.has_content ? '有' : '无' }}</el-tag>
                    </template>
                  </el-table-column>
                  <el-table-column label="操作" width="90" align="center">
                    <template #default="{ row }">
                      <el-button size="small" text type="primary"
                        :loading="regeneratingId === row.chapter_id"
                        @click="regenChapter(row)">重生成</el-button>
                    </template>
                  </el-table-column>
                </el-table>
              </el-collapse-item>
            </el-collapse>
          </template>
        </el-drawer>
      </el-tab-pane>

      <!-- ── Tab 3：文档管理 ── -->
      <el-tab-pane label="文档管理" @click.once="loadAllDocs">
        <div style="margin-bottom:12px;display:flex;justify-content:flex-end">
          <el-button size="small" @click="loadAllDocs">刷新</el-button>
        </div>
        <el-table :data="allDocs" size="small" v-loading="docsLoading">
          <el-table-column prop="file_name" label="文件名" min-width="180" show-overflow-tooltip />
          <el-table-column prop="course_names" label="所属课程" min-width="160" show-overflow-tooltip />
          <el-table-column label="状态" width="90">
            <template #default="{ row }">
              <el-tag size="small"
                :type="row.status==='reviewed'?'success':row.status==='parsed'||row.status==='extracted'?'warning':row.status==='error'?'danger':'info'">
                {{ row.status }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="chunk_count" label="段落数" width="80" />
          <el-table-column label="有页码" width="80">
            <template #default="{ row }">
              <el-tag size="small" :type="row.has_page_no ? 'success' : 'info'">
                {{ row.has_page_no ? '是' : '否' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="owner_name" label="上传者" width="100" />
          <el-table-column label="操作" width="120">
            <template #default="{ row }">
              <el-popconfirm
                title="将清除旧段落并重新解析，确认？"
                @confirm="reparseDoc(row.document_id)">
                <template #reference>
                  <el-button size="small" type="warning"
                    :loading="reparsingId === row.document_id">
                    重新解析
                  </el-button>
                </template>
              </el-popconfirm>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

    </el-tabs>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useRouter } from 'vue-router'
import { adminApi, knowledgeApi } from '@/api'
import { Loading } from '@element-plus/icons-vue'
import axios from 'axios'
const _http = axios.create({ baseURL: '/api', timeout: 30000 })
_http.interceptors.request.use((cfg: any) => { const tk = localStorage.getItem('access_token'); if (tk) cfg.headers.Authorization = `Bearer ${tk}`; return cfg })

const router = useRouter()
const loading = ref(false)
const creating = ref(false)
const domains = ref<any[]>([])
const newDomain = ref('')

// ── 课程管理 ──
const courses           = ref<any[]>([])
const coursesLoading    = ref(false)
const courseDrawerVisible = ref(false)
const currentCourse     = ref<any>(null)
const courseStages      = ref<any[]>([])
const courseDrawerLoading = ref(false)
const openStages        = ref<string[]>([])
const regeneratingId    = ref<string | null>(null)
const totalChapters     = computed(() => courseStages.value.reduce((s: number, st: any) => s + st.chapters.length, 0))
const totalWithContent  = computed(() => courseStages.value.reduce((s: number, st: any) => s + st.chapters.filter((c: any) => c.has_content).length, 0))

async function loadCourses() {
  coursesLoading.value = true
  try {
    const { data } = await _http.get('/admin/courses')
    courses.value = data.data?.courses || []
  } catch { ElMessage.error('加载课程列表失败') }
  finally { coursesLoading.value = false }
}

async function openCourseDrawer(course: any) {
  currentCourse.value = course
  courseDrawerVisible.value = true
  courseDrawerLoading.value = true
  courseStages.value = []
  try {
    const { data } = await _http.get(`/admin/courses/${course.blueprint_id}/chapters`)
    courseStages.value = data.data?.stages || []
    openStages.value = courseStages.value.map((s: any) => s.stage_id)
  } catch { ElMessage.error('加载章节失败') }
  finally { courseDrawerLoading.value = false }
}

async function regenChapter(chapter: any) {
  try {
    await ElMessageBox.confirm(`重生成「${chapter.title}」？约需 30-90 秒。`, '确认', { type: 'warning' })
  } catch { return }
  regeneratingId.value = chapter.chapter_id
  try {
    await _http.post(`/admin/courses/chapters/${chapter.chapter_id}/regenerate`, {}, { timeout: 180000 })
    ElMessage.success('重生成成功')
    chapter.has_content = true
  } catch (err: any) {
    ElMessage.error('失败：' + (err?.response?.data?.msg || err?.message || '未知'))
  } finally { regeneratingId.value = null }
}

async function regenAll(course: any) {
  try {
    await ElMessageBox.confirm(`对「${course.name}」全部 ${course.chapter_count} 章触发重生成？`, '确认', { type: 'warning' })
  } catch { return }
  try {
    await _http.post(`/admin/courses/${course.blueprint_id}/regenerate-all`)
    ElMessage.success('已提交后台处理')
  } catch (err: any) {
    ElMessage.error('失败：' + (err?.response?.data?.msg || err?.message || ''))
  }
}

// ── 文档管理 ──
const allDocs      = ref<any[]>([])
const docsLoading  = ref(false)
const reparsingId  = ref<string | null>(null)

async function loadAllDocs() {
  docsLoading.value = true
  try {
    const res: any = await adminApi.getAllDocuments()
    allDocs.value = res.data?.documents || []
  } catch {
    ElMessage.error('加载文档列表失败')
  } finally {
    docsLoading.value = false
  }
}

async function reparseDoc(documentId: string) {
  reparsingId.value = documentId
  try {
    const res: any = await adminApi.reparseDocument(documentId)
    if (res.code === 200) {
      ElMessage.success(`重新解析完成，共 ${res.data?.chunk_count || 0} 个段落`)
      await loadAllDocs()
    } else {
      ElMessage.error(res.msg || '重新解析失败')
    }
  } catch {
    ElMessage.error('重新解析失败，请重试')
  } finally {
    reparsingId.value = null
  }
}

async function load() {
  loading.value = true
  try {
    const res: any = await knowledgeApi.getDomains()
    domains.value = res.data?.domains || []
  } finally {
    loading.value = false
  }
}

async function createDomain() {
  const name = newDomain.value.trim()
  if (!name) {
    ElMessage.warning('请输入领域名')
    return
  }

  creating.value = true
  try {
    await adminApi.createKnowledgeSpace({ name, space_type: 'global' })
    ElMessage.success('领域已创建')
    newDomain.value = ''
    await load()
  } finally {
    creating.value = false
  }
}

function goLearn(domain: string) {
  router.push({ path: '/tutorial', query: { topic: domain } })
}

function goReview(domain: string) {
  router.push('/admin/review')
}

const activeTab = ref(sessionStorage.getItem('adminKnowledgeTab') || 'knowledge')

function onTabChange(tab: string) {
  sessionStorage.setItem('adminKnowledgeTab', tab)
  if (tab === 'courses' && courses.value.length === 0) loadCourses()
  if (tab === 'docs'    && allDocs.value.length === 0)  loadAllDocs()
}

onMounted(() => {
  load()
  loadCourses()
  loadAllDocs()
})
</script>

<style scoped>
.page {
  padding: 8px;
}

.toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.toolbar-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}
</style>
