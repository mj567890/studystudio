<template>
  <div class="page">
    <el-card>
      <template #header>
        <span>课程设计向导</span>
        <div style="float:right;display:flex;gap:8px;align-items:center">
          <el-select v-model="topicKey" placeholder="选择主题" size="small"
            style="width:220px" :loading="domainsLoading" @change="onTopicChange">
            <el-option v-for="d in domains" :key="d.domain_tag"
              :label="`${d.domain_tag}（${d.space_type === 'global' ? '全局' : '私有'}）`"
              :value="d.domain_tag" />
          </el-select>
        </div>
      </template>

      <!-- 步骤条 -->
      <el-steps :active="step" align-center style="margin-bottom:28px">
        <el-step title="选择方案" description="AI 分析 + 教师选择" />
        <el-step title="经验校准" description="5 道选择题 · 3 分钟" />
        <el-step title="确认生成" description="预览 + 启动生成" />
      </el-steps>

      <!-- ═══════════════════════════════════════ -->
      <!-- Step 1：选择方案 -->
      <!-- ═══════════════════════════════════════ -->
      <div v-if="step === 1">
        <!-- 加载状态 -->
        <div v-if="loading" style="text-align:center;padding:60px 0">
          <el-icon class="is-loading" :size="32"><Loading /></el-icon>
          <p style="color:#909399;margin-top:12px">AI 正在分析知识体系，生成课程方案...</p>
        </div>

        <!-- 错误状态 -->
        <el-alert v-else-if="error" :title="error" type="error" show-icon style="margin-bottom:16px" />

        <!-- 方案为空 -->
        <el-empty v-else-if="!proposals.length && !loading"
          description="请先选择主题，AI 将自动生成课程方案" />

        <!-- 方案卡片 -->
        <div v-else>
          <p style="color:#606266;font-size:13px;margin-bottom:12px">
            以下 3 套方案基于知识体系分析生成。请选择最适合你学生的方案，然后微调关键参数。
          </p>

          <div style="display:flex;gap:16px;margin-bottom:24px">
            <el-card
              v-for="p in proposals"
              :key="p.id"
              :shadow="selectedId === p.id ? 'always' : 'hover'"
              :class="['proposal-card', { selected: selectedId === p.id }]"
              @click="selectProposal(p.id)"
            >
              <div style="text-align:center;margin-bottom:8px">
                <el-tag :type="tagType(p.id)" size="small">{{ p.id }} · {{ p.tagline }}</el-tag>
              </div>

              <div class="prop-field">
                <span class="prop-label">面向</span>
                <span class="prop-value">{{ p.target_audience?.label }}</span>
              </div>
              <div class="prop-field">
                <span class="prop-label">风格</span>
                <span class="prop-value">{{ p.teaching_style?.label }}</span>
              </div>
              <div class="prop-field">
                <span class="prop-label">结构</span>
                <span class="prop-value">{{ p.course_structure?.total_chapters }}章·{{ p.course_structure?.estimated_hours }}h</span>
              </div>
              <div class="prop-field">
                <span class="prop-label">节奏</span>
                <span class="prop-value">{{ p.course_structure?.pacing }}</span>
              </div>

              <el-divider style="margin:10px 0" />

              <div style="font-size:12px;color:#909399">
                <p style="margin:2px 0">{{ p.target_audience?.why_this_audience }}</p>
                <p style="margin:2px 0;font-weight:500">{{ p.key_differentiator }}</p>
              </div>

              <div style="text-align:center;margin-top:10px">
                <el-button
                  :type="selectedId === p.id ? 'primary' : 'default'"
                  size="small"
                  @click.stop="selectProposal(p.id)"
                >
                  {{ selectedId === p.id ? '已选择' : '选择方案 ' + p.id }}
                </el-button>
              </div>
            </el-card>
          </div>

          <!-- 填空题区域（选中方案后展开） -->
          <div v-if="selectedId" style="background:#f5f7fa;border-radius:8px;padding:20px">
            <h4 style="margin:0 0 12px 0;color:#303133">
              微调方案 {{ selectedId }}
              <span style="font-size:12px;color:#909399;font-weight:normal">— 直接使用 AI 建议值即可，也可按需调整</span>
            </h4>

            <el-form :model="adjustments" label-width="120px" label-position="left">
              <el-form-item label="总课时（小时）">
                <el-input-number v-model="adjustments.total_hours" :min="4" :max="200" :step="1" size="small" />
                <span style="margin-left:8px;font-size:12px;color:#909399">AI 建议：{{ selectedProposal?.course_structure?.estimated_hours }}h</span>
              </el-form-item>

              <el-form-item label="难度等级">
                <el-select v-model="adjustments.difficulty" size="small" style="width:160px">
                  <el-option label="初级（入门）" value="beginner" />
                  <el-option label="中级（进阶）" value="intermediate" />
                  <el-option label="高级（深入）" value="advanced" />
                </el-select>
                <span style="margin-left:8px;font-size:12px;color:#909399">AI 建议：{{ levelLabel(selectedProposal?.target_audience?.level) }}</span>
              </el-form-item>

              <el-form-item label="理论 / 实操比例">
                <div style="display:flex;align-items:center;gap:8px">
                  <span style="font-size:12px;color:#909399">理论</span>
                  <el-slider v-model="adjustments.theory_ratio" :min="10" :max="90" :step="10"
                    style="width:200px" show-stops />
                  <span style="font-size:12px;color:#909399">实操</span>
                  <span style="font-size:12px;color:#606266;margin-left:8px">
                    {{ adjustments.theory_ratio }} : {{ 100 - adjustments.theory_ratio }}
                  </span>
                </div>
                <span style="font-size:12px;color:#909399">AI 建议：{{ selectedProposal?.teaching_style?.theory_practice_ratio }}</span>
              </el-form-item>

              <el-form-item label="额外要求">
                <el-input
                  v-model="extraNotes"
                  type="textarea"
                  :rows="2"
                  size="small"
                  placeholder="选填。例如：弱化数学推导，多给直觉解释；所有代码示例用 Python..."
                  clearable
                />
              </el-form-item>
            </el-form>

            <div style="display:flex;justify-content:flex-end;gap:12px;margin-top:16px">
              <el-button @click="resetSelection">重新选择</el-button>
              <el-button type="primary" :loading="loadingCalibration" @click="goToStep2">
                下一步：经验校准
              </el-button>
            </div>
          </div>
        </div>
      </div>

      <!-- ═══════════════════════════════════════ -->
      <!-- Step 2：经验校准 ★v2.2 新增 -->
      <!-- ═══════════════════════════════════════ -->
      <div v-if="step === 2">
        <div style="display:flex;gap:24px">
          <!-- 左侧：题目区 -->
          <div style="flex:2">
            <div style="margin-bottom:16px;padding:12px 16px;background:#ecf5ff;border-radius:8px">
              <p style="margin:0;font-size:13px;color:#409EFF">
                接下来 5 道题，3 分钟搞定。每题都直接影响课程内容质量——AI 会根据你的选择，
                给真痛点更多笔墨、用真实案例作为教学主线、标注学员最容易犯的错误。
              </p>
            </div>

            <div v-if="loadingCalibration" style="text-align:center;padding:40px 0">
              <el-icon class="is-loading" :size="24"><Loading /></el-icon>
              <p style="color:#909399;margin-top:8px">AI 正在生成校准题...</p>
            </div>

            <div v-else-if="!calibrationQuestions.length" style="text-align:center;padding:40px 0">
              <p style="color:#909399">无法生成校准题，请返回上一步或直接开始生成</p>
              <el-button type="primary" style="margin-top:12px" @click="step = 3">跳过，直接生成</el-button>
            </div>

            <div v-else>
              <!-- 题 1：真痛点（多选） -->
              <div v-for="(q, qi) in calibrationQuestions" :key="q.id"
                style="margin-bottom:20px;padding:16px;background:#fff;border:1px solid #e4e7ed;border-radius:8px">
                <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
                  <strong>题 {{ qi + 1 }}/5：{{ q.title }}</strong>
                  <el-tag size="small" type="info">{{ qi + 1 }}/5</el-tag>
                </div>

                <!-- 多选 -->
                <el-checkbox-group v-if="q.type === 'multi_select'" v-model="(calibrationAnswers as any)[q.id]"
                  style="display:flex;flex-direction:column;gap:8px">
                  <el-checkbox v-for="opt in q.options" :key="opt.id" :label="opt"
                    :value="opt" style="margin-right:0">
                    {{ opt.label }}
                  </el-checkbox>
                </el-checkbox-group>

                <!-- 单选 -->
                <el-radio-group v-else-if="q.type === 'single_select'" v-model="(calibrationAnswers as any)[q.id]"
                  style="display:flex;flex-direction:column;gap:8px">
                  <el-radio v-for="opt in q.options" :key="opt.id" :value="opt" style="margin-right:0">
                    {{ opt.label }}
                  </el-radio>
                </el-radio-group>

                <!-- 排序 -->
                <div v-else-if="q.type === 'ranking'" style="display:flex;flex-direction:column;gap:8px">
                  <p style="font-size:12px;color:#909399;margin:4px 0">拖拽或点击选择前 5 项（按重要性排序）</p>
                  <el-checkbox-group v-model="(calibrationAnswers as any)[q.id]"
                    :max="5" style="display:flex;flex-direction:column;gap:8px">
                    <el-checkbox v-for="opt in q.options" :key="opt.id" :label="opt" :value="opt" style="margin-right:0">
                      {{ opt.label }}
                    </el-checkbox>
                  </el-checkbox-group>
                </div>

                <!-- 跳过选项 -->
                <div style="margin-top:10px;padding-top:8px;border-top:1px dashed #e4e7ed">
                  <el-button text size="small" type="info" @click="skipQuestion(q.id)">
                    {{ q.skip_option || '不清楚 / 跳过' }}
                  </el-button>
                </div>

                <!-- 为什么问这个 -->
                <div style="margin-top:6px;font-size:12px;color:#909399">
                  {{ q.why_ask }}
                </div>
              </div>
            </div>

            <div style="display:flex;justify-content:space-between;margin-top:16px">
              <el-button @click="step = 1">上一步</el-button>
              <div style="display:flex;gap:8px">
                <el-button @click="step = 3">跳过，直接生成</el-button>
                <el-button type="primary" @click="goToStep3">
                  下一步：确认生成
                </el-button>
              </div>
            </div>
          </div>

          <!-- 右侧：经验摘要卡 -->
          <div style="flex:1;min-width:200px">
            <el-card shadow="never" style="background:#fafbfc">
              <template #header>
                <span style="font-size:14px;font-weight:600">经验摘要</span>
              </template>
              <div v-if="answeredCount === 0" style="color:#909399;font-size:13px;text-align:center;padding:20px 0">
                回答题目后，这里会实时显示你的经验贡献
              </div>
              <div v-else>
                <p style="font-size:13px;color:#606266">已答 {{ answeredCount }}/5 题</p>
                <p style="font-size:13px;color:#606266">信息密度：
                  <el-tag :type="confidenceTag" size="small">{{ (answeredCount / 5 * 100).toFixed(0) }}%</el-tag>
                </p>
                <p v-if="answeredCount < 3" style="font-size:12px;color:#e6a23c;margin-top:8px">
                  建议至少回答 3 题以获得更好的课程质量
                </p>
                <p v-else style="font-size:12px;color:#67c23a;margin-top:8px">
                  经验校准良好，AI 会充分使用你的经验数据
                </p>
              </div>
            </el-card>
          </div>
        </div>
      </div>

      <!-- ═══════════════════════════════════════ -->
      <!-- Step 3：确认生成 ★v2.2 新增 -->
      <!-- ═══════════════════════════════════════ -->
      <div v-if="step === 3">
        <div style="max-width:640px;margin:0 auto">
          <h3 style="text-align:center;color:#303133;margin-bottom:20px">确认课程生成配置</h3>

          <el-descriptions :column="1" border style="margin-bottom:20px">
            <el-descriptions-item label="选中方案">
              {{ selectedId }} · {{ selectedProposal?.tagline }}
            </el-descriptions-item>
            <el-descriptions-item label="目标受众">
              {{ selectedProposal?.target_audience?.label }}
              （{{ levelLabel(adjustments.difficulty) }}）
            </el-descriptions-item>
            <el-descriptions-item label="总课时">
              {{ adjustments.total_hours }} 小时
            </el-descriptions-item>
            <el-descriptions-item label="教学风格">
              {{ selectedProposal?.teaching_style?.label }}
            </el-descriptions-item>
            <el-descriptions-item label="理论/实操">
              {{ adjustments.theory_ratio }} : {{ 100 - adjustments.theory_ratio }}
            </el-descriptions-item>
            <el-descriptions-item label="经验校准">
              <el-tag :type="confidenceTag" size="small">
                {{ answeredCount }}/5 题已答
              </el-tag>
              <span v-if="answeredCount === 0" style="margin-left:8px;font-size:12px;color:#909399">
                （已跳过，AI 将基于材料推测）
              </span>
            </el-descriptions-item>
            <el-descriptions-item v-if="extraNotes" label="额外要求">
              {{ extraNotes }}
            </el-descriptions-item>
          </el-descriptions>

          <!-- 低置信度提示 -->
          <el-alert
            v-if="answeredCount < 3 && answeredCount >= 0"
            title="经验校准内容较少"
            type="warning"
            :closable="false"
            show-icon
            style="margin-bottom:20px"
          >
            <template #default>
              <p style="margin:0;font-size:13px">
                你只回答了 {{ answeredCount }}/5 道经验校准题。AI 会基于材料推测真实场景。
                如果你不是这块业务的专家，建议返回上一步补充作答，或邀请一线主管参与校准。
              </p>
            </template>
          </el-alert>

          <!-- 生成中 -->
          <div v-if="submitting" style="text-align:center;padding:40px 0">
            <el-icon class="is-loading" :size="32"><Loading /></el-icon>
            <p style="color:#606266;margin-top:12px">{{ statusMessage }}</p>
          </div>

          <!-- 生成完成 -->
          <el-result
            v-if="generationDone"
            icon="success"
            title="课程生成任务已启动"
            sub-title="AI 正在后台生成课程内容（含课程地图规划 + 经验校准路由分发）。完成后会通过通知提醒你。"
          >
            <template #extra>
              <el-button type="primary" @click="goToTutorial">去学习课程</el-button>
              <el-button @click="router.push('/')">返回首页</el-button>
            </template>
          </el-result>

          <!-- 操作按钮 -->
          <div v-if="!submitting && !generationDone" style="display:flex;justify-content:center;gap:12px">
            <el-button @click="step = 2">上一步</el-button>
            <el-button type="primary" size="large" :loading="submitting" @click="startGeneration">
              确认生成课程
            </el-button>
          </div>
        </div>
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, watch, onMounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Loading } from '@element-plus/icons-vue'
import { blueprintApi, teachingApi } from '@/api'
import type { CourseProposal, CalibrationQuestion } from '@/api'

const router = useRouter()
const route = useRoute()

// 领域选择
const domains = ref<any[]>([])
const domainsLoading = ref(false)
const topicKey = ref('')
const spaceId = ref('')

// 步骤
const step = ref(1)

// Step 1：方案数据
const proposals = ref<CourseProposal[]>([])
const selectedId = ref('')
const loading = ref(false)
const error = ref('')

const adjustments = reactive({
  total_hours: 30,
  difficulty: 'beginner',
  theory_ratio: 50,
})
const extraNotes = ref('')

// Step 2：经验校准
const loadingCalibration = ref(false)
const calibrationQuestions = ref<CalibrationQuestion[]>([])
const calibrationAnswers = ref<Record<string, any>>({})

// Step 3：生成状态
const submitting = ref(false)
const statusMessage = ref('')
const generationDone = ref(false)

const selectedProposal = computed(() =>
  proposals.value.find(p => p.id === selectedId.value)
)

const answeredCount = computed(() => {
  let count = 0
  for (const [qid, answer] of Object.entries(calibrationAnswers.value)) {
    if (answer === 'skip' || answer === '' || answer === null) continue
    if (Array.isArray(answer) && answer.length === 0) continue
    count++
  }
  return count
})

const confidenceTag = computed(() => {
  const ratio = answeredCount.value / 5
  if (ratio >= 0.8) return 'success'
  if (ratio >= 0.6) return 'warning'
  return 'danger'
})

function tagType(id: string) {
  return { A: 'success', B: 'warning', C: '' }[id] || 'info'
}

function levelLabel(level?: string) {
  const map: Record<string, string> = { beginner: '初级', intermediate: '中级', advanced: '高级' }
  return map[level || 'beginner'] || level || '初级'
}

async function loadDomains() {
  domainsLoading.value = true
  try {
    const res = await teachingApi.getSpaces()
    domains.value = (res.data || [])
    const qTopic = route.query.topic as string
    if (qTopic) {
      topicKey.value = qTopic
      const match = domains.value.find((d: any) => d.domain_tag === qTopic)
      if (match) {
        spaceId.value = match.space_id
        await loadProposals()
      }
    }
  } catch (e: any) {
    console.error('Failed to load domains', e)
  } finally {
    domainsLoading.value = false
  }
}

async function onTopicChange() {
  const match = domains.value.find((d: any) => d.domain_tag === topicKey.value)
  spaceId.value = match?.space_id || ''
  selectedId.value = ''
  proposals.value = []
  calibrationQuestions.value = []
  calibrationAnswers.value = {}
  generationDone.value = false
  step.value = 1
  if (spaceId.value) {
    router.replace({ query: { topic: topicKey.value } })
    await loadProposals()
  }
}

async function loadProposals() {
  if (!topicKey.value) return
  loading.value = true
  error.value = ''
  proposals.value = []
  try {
    const res = await blueprintApi.getProposals(topicKey.value)
    proposals.value = res.data?.proposals || []
    if (!proposals.value.length) {
      error.value = 'AI 未能生成课程方案。该主题可能暂时不支持，请稍后重试或联系管理员。'
    }
  } catch (e: any) {
    error.value = e?.response?.data?.detail?.msg || '加载课程方案失败，请稍后重试'
  } finally {
    loading.value = false
  }
}

function selectProposal(id: string) {
  selectedId.value = id
  const p = proposals.value.find(x => x.id === id)
  if (p) {
    adjustments.total_hours = p.course_structure?.estimated_hours || 30
    adjustments.difficulty = p.target_audience?.level || 'beginner'
    const ratio = p.teaching_style?.theory_practice_ratio || '5:5'
    const parts = ratio.split(':')
    adjustments.theory_ratio = parseInt(parts[0]) * 10 || 50
    extraNotes.value = ''
  }
}

function resetSelection() {
  selectedId.value = ''
}

// Step 1 → 2：生成校准题
async function goToStep2() {
  if (!selectedId.value || !spaceId.value) {
    ElMessage.warning('请先选择课程方案')
    return
  }

  step.value = 2
  if (calibrationQuestions.value.length > 0) return  // 已加载过

  loadingCalibration.value = true
  try {
    const res = await blueprintApi.getCalibrationQuestions(topicKey.value, {
      space_id: spaceId.value,
      selected_proposal_id: selectedId.value,
      adjustments: {
        total_hours: adjustments.total_hours,
        difficulty: adjustments.difficulty,
        theory_ratio: adjustments.theory_ratio,
      },
    })
    calibrationQuestions.value = res.data?.questions || []
    // 初始化答案
    for (const q of calibrationQuestions.value) {
      if (q.type === 'multi_select' || q.type === 'ranking') {
        calibrationAnswers.value[q.id] = []
      } else {
        calibrationAnswers.value[q.id] = null
      }
    }
  } catch (e: any) {
    ElMessage.error('生成校准题失败：' + (e?.response?.data?.detail?.msg || '未知错误'))
    calibrationQuestions.value = []
  } finally {
    loadingCalibration.value = false
  }
}

function skipQuestion(qid: string) {
  calibrationAnswers.value[qid] = 'skip'
}

// Step 2 → 3
function goToStep3() {
  step.value = 3
}

// 构建后端所需的校准答案格式
function buildCalibrationPayload(): Record<string, any> {
  const payload: Record<string, any> = {}
  for (const q of calibrationQuestions.value) {
    const answer = calibrationAnswers.value[q.id]
    if (answer === 'skip' || answer === null || answer === undefined) {
      payload[q.id] = q.type === 'multi_select' || q.type === 'ranking' ? [] : 'skip'
    } else if (Array.isArray(answer)) {
      payload[q.id] = answer.map((opt: any) => ({
        id: opt.id,
        label: opt.label,
        entity_id: opt.entity_id || '',
      }))
    } else if (typeof answer === 'object') {
      payload[q.id] = [{
        id: answer.id,
        label: answer.label,
        entity_id: answer.entity_id || '',
      }]
    } else {
      payload[q.id] = 'skip'
    }
  }
  return payload
}

async function startGeneration() {
  if (!selectedId.value || !spaceId.value) return
  submitting.value = true
  generationDone.value = false
  statusMessage.value = '正在保存课程配置...'

  try {
    const res = await blueprintApi.startGeneration(topicKey.value, {
      space_id: spaceId.value,
      selected_proposal_id: selectedId.value,
      adjustments: {
        total_hours: adjustments.total_hours,
        difficulty: adjustments.difficulty,
        theory_ratio: adjustments.theory_ratio,
      },
      extra_notes: extraNotes.value || undefined,
      calibration_answers: answeredCount.value > 0 ? buildCalibrationPayload() : undefined,
      course_map_confirmed: true,
    })
    statusMessage.value = '课程生成任务已启动，AI 正在分析知识结构、规划课程地图、生成教学内容...'
    generationDone.value = true
    ElMessage.success('课程生成任务已启动！')
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail?.msg || '启动生成失败')
  } finally {
    submitting.value = false
  }
}

function goToTutorial() {
  router.push({ path: '/tutorial', query: { topic: topicKey.value } })
}

onMounted(() => {
  loadDomains()
})
</script>

<style scoped>
.proposal-card {
  flex: 1;
  cursor: pointer;
  transition: all 0.2s;
  border: 2px solid transparent;
}
.proposal-card:hover {
  transform: translateY(-2px);
}
.proposal-card.selected {
  border-color: #409EFF;
  background: #ecf5ff;
}
.prop-field {
  display: flex;
  justify-content: space-between;
  margin: 6px 0;
  font-size: 13px;
}
.prop-label {
  color: #909399;
  flex-shrink: 0;
}
.prop-value {
  color: #303133;
  text-align: right;
  font-weight: 500;
}
</style>
