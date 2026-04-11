<template>
  <div class="page">
    <el-card>
      <template #header>定位自检</template>

      <div v-if="step === 'input'" class="step-input">
        <p class="tip">选择学习主题，系统为你生成定位题目</p>
        <el-select v-model="topicKey" placeholder="选择主题" filterable
          size="large" style="width:360px" :loading="domainsLoading">
          <el-option v-for="d in domains" :key="d.domain_tag"
            :label="`${d.domain_tag}（${d.entity_count}个知识点）`"
            :value="d.domain_tag" />
        </el-select>
        <el-button type="primary" size="large" :loading="loading"
          style="margin-left:12px" :disabled="!topicKey" @click="loadQuiz">
          开始自检
        </el-button>
      </div>

      <div v-else-if="step === 'quiz'">
        <el-alert v-if="quiz?.is_fallback" type="info" show-icon :closable="false"
          title="题库生成中，当前为简化版题目" style="margin-bottom:16px" />
        <div v-for="(q, idx) in quiz?.questions" :key="q.question_id" class="question">
          <p class="q-title">{{ idx + 1 }}. {{ q.stem }}</p>
          <el-radio-group v-model="answers[q.question_id]">
            <el-radio v-for="opt in q.options" :key="opt" :value="opt.charAt(0)"
              style="display:block;margin:6px 0">{{ opt }}</el-radio>
          </el-radio-group>
        </div>
        <el-button type="primary" size="large" :loading="loading"
          style="margin-top:20px" @click="submit">提交答题</el-button>
      </div>

      <div v-else-if="step === 'result'" class="step-result">
        <el-result icon="success" title="自检完成！"
          sub-title="系统已根据你的答题情况初始化知识掌握度">
          <template #extra>
            <el-descriptions :column="1" border style="width:360px;margin:0 auto 20px">
              <el-descriptions-item v-for="(score, domain) in result?.domain_scores"
                :key="domain" :label="String(domain)">
                <el-progress :percentage="Math.round(Number(score)*100)" :stroke-width="8" />
              </el-descriptions-item>
            </el-descriptions>
            <el-button type="primary" @click="router.push({ path:'/gaps', query:{topic:topicKey} })">
              查看知识漏洞
            </el-button>
            <el-button @click="router.push({ path:'/path', query:{topic:topicKey} })">
              获取学习路径
            </el-button>
          </template>
        </el-result>
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { learnerApi, knowledgeApi } from '@/api'

const router   = useRouter()
const route    = useRoute()
const loading  = ref(false)
const domainsLoading = ref(false)
const step     = ref<'input'|'quiz'|'result'>('input')
const topicKey = ref((route.query.topic as string) || '')
const quiz     = ref<any>(null)
const answers  = ref<Record<string, string>>({})
const result   = ref<any>(null)
const domains  = ref<any[]>([])

async function loadDomains() {
  domainsLoading.value = true
  try {
    const res: any = await knowledgeApi.getDomains()
    domains.value = res.data?.domains || []
  } finally { domainsLoading.value = false }
}

async function loadQuiz() {
  if (!topicKey.value) { ElMessage.warning('请选择主题'); return }
  loading.value = true
  try {
    const res: any = await learnerApi.getPlacementQuiz(topicKey.value)
    quiz.value = res.data
    step.value = 'quiz'
  } finally { loading.value = false }
}

async function submit() {
  const unanswered = quiz.value?.questions?.filter((q: any) => !answers.value[q.question_id])
  if (unanswered?.length) { ElMessage.warning('请完成所有题目'); return }
  loading.value = true
  try {
    const answerList = quiz.value.questions.map((q: any) => ({
      question_id: q.question_id, selected_option: answers.value[q.question_id],
      domain: q.domain, difficulty: q.difficulty, is_fallback: quiz.value.is_fallback,
      is_correct: answers.value[q.question_id] === 'A',
    }))
    const res: any = await learnerApi.submitPlacementResult({ topic_key: topicKey.value, answers: answerList })
    result.value = res.data
    step.value = 'result'
  } finally { loading.value = false }
}

onMounted(() => { loadDomains() })
</script>

<style scoped>
.page { padding: 8px; }
.step-input { text-align: center; padding: 40px 0; }
.tip { color: #606266; margin-bottom: 24px; font-size: 15px; }
.question { margin-bottom: 24px; padding: 16px; background: #f9f9f9; border-radius: 8px; }
.q-title  { font-weight: 500; margin-bottom: 12px; }
</style>
