<template>
  <div class="home-page">
    <!-- 顶部欢迎栏 -->
    <div class="welcome-bar">
      <div class="welcome-left">
        <span class="welcome-title">学习中心</span>
        <el-select
          v-model="topicKey"
          placeholder="选择学习主题"
          size="small"
          style="width:200px;margin-left:16px"
          :loading="domainsLoading"
          @change="onTopicChange"
        >
          <el-option
            v-for="d in domains"
            :key="d.domain_tag"
            :label="`${d.domain_tag}（${d.space_type === 'global' ? '全局' : '私有'}）`"
            :value="d.domain_tag"
          />
        </el-select>
      </div>
      <el-button type="primary" size="small" @click="$router.push('/tutorial')">
        继续学习 →
      </el-button>
    </div>

    <el-empty v-if="!topicKey" description="请先选择学习主题" style="margin-top:80px" />

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
      </template>
    </template>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Loading, Warning } from '@element-plus/icons-vue'
import { knowledgeApi, achievementApi, reviewApi } from '@/api'

const router = useRouter()

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

// ── 数据加载 ──────────────────────────────────────────────────
async function loadDomains() {
  domainsLoading.value = true
  try {
    const res: any = await knowledgeApi.getDomains()
    domains.value = res.data?.domains || res.data || []
    if (domains.value.length > 0 && !topicKey.value) {
      topicKey.value = domains.value[0].domain_tag
      await Promise.all([loadRadar(), loadReview()])
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

async function onTopicChange() {
  stages.value = []
  overallMastery.value = 0
  await loadRadar()
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

@media (max-width: 768px) {
  .stat-row  { grid-template-columns: repeat(2, 1fr); }
  .main-grid { grid-template-columns: 1fr; }
}
</style>
