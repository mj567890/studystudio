<template>
  <div class="page">
    <el-row :gutter="20">
      <!-- 用户信息卡片 -->
      <el-col :span="8">
        <el-card>
          <div class="user-card">
            <el-avatar :size="64" icon="UserFilled" />
            <h3>{{ auth.user?.nickname }}</h3>
            <p class="email">{{ auth.user?.email }}</p>
            <el-tag>{{ auth.user?.roles?.[0] || 'learner' }}</el-tag>
          </div>
        </el-card>

        <el-card style="margin-top:16px">
          <template #header>快速操作</template>
          <el-button type="primary" style="width:100%;margin-bottom:10px"
            @click="router.push('/quiz')">开始定位自检</el-button>
          <el-button style="width:100%;margin-bottom:10px"
            @click="router.push('/gaps')">查看知识漏洞</el-button>
          <el-button style="width:100%"
            @click="router.push('/path')">获取学习路径</el-button>
        </el-card>
      </el-col>

      <!-- 掌握度摘要 -->
      <el-col :span="16">
        <el-card v-loading="loading">
          <template #header>
            <span>知识掌握概览</span>
            <el-button text style="float:right" @click="loadProfile">刷新</el-button>
          </template>

          <div v-if="profile">
            <el-descriptions :column="2" border>
              <el-descriptions-item label="最近更新">
                {{ formatDate(profile.updated_at) }}
              </el-descriptions-item>
              <el-descriptions-item label="画像版本">
                V{{ profile.version }}
              </el-descriptions-item>
            </el-descriptions>

            <div v-if="lastDiagnosis" style="margin-top:20px">
              <h4 style="margin-bottom:12px">最新诊断结果</h4>
              <el-alert v-if="lastDiagnosis.last_error_pattern"
                :title="lastDiagnosis.last_error_pattern"
                type="warning" show-icon :closable="false" />
              <div style="margin-top:12px">
                <span style="color:#606266;font-size:14px">识别到的障碍类型：</span>
                <el-tag v-for="g in lastDiagnosis.last_gap_types" :key="g"
                  type="danger" style="margin:4px">{{ gapTypeLabel(g) }}</el-tag>
              </div>
              <div style="margin-top:8px">
                <span style="color:#606266;font-size:14px">诊断置信度：</span>
                <el-progress :percentage="Math.round((lastDiagnosis.last_confidence||0)*100)"
                  :stroke-width="8" style="width:200px;display:inline-block;margin-left:8px" />
              </div>
            </div>

            <el-empty v-else description="暂无诊断数据，开始学习后自动生成"
              style="margin-top:20px" />
          </div>
          <el-empty v-else-if="!loading" description="暂无画像数据，请先完成定位自检" />
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { learnerApi } from '@/api'

const router  = useRouter()
const auth    = useAuthStore()
const loading = ref(false)
const profile = ref<any>(null)

const lastDiagnosis = computed(() => profile.value?.mastery_summary || null)

const GAP_LABELS: Record<string, string> = {
  definition: '定义型', mechanism: '机制型', flow: '流程型',
  distinction: '区分型', application: '应用型', causal: '因果型'
}
const gapTypeLabel = (g: string) => GAP_LABELS[g] || g

function formatDate(d: string) {
  return d ? new Date(d).toLocaleString('zh-CN') : '-'
}

async function loadProfile() {
  loading.value = true
  try {
    const res: any = await learnerApi.getProfile()
    profile.value = res.data
  } catch {} finally {
    loading.value = false
  }
}

onMounted(loadProfile)
</script>

<style scoped>
.page { padding: 8px; }
.user-card { text-align: center; padding: 16px 0; }
.user-card h3 { margin: 12px 0 4px; font-size: 18px; }
.email { color: #909399; font-size: 13px; margin-bottom: 12px; }
</style>
