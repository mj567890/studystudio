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
            <p class="field-label">选择已有领域</p>
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
            <p class="field-hint">当前知识空间下没有可选领域时，直接在下面输入新领域名。</p>
          </div>

          <div class="section-block">
            <p class="field-label">或输入新领域名</p>
            <el-input
              v-model="newDomainName"
              clearable
              maxlength="100"
              show-word-limit
              placeholder="直接输入新领域名，如：python-basic"
            />
          </div>

          <div class="section-block">
            <p class="field-label">知识空间</p>
            <el-radio-group v-model="spaceType">
              <el-radio label="personal">个人知识库（仅自己可见）</el-radio>
              <el-radio label="global" :disabled="!canUseGlobal">全局知识库（需管理员/审核员权限）</el-radio>
            </el-radio-group>
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

          <el-empty v-if="!docsLoading && !documents.length" description="暂无上传记录" />

          <div v-for="doc in documents" :key="doc.document_id" class="doc-item">
            <div class="doc-info">
              <span class="doc-name">{{ doc.title || doc.file_name }}</span>
              <el-tag size="small" :type="statusType(doc.status)" style="margin-left:8px">
                {{ statusLabel(doc.status) }}
              </el-tag>
            </div>
            <div class="doc-meta">
              <span>{{ doc.file_type?.toUpperCase() }}</span>
              <span style="margin:0 6px">·</span>
              <span>{{ formatSize(doc.file_size) }}</span>
              <template v-if="doc.domain_tag">
                <span style="margin:0 6px">·</span>
                <span>{{ doc.domain_tag }}</span>
              </template>
              <span v-if="doc.chunk_count" style="margin:0 6px">·</span>
              <span v-if="doc.chunk_count">{{ doc.chunk_count }} 个知识片段</span>
            </div>
          </div>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { fileApi, knowledgeApi } from '@/api'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const authState = auth as any
const canUseGlobal = computed(() => {
  const roles = authState.user?.roles || authState.roles || []
  return Boolean(authState.isAdmin || roles.includes('admin') || roles.includes('knowledge_reviewer'))
})
const uploading = ref(false)
const domainsLoading = ref(false)
const docsLoading = ref(false)
const fileList = ref<any[]>([])
const selectedFile = ref<File | null>(null)
const selectedExistingDomain = ref('')
const newDomainName = ref('')
const spaceType = ref(canUseGlobal.value ? 'global' : 'personal')
const uploadResult = ref<any>(null)
const domains = ref<any[]>([])
const documents = ref<any[]>([])
let timer: ReturnType<typeof setInterval>

const STATUS_LABELS: Record<string, string> = {
  uploaded: '待解析',
  parsed: '解析中',
  extracted: '抽取中',
  reviewed: '待审核',
  published: '已完成',
  failed: '解析失败'
}
const STATUS_TYPES: Record<string, string> = {
  uploaded: 'info',
  parsed: 'warning',
  extracted: 'warning',
  reviewed: '',
  published: 'success',
  failed: 'danger'
}

const visibleDomains = computed(() =>
  domains.value.filter((item: any) => item.space_type === spaceType.value)
)

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
  return `上传成功！已进入领域「${domain}」的解析队列，通常需要 1-5 分钟`
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
  selectedFile.value = file.raw || null
  fileList.value = files
}

function handleRemove(_file: any, files: any[]) {
  fileList.value = files
  selectedFile.value = files.length ? files[files.length - 1].raw || null : null
}

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
      ElMessage.success(`已复用原文件并重新投递到领域「${res.data.domain_tag || domain}」`)
    } else if (res.data?.is_duplicate && res.data?.already_in_space) {
      ElMessage.warning(`该文件已在领域「${res.data.already_in_space}」中处理过，知识点已可用，无需重复上传`)
    } else if (res.data?.is_duplicate) {
      ElMessage.warning('文件已存在，系统已自动去重')
    } else {
      ElMessage.success('上传完成，系统正在后台解析')
    }

    fileList.value = []
    selectedFile.value = null
    await loadDocs()
    await loadDomains()
  } finally {
    uploading.value = false
  }
}

async function loadDomains() {
  domainsLoading.value = true
  try {
    const res: any = await knowledgeApi.getDomains()
    domains.value = res.data?.domains || []

    const hasCurrentDomains = domains.value.some((item: any) => item.space_type === spaceType.value)
    if (!hasCurrentDomains) {
      if (canUseGlobal.value && domains.value.some((item: any) => item.space_type === 'global')) {
        spaceType.value = 'global'
      } else if (domains.value.some((item: any) => item.space_type === 'personal')) {
        spaceType.value = 'personal'
      }
    }
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

onMounted(() => {
  loadDomains()
  loadDocs()
  timer = setInterval(loadDocs, 30000)
})

onUnmounted(() => clearInterval(timer))
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

.doc-name {
  font-size: 14px;
  color: #303133;
  font-weight: 500;
}

.doc-meta {
  font-size: 12px;
  color: #909399;
  margin-top: 4px;
}
</style>
