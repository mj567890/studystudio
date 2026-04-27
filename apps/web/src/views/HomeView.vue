<template>
  <div class="home-page">
    <!-- 顶部欢迎栏 course_cards_v1 user_card_in_home_v1 -->
    <div class="welcome-bar">
      <div style="display:flex;align-items:center;gap:12px">
        <el-avatar :size="40" :src="auth.user?.avatar_url || ''" icon="UserFilled"
          style="cursor:pointer;flex-shrink:0" @click="$router.push('/profile')" />
        <div>
          <div style="font-size:16px;font-weight:600;color:#303133">
            {{ auth.user?.nickname || auth.user?.email }}
          </div>
          <div style="font-size:12px;color:#909399">
            <el-tag size="small" effect="plain" style="margin-right:4px">
              {{ auth.user?.roles?.[0] || 'learner' }}
            </el-tag>
            <el-button link size="small" @click="$router.push('/profile')">账号设置</el-button>
          </div>
        </div>
      </div>
      <el-button type="primary" size="small" @click="$router.push('/upload')">
        + 上传资料
      </el-button>
    </div>

    <!-- 课程卡片列表 -->
    <div v-if="domainsLoading" style="padding:40px;text-align:center">
      <el-icon class="is-loading" style="font-size:28px;color:#409eff"><Loading /></el-icon>
    </div>
    <div v-else-if="domains.length > 0" class="course-grid">
      <div
        v-for="d in domains"
        :key="d.domain_tag"
        class="course-card"
        :class="{ 'course-card--active': topicKey === d.domain_tag }"
        @click="selectCourse(d)"
      >
        <div class="course-card__header">
          <span class="course-card__title">{{ d.domain_tag }}</span>
          <el-tag size="small" :type="d.space_type === 'global' ? 'warning' : 'info'" effect="plain">
            {{ d.space_type === 'global' ? '全局' : '个人' }}
          </el-tag>
        </div>
        <div class="course-card__stats">
          <span>{{ d.approved_count || d.entity_count || 0 }} 个知识点</span>
          <template v-if="getCourseProgress(d.domain_tag)">
            <span style="margin:0 4px;color:#dcdfe6">|</span>
            <span>{{ getCourseProgress(d.domain_tag)?.read_chapters }}/{{ getCourseProgress(d.domain_tag)?.total_chapters }} 章</span>
          </template>
        </div>
        <el-progress
          v-if="getCourseProgress(d.domain_tag)"
          :percentage="Math.round((getCourseProgress(d.domain_tag)?.read_chapters || 0) / (getCourseProgress(d.domain_tag)?.total_chapters || 1) * 100)"
          :stroke-width="4" :show-text="false"
          style="margin-top:8px"
        />
        <el-button
          v-if="topicKey === d.domain_tag"
          type="primary" size="small"
          style="width:100%;margin-top:10px"
          @click.stop="$router.push(`/tutorial?topic=${d.domain_tag}`)"
        >
          继续学习 →
        </el-button>
      </div>
    </div>

    <!-- onboarding_guide_v1 -->
    <template v-if="!topicKey && !domainsLoading">
      <!-- 有主题但未选中（理论上不会出现，保留兜底） -->
      <el-empty v-if="domains.length > 0" description="请先选择学习主题" style="margin-top:80px" />
      <!-- 真正的新用户：没有任何资料 -->
      <div v-else class="onboarding-card">
        <div class="onboarding-icon">📚</div>
        <h2 class="onboarding-title">欢迎来到 StudyStudio</h2>
        <p class="onboarding-desc">
          上传你的学习资料（PDF、文档均可），AI 会自动生成专属课程，<br />
          帮你由浅入深地掌握其中的知识与技能。
        </p>
        <el-button type="primary" size="large" @click="$router.push('/upload')">
          立即上传资料，生成我的课程 →
        </el-button>
        <div class="onboarding-hint">
          也可以在「知识空间」里 Fork 社区分享的课程，直接开始学习
        </div>
        <el-button text size="small" style="margin-top:4px"
          @click="$router.push('/spaces')">
          浏览社区课程 →
        </el-button>
      </div>
    </template>

    <template v-else>
      <div v-if="radarLoading" style="padding:40px;text-align:center">
        <el-icon class="is-loading" style="font-size:32px;color:#409eff"><Loading /></el-icon>
        <p style="margin-top:12px;color:#909399">加载学习数据…</p>
      </div>

      <template v-else>
        <!-- 概览卡片行 -->
        <div class="stat-row">
          <div class="stat-card">
            <div class="stat-label">综合掌握度</div>
            <div class="stat-value" :style="masteryColor(overallMastery)">
              {{ Math.round(overallMastery * 100) }}%
            </div>
          </div>
          <div class="stat-card">
            <div class="stat-label">已读章节</div>
            <div class="stat-value">{{ totalRead }} / {{ totalChapters }}</div>
          </div>
          <div class="stat-card">
            <div class="stat-label">已完成阶段</div>
            <div class="stat-value">{{ completedStages }} / {{ stages.length }}</div>
          </div>
          <div class="stat-card" :class="{ 'stat-card--warn': reviewItems.length > 0 }">
            <div class="stat-label">待复习知识点</div>
            <div class="stat-value" :style="reviewItems.length > 0 ? 'color:#e6a23c' : ''">
              {{ reviewItems.length }}
            </div>
          </div>
        </div>

        <!-- 继续上次学习 card_main_v1 -->
        <div v-if="lastChapter" class="continue-card" @click="goContinueLearning">
          <div class="continue-card__left">
            <span class="continue-card__icon">📖</span>
            <div>
              <div class="continue-card__label">继续上次学习</div>
              <div class="continue-card__chapter">{{ lastChapter.chapter_title }}</div>
              <div class="continue-card__meta">
                {{ lastChapter.blueprint_title || lastChapter.topic_key }}
              </div>
            </div>
          </div>
          <el-button type="primary" size="small" round>继续 →</el-button>
        </div>

        <!-- 主内容网格 -->
        <div class="main-grid">
          <!-- 雷达图 -->
          <el-card class="radar-card" shadow="never">
            <template #header><span class="card-title">阶段掌握度雷达</span></template>
            <div class="radar-wrap">
              <svg v-if="stages.length >= 3" :viewBox="`0 0 ${SVG_SIZE} ${SVG_SIZE}`" class="radar-svg">
                <polygon
                  v-for="level in [0.2,0.4,0.6,0.8,1.0]" :key="level"
                  :points="gridPoints(level)" fill="none" stroke="#e4e7ed" stroke-width="1"
                />
                <line
                  v-for="(pt, i) in outerPoints" :key="'axis-'+i"
                  :x1="CENTER" :y1="CENTER" :x2="pt.x" :y2="pt.y"
                  stroke="#e4e7ed" stroke-width="1"
                />
                <polygon
                  :points="dataPoints"
                  fill="rgba(64,158,255,0.2)" stroke="#409eff"
                  stroke-width="2" stroke-linejoin="round"
                />
                <circle
                  v-for="(pt, i) in dataPointList" :key="'dp-'+i"
                  :cx="pt.x" :cy="pt.y" r="4" fill="#409eff"
                />
                <text
                  v-for="(pt, i) in labelPoints" :key="'label-'+i"
                  :x="pt.x" :y="pt.y"
                  text-anchor="middle" dominant-baseline="middle"
                  font-size="12" fill="#606266"
                >{{ truncate(stages[i]?.label, 6) }}</text>
                <text :x="CENTER+4" :y="CENTER - RADIUS*0.8" font-size="10" fill="#909399">80%</text>
                <text :x="CENTER+4" :y="CENTER - RADIUS*0.4" font-size="10" fill="#909399">40%</text>
              </svg>
              <el-empty v-else description="至少需要 3 个阶段才能显示雷达图" :image-size="60" />
            </div>
          </el-card>

          <!-- 阶段进度列表 -->
          <el-card shadow="never">
            <template #header><span class="card-title">各阶段学习进度</span></template>
            <div class="stages-list">
              <div v-for="s in stages" :key="s.label" class="stage-row">
                <div class="stage-row-top">
                  <span class="stage-name">{{ s.label }}</span>
                  <div style="display:flex;align-items:center;gap:8px">
                    <el-tag v-if="s.avg_mastery < 0.4" type="danger"   size="small" effect="plain">建议复习</el-tag>
                    <el-tag v-else-if="s.avg_mastery >= 0.8" type="success" size="small" effect="plain">已掌握</el-tag>
                    <span class="stage-pct" :style="masteryColor(s.avg_mastery)">
                      {{ Math.round(s.avg_mastery * 100) }}%
                    </span>
                  </div>
                </div>
                <el-progress
                  :percentage="Math.round(s.avg_mastery * 100)"
                  :color="progressColor(s.avg_mastery)"
                  :stroke-width="6" :show-text="false"
                  style="margin:4px 0 2px"
                />
                <div class="stage-read-info">已读 {{ s.read_count }} / {{ s.chapter_count }} 章</div>
              </div>
              <el-empty v-if="stages.length === 0" description="暂无阶段数据" :image-size="50" />
            </div>
          </el-card>
        </div>

        <!-- 薄弱章节 weak_marks_v1 -->
        <el-card v-if="weakChapters.length > 0" shadow="never" style="margin-bottom:16px">
          <template #header>
            <div style="display:flex;align-items:center;gap:8px">
              <el-icon style="color:#f56c6c;font-size:16px"><Warning /></el-icon>
              <span class="card-title">薄弱章节</span>
              <el-tag type="danger" size="small" effect="plain">
                {{ weakChapters.length }} 个章节掌握度不足
              </el-tag>
            </div>
          </template>
          <div class="weak-list">
            <div
              v-for="ch in weakChapters" :key="ch.chapter_id"
              class="weak-row"
              @click="$router.push(`/tutorial?topic=${ch.topic_key}`)"
            >
              <div class="weak-row__main">
                <span class="weak-row__title">{{ ch.chapter_title }}</span>
                <span class="weak-row__meta">{{ ch.blueprint_title }} · {{ ch.stage_title }}</span>
              </div>
              <div style="display:flex;align-items:center;gap:10px">
                <span class="weak-row__count">{{ ch.weak_entity_count }} 个薄弱知识点</span>
                <el-progress
                  :percentage="Math.round(ch.avg_mastery * 100)"
                  :color="progressColor(ch.avg_mastery)"
                  :stroke-width="6" :show-text="false"
                  style="width:80px"
                />
                <span class="weak-row__score" :style="masteryColor(ch.avg_mastery)">
                  {{ Math.round(ch.avg_mastery * 100) }}%
                </span>
              </div>
            </div>
          </div>
        </el-card>

        <!-- H-4 遗忘曲线复习提醒区 -->
        <el-card v-if="reviewItems.length > 0" shadow="never" style="margin-bottom:16px">
          <template #header>
            <div style="display:flex;align-items:center;justify-content:space-between">
              <div style="display:flex;align-items:center;gap:8px">
                <el-icon style="color:#e6a23c;font-size:16px"><Warning /></el-icon>
                <span class="card-title">遗忘曲线提醒</span>
                <el-tag type="warning" size="small" effect="plain">{{ reviewItems.length }} 个知识点已衰减</el-tag>
              </div>
              <el-button link size="small" @click="reviewExpanded = !reviewExpanded">
                {{ reviewExpanded ? '收起' : '展开全部' }}
              </el-button>
            </div>
          </template>

          <div class="review-grid">
            <div
              v-for="item in reviewExpanded ? reviewItems : reviewItems.slice(0,6)"
              :key="item.canonical_name"
              class="review-chip"
              :class="reviewUrgency(item.current_score)"
              @click="item.topic_key && $router.push('/tutorial')"
            >
              <div class="chip-name">{{ item.canonical_name }}</div>
              <div class="chip-meta">
                <span class="chip-domain">{{ item.domain_tag }}</span>
                <span class="chip-decay">
                  {{ Math.round(item.current_score * 100) }}%
                  <span class="chip-arrow">↓</span>
                  <span class="chip-days">{{ item.days_since < 1 ? '今天' : Math.round(item.days_since) + '天前' }}</span>
                </span>
              </div>
              <!-- 衰减进度条：灰色底 + 当前分数覆盖 -->
              <div class="decay-bar-bg">
                <div
                  class="decay-bar-orig"
                  :style="`width:${Math.round(item.original_score*100)}%`"
                />
                <div
                  class="decay-bar-cur"
                  :style="`width:${Math.round(item.current_score*100)}%`"
                />
              </div>
              <div class="chip-chapter" v-if="item.chapter_title">
                📖 {{ truncate(item.chapter_title, 16) }}
              </div>
            </div>
          </div>

          <div v-if="!reviewExpanded && reviewItems.length > 6" class="review-more">
            还有 {{ reviewItems.length - 6 }} 个知识点需要复习
            <el-button link size="small" @click="reviewExpanded = true">全部查看</el-button>
          </div>
        </el-card>

        <!-- 无复习任务时的鼓励提示 -->
        <el-alert
          v-else-if="!reviewLoading && reviewItems.length === 0 && totalRead > 0"
          title="所有已学知识点掌握度良好，继续保持！"
          type="success" show-icon :closable="false"
          style="margin-bottom:16px"
        />

        <!-- 最近学习记录 recent_activity_v1 -->
        <el-card v-if="recentActivity.length > 0" shadow="never">
          <template #header><span class="card-title">最近学习记录</span></template>
          <div class="activity-list">
            <div v-for="act in recentActivity" :key="act.chapter_id + act.completed_at" class="activity-row">
              <div class="activity-dot"></div>
              <div class="activity-body">
                <span class="activity-chapter">{{ act.chapter_title }}</span>
                <span class="activity-meta">
                  {{ act.blueprint_title }} · {{ act.stage_title }}
                </span>
              </div>
              <div class="activity-right">
                <span class="activity-time">{{ formatRelativeTime(act.completed_at) }}</span>
              </div>
            </div>
          </div>
        </el-card>
      </template>
    </template>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useAuthStore } from '@/stores/auth'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Loading, Warning } from '@element-plus/icons-vue'
import { knowledgeApi, achievementApi, reviewApi, dashboardApi } from '@/api'

const router = useRouter()
const auth    = useAuthStore()

const SVG_SIZE = 300
const CENTER   = SVG_SIZE / 2
const RADIUS   = 110

// ── 状态 ─────────────────────────────────────────────────────
const domains        = ref<any[]>([])
const domainsLoading = ref(false)
const topicKey       = ref('')

const stages         = ref<any[]>([])
const overallMastery = ref(0)
const radarLoading   = ref(false)

const reviewItems    = ref<any[]>([])
const reviewLoading  = ref(false)
const reviewExpanded = ref(false)

const recentActivity  = ref<any[]>([])
const weakChapters    = ref<any[]>([])
const lastChapter     = ref<any>(null)
const courseProgress  = ref<any[]>([])
const dashboardLoading = ref(false)

// ── 计算属性 ──────────────────────────────────────────────────
const totalRead = computed(() =>
  stages.value.reduce((s, r) => s + (r.read_count || 0), 0)
)
const totalChapters = computed(() =>
  stages.value.reduce((s, r) => s + (r.chapter_count || 0), 0)
)
const completedStages = computed(() =>
  stages.value.filter(s => s.avg_mastery >= 0.8).length
)

// ── 雷达图几何 ────────────────────────────────────────────────
function angleOf(i: number, n: number) {
  return (Math.PI * 2 * i) / n - Math.PI / 2
}
const outerPoints = computed(() =>
  stages.value.map((_, i) => {
    const a = angleOf(i, stages.value.length)
    return { x: CENTER + RADIUS * Math.cos(a), y: CENTER + RADIUS * Math.sin(a) }
  })
)
const labelPoints = computed(() =>
  stages.value.map((_, i) => {
    const a = angleOf(i, stages.value.length)
    return { x: CENTER + (RADIUS + 22) * Math.cos(a), y: CENTER + (RADIUS + 22) * Math.sin(a) }
  })
)
const dataPointList = computed(() =>
  stages.value.map((s, i) => {
    const a = angleOf(i, stages.value.length)
    const r = RADIUS * (s.avg_mastery || 0)
    return { x: CENTER + r * Math.cos(a), y: CENTER + r * Math.sin(a) }
  })
)
const dataPoints = computed(() =>
  dataPointList.value.map(p => `${p.x},${p.y}`).join(' ')
)
function gridPoints(level: number) {
  const n = stages.value.length
  if (n < 3) return ''
  return Array.from({ length: n }, (_, i) => {
    const a = angleOf(i, n)
    return `${CENTER + RADIUS * level * Math.cos(a)},${CENTER + RADIUS * level * Math.sin(a)}`
  }).join(' ')
}

// ── 样式工具 ──────────────────────────────────────────────────
function truncate(s: string = '', max: number) {
  return s.length <= max ? s : s.slice(0, max) + '…'
}
function masteryColor(v: number) {
  if (v >= 0.8) return 'color:#67c23a'
  if (v >= 0.5) return 'color:#409eff'
  if (v >= 0.3) return 'color:#e6a23c'
  return 'color:#f56c6c'
}
function progressColor(v: number) {
  if (v >= 0.8) return '#67c23a'
  if (v >= 0.5) return '#409eff'
  if (v >= 0.3) return '#e6a23c'
  return '#f56c6c'
}
function reviewUrgency(score: number) {
  if (score < 0.2) return 'chip--urgent'
  if (score < 0.4) return 'chip--warn'
  return 'chip--mild'
}

// ── 时间格式化 ──────────────────────────────────────────────────
function formatRelativeTime(iso: string | null) {
  if (!iso) return ''
  const diff = Date.now() - new Date(iso).getTime()
  const mins = Math.floor(diff / 60000)
  if (mins < 1) return '刚刚'
  if (mins < 60) return `${mins} 分钟前`
  const hours = Math.floor(mins / 60)
  if (hours < 24) return `${hours} 小时前`
  const days = Math.floor(hours / 24)
  if (days < 7) return `${days} 天前`
  return new Date(iso).toLocaleDateString('zh-CN')
}

function goContinueLearning() {
  if (lastChapter.value?.topic_key) {
    router.push(`/tutorial?topic=${lastChapter.value.topic_key}`)
  } else {
    router.push('/tutorial')
  }
}

function getCourseProgress(topic: string) {
  return courseProgress.value.find((c: any) => c.topic_key === topic) || null
}

// ── 数据加载 ──────────────────────────────────────────────────
async function loadDomains() {
  domainsLoading.value = true
  try {
    const res: any = await knowledgeApi.getDomains()
    domains.value = res.data?.domains || res.data || []
    if (domains.value.length > 0 && !topicKey.value) {
      topicKey.value = domains.value[0].domain_tag
      await Promise.all([loadRadar(), loadReview(), loadDashboard()])
    } else {
      await loadDashboard()  // 即便没有自动选中主题也加载进度数据
    }
  } catch {
    ElMessage.error('获取主题列表失败')
  } finally {
    domainsLoading.value = false
  }
}

async function loadRadar() {
  if (!topicKey.value) return
  radarLoading.value = true
  try {
    const res: any = await achievementApi.radar(topicKey.value)
    const data = res.data || {}
    stages.value        = data.stages  || []
    overallMastery.value = data.overall || 0
  } catch {
    ElMessage.error('获取学习数据失败')
  } finally {
    radarLoading.value = false
  }
}

async function loadDashboard() {
  dashboardLoading.value = true
  try {
    const res: any = await dashboardApi.get()
    const data = res.data || {}
    recentActivity.value  = data.recent_activity  || []
    weakChapters.value    = data.weak_chapters    || []
    courseProgress.value  = data.course_progress  || []
    // 优先当前主题的上次章节，降级到最近学习的任意主题
    const all = data.last_learned || []
    lastChapter.value    = all.find((l: any) => l.topic_key === topicKey.value) || all[0] || null
  } catch {
    // dashboard 加载失败不阻断主流程
    recentActivity.value = []
    weakChapters.value   = []
    lastChapter.value    = null
  } finally {
    dashboardLoading.value = false
  }
}

async function loadReview() {
  reviewLoading.value = true
  try {
    const res: any = await reviewApi.getDue()
    reviewItems.value = res.data?.items || []
  } catch {
    // 复习提醒加载失败不阻断主流程，静默处理
    reviewItems.value = []
  } finally {
    reviewLoading.value = false
  }
}

async function selectCourse(d: any) {
  topicKey.value = d.domain_tag
  onTopicChange()
}

async function onTopicChange() {
  stages.value = []
  overallMastery.value = 0
  recentActivity.value  = []
  weakChapters.value    = []
  lastChapter.value     = null
  courseProgress.value  = []
  await loadRadar()
  await loadDashboard()
  // review-due 是全局接口（不按 topic 过滤），无需重新加载
}

onMounted(loadDomains)
</script>

<style scoped>
.home-page {
  padding: 16px;
  max-width: 1100px;
  margin: 0 auto;
}
.welcome-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 20px;
}
.welcome-title {
  font-size: 20px;
  font-weight: 600;
  color: #303133;
}
.stat-row {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
  margin-bottom: 16px;
}
.stat-card {
  background: #f5f7fa;
  border-radius: 8px;
  padding: 16px 20px;
  text-align: center;
}
.stat-card--warn { background: #fdf6ec; }
.stat-label { font-size: 13px; color: #909399; margin-bottom: 8px; }
.stat-value { font-size: 26px; font-weight: 600; color: #303133; }

.main-grid {
  display: grid;
  grid-template-columns: 340px 1fr;
  gap: 16px;
  margin-bottom: 16px;
}
.card-title { font-size: 15px; font-weight: 600; color: #303133; }

.radar-wrap { display: flex; justify-content: center; padding: 8px 0; }
.radar-svg  { width: 100%; max-width: 280px; height: auto; }

.stages-list { display: flex; flex-direction: column; gap: 14px; }
.stage-row-top {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.stage-name {
  font-size: 13px; color: #303133; font-weight: 500;
  max-width: 160px; overflow: hidden;
  text-overflow: ellipsis; white-space: nowrap;
}
.stage-pct   { font-size: 14px; font-weight: 600; }
.stage-read-info { font-size: 12px; color: #909399; }

/* ── 遗忘曲线复习区 ─────────────────────────── */
.review-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: 10px;
}
.review-chip {
  border-radius: 8px;
  padding: 10px 12px;
  cursor: pointer;
  transition: opacity .15s;
  border: 1px solid transparent;
}
.review-chip:hover { opacity: .85; }

.chip--urgent {
  background: #fef0f0;
  border-color: #fde2e2;
}
.chip--warn {
  background: #fdf6ec;
  border-color: #faecd8;
}
.chip--mild {
  background: #f4f4f5;
  border-color: #e9e9eb;
}
.chip-name {
  font-size: 13px;
  font-weight: 600;
  color: #303133;
  margin-bottom: 4px;
}
.chip-meta {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 6px;
}
.chip-domain {
  font-size: 11px;
  color: #909399;
  background: #f0f2f5;
  padding: 1px 6px;
  border-radius: 4px;
}
.chip-decay  { font-size: 12px; color: #e6a23c; font-weight: 500; }
.chip-arrow  { margin: 0 2px; }
.chip-days   { font-size: 11px; color: #909399; }

/* 衰减双层进度条 */
.decay-bar-bg {
  position: relative;
  height: 4px;
  background: #ebeef5;
  border-radius: 2px;
  margin-bottom: 6px;
  overflow: hidden;
}
.decay-bar-orig {
  position: absolute;
  top: 0; left: 0;
  height: 100%;
  background: #d3d3d3;
  border-radius: 2px;
}
.decay-bar-cur {
  position: absolute;
  top: 0; left: 0;
  height: 100%;
  background: #e6a23c;
  border-radius: 2px;
}
.chip--urgent .decay-bar-cur { background: #f56c6c; }
.chip--mild   .decay-bar-cur { background: #409eff; }

.chip-chapter {
  font-size: 11px;
  color: #909399;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.review-more {
  margin-top: 10px;
  font-size: 13px;
  color: #909399;
  text-align: center;
}

/* ── 继续上次学习卡片 continue_learning_v1 ── */
.continue-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: linear-gradient(135deg, #f0f7ff, #ecf5ff);
  border: 1px solid #d9ecff;
  border-radius: 12px;
  padding: 16px 20px;
  margin-bottom: 16px;
  cursor: pointer;
  transition: all .2s;
}
.continue-card:hover {
  border-color: #409eff;
  box-shadow: 0 2px 12px rgba(64,158,255,0.12);
}
.continue-card__left {
  display: flex;
  align-items: center;
  gap: 14px;
}
.continue-card__icon { font-size: 28px; }
.continue-card__label { font-size: 13px; color: #409eff; font-weight: 500; }
.continue-card__chapter {
  font-size: 16px; font-weight: 600; color: #303133; margin: 2px 0;
}
.continue-card__meta { font-size: 12px; color: #909399; }

/* ── 薄弱章节 weak_section_v1 ── */
.weak-list { display: flex; flex-direction: column; gap: 8px; }
.weak-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 14px;
  border-radius: 8px;
  background: #fef0f0;
  border: 1px solid #fde2e2;
  cursor: pointer;
  transition: opacity .15s;
}
.weak-row:hover { opacity: .85; }
.weak-row__main { display: flex; flex-direction: column; gap: 2px; }
.weak-row__title { font-size: 14px; font-weight: 600; color: #303133; }
.weak-row__meta  { font-size: 12px; color: #909399; }
.weak-row__count { font-size: 12px; color: #f56c6c; }
.weak-row__score { font-size: 14px; font-weight: 600; min-width: 42px; text-align: right; }

/* ── 最近学习记录 activity_v1 ── */
.activity-list { display: flex; flex-direction: column; gap: 2px; }
.activity-row {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 0;
  border-bottom: 1px solid #f5f5f5;
}
.activity-row:last-child { border-bottom: none; }
.activity-dot {
  width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0;
  background: #409eff;
}
.activity-body { flex: 1; display: flex; flex-direction: column; gap: 2px; }
.activity-chapter { font-size: 14px; color: #303133; font-weight: 500; }
.activity-meta     { font-size: 12px; color: #909399; }
.activity-right    { display: flex; flex-direction: column; align-items: flex-end; gap: 2px; }
.activity-time     { font-size: 11px; color: #c0c4cc; }

@media (max-width: 768px) {
  .stat-row  { grid-template-columns: repeat(2, 1fr); }
  .main-grid { grid-template-columns: 1fr; }
}

/* 课程卡片 course_cards_v1 */
.course-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: 14px;
  margin-bottom: 20px;
}
.course-card {
  background: #fff;
  border: 2px solid #e4e7ed;
  border-radius: 12px;
  padding: 16px;
  cursor: pointer;
  transition: all 0.2s;
}
.course-card:hover { border-color: #409eff; box-shadow: 0 2px 12px rgba(64,158,255,0.15); }
.course-card--active { border-color: #409eff; background: #f0f7ff; }
.course-card__header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 8px;
  margin-bottom: 8px;
}
.course-card__title {
  font-size: 15px;
  font-weight: 600;
  color: #303133;
  word-break: break-all;
  flex: 1;
}
.course-card__stats { font-size: 12px; color: #909399; }

/* 新用户引导卡片 */
.onboarding-card {
  max-width: 520px;
  margin: 80px auto 0;
  text-align: center;
  padding: 48px 40px;
  background: #f8f9ff;
  border-radius: 16px;
  border: 1px solid #e0e7ff;
}
.onboarding-icon  { font-size: 52px; margin-bottom: 16px; }
.onboarding-title { font-size: 22px; font-weight: 700; color: #303133; margin: 0 0 12px; }
.onboarding-desc  {
  font-size: 15px; color: #606266; line-height: 1.8;
  margin-bottom: 28px;
}
.onboarding-hint  { font-size: 13px; color: #909399; margin-top: 20px; }
</style>
