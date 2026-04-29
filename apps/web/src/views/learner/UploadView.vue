<template>
  <div class="page">
    <el-row :gutter="16">
      <el-col :span="12">
        <el-card>
          <template #header>上传学习资料</template>

          <el-upload
            drag
            :auto-upload="false"
            :on-change="handleChange"
            :on-remove="handleRemove"
            :file-list="fileList"
            accept=".pdf,.docx,.md,.txt"
            class="uploader"
          >
            <el-icon style="font-size:48px;color:#c0c4cc"><UploadFilled /></el-icon>
            <p style="margin:12px 0 4px;font-size:15px">拖拽文件到此处，或点击选择</p>
            <p style="color:#909399;font-size:13px">支持 PDF、Word、Markdown、TXT，最大 100MB</p>
          </el-upload>

          <div class="section-block">
            <!-- simplified_form_v1 -->
            <p class="field-label">添加到已有课程（可选）</p>
            <el-select
              v-model="selectedExistingDomain"
              placeholder="可选已有领域"
              filterable
              clearable
              style="width:100%"
              :loading="domainsLoading"
            >
              <el-option
                v-for="d in visibleDomains"
                :key="`${d.space_type}-${d.domain_tag}`"
                :label="`${d.domain_tag}（${d.entity_count}个知识点）`"
                :value="d.domain_tag"
              />
            </el-select>
            <p class="field-hint">已有课程可以继续往里添加资料，也可以在下方新建课程。</p>
          </div>

          <div class="section-block">
            <p class="field-label">新课程名称</p>
            <el-input
              v-model="newDomainName"
              clearable
              maxlength="100"
              show-word-limit
              placeholder="给这批资料起个名字，如：Python 入门、考研数学"
            />
          </div>

          <div class="section-block">
            <p class="field-label">课程模板 — 按课型分别指定</p>
            <div style="margin-bottom:8px">
              <span style="font-size:12px;color:#909399">原理课</span>
              <TemplateSelector
                v-model="selectedTheoryTemplateId"
                placeholder="概念/原理类章节"
                default-template-name="理论基础"
                @select="onTheorySelect"
              />
            </div>
            <div style="margin-bottom:8px">
              <span style="font-size:12px;color:#909399">任务课</span>
              <TemplateSelector
                v-model="selectedTaskTemplateId"
                placeholder="工具/操作类章节"
                default-template-name="实操导向"
                @select="onTaskSelect"
              />
            </div>
            <div style="margin-bottom:8px">
              <span style="font-size:12px;color:#909399">实战课</span>
              <TemplateSelector
                v-model="selectedProjectTemplateId"
                placeholder="项目/综合类章节"
                default-template-name="系统默认"
                @select="onProjectSelect"
              />
            </div>
            <p class="field-hint">AI 将根据每节课的性质自动选用对应模板。留空则使用默认风格</p>
          </div>

          <el-button
            type="primary"
            size="large"
            :loading="uploading"
            :disabled="!selectedFile || !effectiveDomain"
            style="width:100%;margin-top:20px"
            @click="upload"
          >
            {{ uploading ? '上传中...' : '开始上传' }}
          </el-button>

          <el-alert
            v-if="uploadResult"
            style="margin-top:12px"
            :title="uploadAlertTitle"
            :type="uploadAlertType"
            show-icon
            :closable="false"
          />
          <el-alert
            v-if="uploadResult && !uploadResult.is_duplicate"
            style="margin-top:8px"
            type="success"
            :closable="false"
            show-icon
          >
            <template #title>
              <el-button
                type="primary" size="small" link
                style="margin-left:8px"
                @click="router.push('/spaces')"
              >立即前往 →</el-button>
            </template>
          </el-alert>
        </el-card>
      </el-col>

      <el-col :span="12">
        <el-card>
          <template #header>
            <span>我的上传记录</span>
            <el-button text style="float:right" @click="loadDocs">
              <el-icon><Refresh /></el-icon> 刷新
            </el-button>
          </template>

          <!-- pipeline_steps_v1 -->
          <div style="display:flex;align-items:center;gap:0;margin-bottom:16px;padding:12px 16px;background:#f8f9ff;border-radius:10px;border:1px solid #e0e7ff">
            <div v-for="(step, i) in [
              {icon:'📤', label:'上传'},
              {icon:'✂️', label:'解析'},
              {icon:'🔍', label:'审核'},
              {icon:'🎓', label:'生成课程'}
            ]" :key="i" style="display:flex;align-items:center;flex:1">
              <div style="display:flex;flex-direction:column;align-items:center;gap:3px;flex:1">
                <span style="font-size:18px">{{ step.icon }}</span>
                <span style="font-size:11px;color:#606266;white-space:nowrap">{{ step.label }}</span>
              </div>
              <div v-if="i < 3"
                style="width:24px;height:2px;background:linear-gradient(90deg,#c0c4cc,#dcdfe6);flex-shrink:0;margin-bottom:14px" />
            </div>
          </div>
          <div style="font-size:11px;color:#909399;margin:-10px 0 12px;text-align:center">
            小文件约 5~10 分钟 · 大文件（&gt;5MB）可能需要 30 分钟以上
          </div>

          <el-empty v-if="!docsLoading && !documents.length" description="暂无上传记录" />

          <div v-for="doc in documents" :key="doc.document_id" class="doc-item">
            <div class="doc-info">
              <span class="doc-name">{{ doc.title || doc.file_name }}</span>
              <span class="doc-actions">
                <el-tag size="small" :type="statusType(doc.status)">
                  {{ doc.status_label || statusLabel(doc.status) }}
                </el-tag>
                <el-button link type="primary" size="small"
                  @click="viewDoc(doc)">打开原文</el-button>
                <el-button v-if="doc.status === 'failed'" link type="primary" size="small"
                  @click="retryDoc(doc.document_id)">重试</el-button>
                <el-popconfirm title="确认删除该文档及其知识点？" @confirm="deleteDoc(doc.document_id)">
                  <template #reference>
                    <el-button link type="danger" size="small">删除</el-button>
                  </template>
                </el-popconfirm>
              </span>
            </div>
            <div class="doc-meta">
              <span>{{ doc.file_type?.toUpperCase() }}</span>
              <span style="margin:0 6px">·</span>
              <span>{{ formatSize(doc.file_size) }}</span>
              <template v-if="doc.domain_tag">
                <span style="margin:0 6px">·</span>
                <span>{{ doc.domain_tag }}</span>
              </template>
              <template v-if="doc.chunk_count">
                <span style="margin:0 6px">·</span>
                <span>{{ doc.chunk_count }} 片段</span>
              </template>
              <template v-if="doc.entity_count">
                <span style="margin:0 6px">·</span>
                <span>{{ doc.entity_count }} 个知识点</span>
              </template>
              <el-tooltip v-if="doc.is_truncated" content="文件过大，仅处理了前 500 个片段" placement="top">
                <el-tag size="small" type="warning" style="margin-left:6px">已截断</el-tag>
              </el-tooltip>
            </div>
            <!-- 管线进度条：使用 API 返回的 progress_pct -->
            <div v-if="doc.progress_pct !== undefined && doc.progress_pct < 100 && doc.status !== 'failed'"
              style="margin-top:6px">
              <div style="display:flex;justify-content:space-between;font-size:11px;color:#909399;margin-bottom:3px">
                <span>{{ doc.status_label || statusLabel(doc.status) }}</span>
                <span v-if="doc.eta_minutes !== null && doc.eta_minutes !== undefined">
                  预计还需 {{ doc.eta_minutes }} 分钟
                </span>
                <span v-if="doc.chunk_count">已切分 {{ doc.chunk_count }} 片段</span>
              </div>
              <el-progress :percentage="doc.progress_pct" :stroke-width="4" :show-text="false"
                :status="doc.progress_pct > 80 ? '' : ''"
                striped striped-flow :duration="10"
                :color="doc.progress_pct < 40 ? '#909399' : '#409eff'" />
            </div>
            <!-- 失败文档：显示错误摘要 -->
            <div v-if="doc.status === 'failed' && doc.last_error_summary"
              style="margin-top:6px;padding:6px 10px;background:#fef0f0;border-radius:6px;border:1px solid #fde2e2">
              <span style="font-size:11px;color:#f56c6c">{{ doc.last_error_summary }}</span>
            </div>
            <!-- 已完成 -->
            <div v-if="doc.progress_pct === 100" style="margin-top:6px">
              <el-progress :percentage="100" :stroke-width="4" :show-text="false"
                status="success" />
            </div>
          </div>
        </el-card>
      </el-col>
    </el-row>
  </div>
<!-- 文档阅读抽屉 -->
<el-drawer v-model="drawerVisible" :title="drawerTitle" size="60%" direction="rtl">
  <div v-if="drawerLoading" style="text-align:center;padding:40px">
    <el-icon class="is-loading" style="font-size:32px"><Loading /></el-icon>
    <p style="color:#909399;margin-top:12px">加载中…</p>
  </div>
  <div v-else-if="drawerMode === 'text'" style="padding:0 8px">
    <pre v-if="drawerSuffix === 'txt'"
      style="white-space:pre-wrap;font-size:13px;line-height:1.7;font-family:monospace">{{ drawerContent }}</pre>
    <div v-else v-html="drawerHtml" style="line-height:1.8;font-size:14px" />
  </div>
  <div v-else-if="drawerMode === 'url'" style="text-align:center;padding:40px">
    <p style="color:#606266;margin-bottom:20px">
      {{ drawerSuffix === 'pdf' ? 'PDF 将在新标签页中打开' : '该格式将触发下载' }}
    </p>
    <el-button type="primary" @click="openUrl">打开文件</el-button>
  </div>
  <div v-else-if="drawerError" style="text-align:center;padding:40px;color:#f56c6c">
    {{ drawerError }}
  </div>
</el-drawer>

</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { marked } from 'marked'
import DOMPurify from 'dompurify'
// 安全审计 2026-04-27：DOMPurify 防止用户上传文件内容的 XSS
import { ElMessage } from 'element-plus'
import { fileApi, knowledgeApi, templateApi } from '@/api'
import TemplateSelector from '@/components/TemplateSelector.vue'
import { useAuthStore } from '@/stores/auth'
import { useRouter } from 'vue-router'

const router = useRouter()
const auth = useAuthStore()
const authState = auth as any

const uploading = ref(false)
const drawerVisible = ref(false)
const drawerLoading = ref(false)
const drawerTitle   = ref('')
const drawerMode    = ref('')
const drawerSuffix  = ref('')
const drawerContent = ref('')
const drawerHtml    = ref('')
const drawerUrl     = ref('')
const drawerError   = ref('')
const domainsLoading = ref(false)
const docsLoading = ref(false)
const fileList = ref<any[]>([])
const selectedFile = ref<File | null>(null)
const selectedExistingDomain = ref('')
const newDomainName = ref('')
const spaceType = ref('personal')  // 创建即私人，可见性在空间详情页修改
const uploadResult = ref<any>(null)
const domains = ref<any[]>([])
const selectedTheoryTemplateId = ref<string | null>(null)
const selectedTaskTemplateId = ref<string | null>(null)
const selectedProjectTemplateId = ref<string | null>(null)
const theoryContent = ref('')
const taskContent = ref('')
const projectContent = ref('')
const documents = ref<any[]>([])
let timer: ReturnType<typeof setInterval>

const STATUS_LABELS: Record<string, string> = {
  uploaded:   '⏳ 排队中',
  parsed:     '⏳ 提取知识点中',
  extracting: '🤖 AI 正在提取…',
  extracted:  '⏳ AI 审核知识点中',
  embedding:  '🧬 生成向量中',
  reviewed:   '✅ 知识点已就绪',
  published:  '✅ 已完成',
  failed:     '❌ 处理失败'
}
const STATUS_TYPES: Record<string, string> = {
  uploaded:   'info',
  parsed:     'info',
  extracting: 'warning',
  extracted:  'warning',
  embedding:  'info',
  reviewed:   'success',
  published:  'success',
  failed:     'danger'
}

// visible_domains_fix_v1: 下拉列表显示所有课程，不按 spaceType 过滤
const visibleDomains = computed(() => domains.value)

const effectiveDomain = computed(() => {
  const custom = newDomainName.value.trim()
  if (custom) return custom
  return selectedExistingDomain.value.trim()
})

const uploadAlertTitle = computed(() => {
  if (!uploadResult.value) return ''
  const domain = uploadResult.value.domain_tag || effectiveDomain.value
  if (uploadResult.value.is_duplicate && uploadResult.value.requeued) {
    return `文件内容已存在，已复用原文件并重新投递到领域「${domain}」`
  }
  if (uploadResult.value.is_duplicate) {
    if (uploadResult.value.already_in_space) {
      return `该文件已在领域「${uploadResult.value.already_in_space}」中处理过，无需重复上传`
    }
    if (uploadResult.value.reused_document || uploadResult.value.document_exists) {
      return `文件已存在于领域「${domain}」，无需重复处理`
    }
    return '文件已存在，已自动去重'
  }
  // time_estimate_v1: 根据文件大小估算处理时间
  const sizeMB = (uploadResult.value?.file_size || 0) / (1024 * 1024)
  let estimate = ''
  if (sizeMB < 1) estimate = '约 5~10 分钟'
  else if (sizeMB < 5) estimate = '约 10~20 分钟'
  else if (sizeMB < 20) estimate = '约 20~40 分钟'
  else estimate = '可能需要 1 小时以上'
  return `上传成功！已加入课程「${domain}」，文件 ${sizeMB.toFixed(1)}MB，预计处理时间${estimate}`
})

const uploadAlertType = computed(() =>
  uploadResult.value?.is_duplicate ? 'warning' : 'success'
)

watch(spaceType, () => {
  selectedExistingDomain.value = ''
  uploadResult.value = null
})

function statusLabel(status: string) {
  return STATUS_LABELS[status] || status
}

function statusType(status: string) {
  return STATUS_TYPES[status] || ''
}

function formatSize(bytes: number): string {
  if (!bytes) return '-'
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)}KB`
  return `${(bytes / 1024 / 1024).toFixed(1)}MB`
}

function handleChange(file: any, files: any[]) {
  // auto_domain_v1: 从文件名自动推断课程名
  if (file?.raw?.name && !selectedExistingDomain.value && !newDomainName.value) {
    const name = file.raw.name
      .replace(/\.[^.]+$/, '')      // 去后缀
      .replace(/[-_]/g, ' ')         // 连字符换空格
      .replace(/\s+/g, ' ')
      .trim()
    if (name) newDomainName.value = name
  }
  selectedFile.value = file.raw || null
  fileList.value = files
}

function handleRemove(_file: any, files: any[]) {
  fileList.value = files
  selectedFile.value = files.length ? files[files.length - 1].raw || null : null
}

function onTheorySelect(c: string)   { theoryContent.value = c }
function onTaskSelect(c: string)    { taskContent.value = c }
function onProjectSelect(c: string) { projectContent.value = c }

async function upload() {
  const domain = effectiveDomain.value.trim()
  if (!selectedFile.value || !domain) {
    ElMessage.warning('请先选择文件并填写领域名')
    return
  }

  uploading.value = true
  uploadResult.value = null
  try {
    const res: any = await fileApi.upload(selectedFile.value, spaceType.value, domain)
    uploadResult.value = res.data

    if (res.data?.is_duplicate && res.data?.requeued) {
      ElMessage.success(`已复用原文件并重新投递到课程「${res.data.domain_tag || domain}」`)
    } else if (res.data?.is_duplicate && res.data?.already_in_space) {
      ElMessage.warning(`该文件已在课程「${res.data.already_in_space}」中处理过，无需重复上传`)
    } else if (res.data?.is_duplicate) {
      ElMessage.warning('文件已存在，系统已自动去重')
    } else {
      ElMessage.success('上传完成，系统正在后台解析')
    }

    fileList.value = []
    selectedFile.value = null
    await loadDocs()
    await loadDomains()
    // 设置空间三课型默认模板
    const dom = domains.value.find((d: any) => d.domain_tag === domain)
    if (dom?.space_id) {
      templateApi.setSpaceDefault(
        dom.space_id, null,
        selectedTheoryTemplateId.value,
        selectedTaskTemplateId.value,
        selectedProjectTemplateId.value,
      ).catch(() => {})
    }
    scheduleNext()
  } finally {
    uploading.value = false
  }
}

async function loadDomains() {
  domainsLoading.value = true
  try {
    const res: any = await knowledgeApi.getDomains()
    domains.value = res.data?.domains || []

  } catch {
    // 交给全局拦截器提示
  } finally {
    domainsLoading.value = false
  }
}

async function loadDocs() {
  docsLoading.value = true
  try {
    const res: any = await fileApi.getMyDocuments()
    documents.value = res.data?.documents || []
  } catch {
    // 交给全局拦截器提示
  } finally {
    docsLoading.value = false
  }
}

async function viewDoc(doc: any) {
  drawerVisible.value = true
  drawerLoading.value = true
  drawerTitle.value   = doc.title || doc.file_name || '文档阅读'
  drawerMode.value    = ''
  drawerError.value   = ''
  drawerContent.value = ''
  drawerHtml.value    = ''
  drawerUrl.value     = ''
  try {
    const res: any = await fileApi.viewDocument(doc.document_id)
    const d = res.data
    drawerMode.value   = d.mode
    drawerSuffix.value = d.suffix || ''
    if (d.mode === 'text') {
      drawerContent.value = d.content
      if (d.suffix === 'md') {
        drawerHtml.value = DOMPurify.sanitize(marked.parse(d.content) as string, {
          ALLOWED_TAGS: ['p', 'br', 'strong', 'em', 'u', 's', 'a', 'ul', 'ol', 'li',
                         'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
                         'pre', 'code', 'blockquote', 'table', 'thead', 'tbody', 'tr', 'th', 'td',
                         'span', 'div', 'hr', 'img', 'sup', 'sub'],
          ALLOWED_ATTR: ['href', 'title', 'class', 'id', 'src', 'alt', 'width', 'height', 'target', 'rel'],
        })
      }
      // PDF 直接打开
    } else if (d.mode === 'url' && d.suffix === 'pdf') {
      window.open(d.url, '_blank')
      drawerVisible.value = false
    } else {
      drawerUrl.value = d.url
    }
  } catch {
    drawerError.value = '加载失败，请稍后重试'
  } finally {
    drawerLoading.value = false
  }
}

function openUrl() {
  window.open(drawerUrl.value, '_blank')
}

async function retryDoc(docId: string) {
  try {
    await fileApi.retryDocument(docId)
    ElMessage.success('已重新提交，请稍后刷新')
    await loadDocs()
  } catch {
    ElMessage.error('重试失败')
  }
}

async function deleteDoc(docId: string) {
  try {
    await fileApi.deleteDocument(docId)
    ElMessage.success('删除成功')
    await loadDocs()
  } catch {
    ElMessage.error('删除失败')
  }
}

function scheduleNext() {
  if (timer) clearTimeout(timer)
  timer = setTimeout(async () => {
    await loadDocs()
    const pending = documents.value.some(
      (d: any) => !['reviewed', 'failed'].includes(d.status)
    )
    if (pending) scheduleNext()
  }, 5000)
}

onMounted(() => {
  loadDomains()
  loadDocs().then(() => scheduleNext())
})

onUnmounted(() => clearTimeout(timer))
</script>

<style scoped>
.page {
  padding: 8px;
}

.uploader {
  width: 100%;
}

.section-block {
  margin-top: 16px;
}

.field-label {
  font-size: 13px;
  color: #606266;
  margin-bottom: 6px;
}

.field-hint {
  font-size: 12px;
  color: #c0c4cc;
  margin-top: 4px;
}

.doc-item {
  padding: 10px 0;
  border-bottom: 1px solid #f0f0f0;
}

.doc-item:last-child {
  border-bottom: none;
}

.doc-info {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.doc-actions {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-shrink: 0;
}
.doc-name {
  font-size: 14px;
  color: #303133;
  font-weight: 500;
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  margin-right: 8px;
}

.doc-meta {
  font-size: 12px;
  color: #909399;
  margin-top: 4px;
}
</style>
