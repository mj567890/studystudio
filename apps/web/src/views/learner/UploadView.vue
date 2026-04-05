<template>
  <div class="page">
    <el-row :gutter="16">
      <!-- 上传区域 -->
      <el-col :span="12">
        <el-card>
          <template #header>上传学习资料</template>

          <el-upload drag :auto-upload="false" :on-change="handleChange"
            :file-list="fileList" accept=".pdf,.docx,.md,.txt" class="uploader">
            <el-icon style="font-size:48px;color:#c0c4cc"><UploadFilled /></el-icon>
            <p style="margin:12px 0 4px;font-size:15px">拖拽文件到此处，或点击选择</p>
            <p style="color:#909399;font-size:13px">支持 PDF、Word、Markdown、TXT，最大 100MB</p>
          </el-upload>

          <div style="margin-top:16px">
            <p style="font-size:13px;color:#606266;margin-bottom:6px">选择知识领域</p>
            <el-select v-model="selectedDomain" placeholder="选择已有领域或输入新领域名"
              filterable allow-create style="width:100%" :loading="domainsLoading">
              <el-option v-for="d in domains" :key="d.domain_tag"
                :label="`${d.domain_tag}（${d.entity_count}个知识点）`"
                :value="d.domain_tag" />
            </el-select>
            <p style="font-size:12px;color:#c0c4cc;margin-top:4px">
              可直接输入新领域名称，如：python-basic
            </p>
          </div>

          <div style="margin-top:12px">
            <p style="font-size:13px;color:#606266;margin-bottom:6px">知识空间</p>
            <el-radio-group v-model="spaceType">
              <el-radio label="personal">个人知识库（仅自己可见）</el-radio>
              <el-radio label="global" :disabled="!auth.isAdmin">全局知识库（需管理员权限）</el-radio>
            </el-radio-group>
          </div>

          <el-button type="primary" size="large" :loading="uploading"
            :disabled="!selectedFile || !selectedDomain"
            style="width:100%;margin-top:20px" @click="upload">
            {{ uploading ? '上传中...' : '开始上传' }}
          </el-button>

          <el-alert v-if="uploadResult" style="margin-top:12px"
            :title="uploadResult.is_duplicate
              ? '文件已存在，已自动去重'
              : '上传成功！系统正在后台解析知识点，通常需要 1-5 分钟'"
            :type="uploadResult.is_duplicate ? 'warning' : 'success'"
            show-icon :closable="false" />
        </el-card>
      </el-col>

      <!-- 已上传文档列表 -->
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
import { ref, onMounted, onUnmounted } from 'vue'
import { ElMessage } from 'element-plus'
import { fileApi, knowledgeApi } from '@/api'
import { useAuthStore } from '@/stores/auth'

const auth           = useAuthStore()
const uploading      = ref(false)
const domainsLoading = ref(false)
const docsLoading    = ref(false)
const fileList       = ref<any[]>([])
const selectedFile   = ref<File | null>(null)
const selectedDomain = ref('')
const spaceType      = ref('personal')
const uploadResult   = ref<any>(null)
const domains        = ref<any[]>([])
const documents      = ref<any[]>([])
let   timer: ReturnType<typeof setInterval>

const STATUS_LABELS: Record<string, string> = {
  uploaded: '待解析', parsed: '解析中', extracted: '抽取中',
  reviewed: '待审核', published: '已完成', failed: '解析失败'
}
const STATUS_TYPES: Record<string, string> = {
  uploaded: 'info', parsed: 'warning', extracted: 'warning',
  reviewed: '', published: 'success', failed: 'danger'
}
const statusLabel = (s: string) => STATUS_LABELS[s] || s
const statusType  = (s: string) => STATUS_TYPES[s] || ''

function formatSize(bytes: number): string {
  if (!bytes) return '-'
  if (bytes < 1024 * 1024) return `${(bytes/1024).toFixed(1)}KB`
  return `${(bytes/1024/1024).toFixed(1)}MB`
}

function handleChange(file: any) { selectedFile.value = file.raw }

async function upload() {
  if (!selectedFile.value || !selectedDomain.value) return
  uploading.value = true
  uploadResult.value = null
  try {
    const res: any = await fileApi.upload(selectedFile.value, spaceType.value, selectedDomain.value)
    uploadResult.value = res.data
    ElMessage.success('上传完成，系统正在后台解析')
    fileList.value = []
    selectedFile.value = null
    await loadDocs()
    await loadDomains()
  } finally { uploading.value = false }
}

async function loadDomains() {
  domainsLoading.value = true
  try {
    const res: any = await knowledgeApi.getDomains()
    domains.value = res.data?.domains || []
  } catch {} finally { domainsLoading.value = false }
}

async function loadDocs() {
  docsLoading.value = true
  try {
    const res: any = await fileApi.getMyDocuments()
    documents.value = res.data?.documents || []
  } catch {} finally { docsLoading.value = false }
}

onMounted(() => {
  loadDomains()
  loadDocs()
  timer = setInterval(loadDocs, 30000)  // 每30秒刷新一次解析状态
})
onUnmounted(() => clearInterval(timer))
</script>

<style scoped>
.page { padding: 8px; }
.uploader { width: 100%; }
.doc-item { padding: 10px 0; border-bottom: 1px solid #f0f0f0; }
.doc-item:last-child { border-bottom: none; }
.doc-name { font-size: 14px; color: #303133; font-weight: 500; }
.doc-meta { font-size: 12px; color: #909399; margin-top: 4px; }
</style>
