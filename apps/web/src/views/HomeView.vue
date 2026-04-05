<template>
  <div class="home-page">
    <div class="welcome">
      <h2>欢迎回来，{{ auth.user?.nickname }} 👋</h2>
      <p>选择一个主题开始学习，或上传资料扩展你的知识库</p>
    </div>

    <!-- 统计卡片 -->
    <el-row :gutter="16" style="margin-bottom:24px">
      <el-col :span="6">
        <el-card class="stat-card">
          <el-statistic title="可学主题" :value="domains.length" />
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card class="stat-card">
          <el-statistic title="知识点总数" :value="totalEntities" />
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card class="stat-card">
          <el-statistic title="我的文档" :value="myDocCount" />
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card class="stat-card">
          <el-statistic title="学习对话" :value="0" />
        </el-card>
      </el-col>
    </el-row>

    <!-- 主题列表 -->
    <el-card v-loading="loading">
      <template #header>
        <span>📚 可学习主题</span>
        <el-button text style="float:right" @click="loadDomains">刷新</el-button>
      </template>

      <el-empty v-if="!loading && !domains.length"
        description="知识库暂无内容，请联系管理员导入种子知识库">
        <el-button type="primary" @click="router.push('/upload')">上传我的资料</el-button>
      </el-empty>

      <el-row :gutter="16">
        <el-col :span="8" v-for="domain in domains" :key="domain.domain_tag"
          style="margin-bottom:16px">
          <el-card class="domain-card" shadow="hover" @click="selectDomain(domain)">
            <div class="domain-icon">{{ domainIcon(domain.domain_tag) }}</div>
            <h3 class="domain-name">{{ domain.domain_tag }}</h3>
            <div class="domain-meta">
              <el-tag size="small">{{ domain.entity_count }} 个知识点</el-tag>
              <el-tag size="small" type="success" style="margin-left:6px">
                {{ domain.core_count }} 个核心
              </el-tag>
            </div>
            <div class="domain-actions">
              <el-button size="small" type="primary"
                @click.stop="startQuiz(domain.domain_tag)">开始自检</el-button>
              <el-button size="small"
                @click.stop="startTutorial(domain.domain_tag)">学习教程</el-button>
            </div>
          </el-card>
        </el-col>
      </el-row>
    </el-card>

    <!-- 我的最近文档 -->
    <el-card style="margin-top:16px" v-if="recentDocs.length">
      <template #header>📄 我的最近上传</template>
      <el-table :data="recentDocs" size="small">
        <el-table-column prop="title" label="文档名" show-overflow-tooltip />
        <el-table-column prop="file_type" label="类型" width="80" />
        <el-table-column label="解析状态" width="120">
          <template #default="{ row }">
            <el-tag :type="statusType(row.status)" size="small">
              {{ statusLabel(row.status) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="知识点数" width="100">
          <template #default="{ row }">
            {{ row.chunk_count || '-' }}
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { knowledgeApi, fileApi } from '@/api'

const router  = useRouter()
const auth    = useAuthStore()
const loading = ref(false)
const domains = ref<any[]>([])
const recentDocs = ref<any[]>([])

const totalEntities = computed(() =>
  domains.value.reduce((sum, d) => sum + d.entity_count, 0)
)
const myDocCount = computed(() => recentDocs.value.length)

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

function domainIcon(tag: string): string {
  if (tag.includes('security') || tag.includes('hack')) return '🔐'
  if (tag.includes('python') || tag.includes('code')) return '🐍'
  if (tag.includes('web')) return '🌐'
  if (tag.includes('data') || tag.includes('ai')) return '🤖'
  return '📖'
}

function selectDomain(domain: any) {
  router.push({ path: '/gaps', query: { topic: domain.domain_tag } })
}

function startQuiz(topicKey: string) {
  router.push({ path: '/quiz', query: { topic: topicKey } })
}

function startTutorial(topicKey: string) {
  router.push({ path: '/tutorial', query: { topic: topicKey } })
}

async function loadDomains() {
  loading.value = true
  try {
    const res: any = await knowledgeApi.getDomains()
    domains.value = res.data?.domains || []
  } catch {} finally { loading.value = false }
}

async function loadDocs() {
  try {
    const res: any = await fileApi.getMyDocuments()
    recentDocs.value = (res.data?.documents || []).slice(0, 5)
  } catch {}
}

onMounted(() => {
  loadDomains()
  loadDocs()
})
</script>

<style scoped>
.home-page { padding: 8px; }
.welcome   { margin-bottom: 20px; }
.welcome h2 { font-size: 22px; color: #303133; margin-bottom: 4px; }
.welcome p  { color: #909399; }
.stat-card  { text-align: center; }
.domain-card { cursor: pointer; transition: transform .2s; }
.domain-card:hover { transform: translateY(-2px); }
.domain-icon { font-size: 32px; margin-bottom: 8px; }
.domain-name { font-size: 16px; font-weight: 600; margin-bottom: 8px; color: #303133; }
.domain-meta { margin-bottom: 12px; }
.domain-actions { display: flex; gap: 8px; }
</style>
