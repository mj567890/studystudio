<template>
  <div class="page">
    <el-row :gutter="16">
      <el-col :span="6">
        <el-card class="toc-card">
          <template #header>
            <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">
              <el-select v-model="topicKey" placeholder="选择主题" size="small"
                style="flex:1;min-width:120px" :loading="domainsLoading" @change="onTopicChange">
                <el-option v-for="d in domains" :key="d.domain_tag"
                  :label="`${d.domain_tag}（${d.space_type==='global'?'全局':'私有'}）`"
                  :value="d.domain_tag" />
              </el-select>
              <el-select v-model="readMode" size="small" style="width:76px" @change="saveReadMode">
                <el-option label="速览" value="skim" />
                <el-option label="标准" value="normal" />
                <el-option label="精读" value="deep" />
              </el-select>
            </div>
          </template>
          <div v-if="tutorial" class="chapter-list">
            <template v-if="tutorial.source==='blueprint'">
              <div v-for="stage in tutorial.stages" :key="stage.stage_id" class="stage-group">
                <div class="stage-title">{{ stage.title }}</div>
                <div v-for="ch in stage.chapters" :key="ch.chapter_id"
                  class="chapter-item"
                  :class="{active:currentChapter?.chapter_id===ch.chapter_id,read:progress[ch.chapter_id]?.status==='read',skipped:progress[ch.chapter_id]?.status==='skipped'}"
                  @click="selectChapter(ch)">
                  <span class="ch-st">{{ progress[ch.chapter_id]?.status==='read'?'✓':progress[ch.chapter_id]?.status==='skipped'?'—':'○' }}</span>
                  {{ ch.title }}
                </div>
              </div>
            </template>
            <template v-else>
              <div v-for="ch in tutorial.chapter_tree" :key="ch.chapter_id"
                class="chapter-item"
                :class="{active:currentChapter?.chapter_id===ch.chapter_id,read:progress[ch.chapter_id]?.status==='read',skipped:progress[ch.chapter_id]?.status==='skipped'}"
                @click="selectChapter(ch)">
                <span class="ch-st">{{ progress[ch.chapter_id]?.status==='read'?'✓':progress[ch.chapter_id]?.status==='skipped'?'—':'○' }}</span>
                {{ ch.title }}
              </div>
            </template>
          </div>
          <el-skeleton v-else-if="loading" :rows="6" animated />
          <el-empty v-else description="请选择主题" />
        </el-card>
      </el-col>

      <el-col :span="18">
        <el-card v-if="currentChapter">
          <template #header>
            <div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:8px">
              <span style="font-size:16px;font-weight:600">{{ currentChapter.title }}</span>
              <div style="display:flex;gap:6px;align-items:center;flex-wrap:wrap">
                <el-tag v-if="adaptiveHint" type="info" size="small">{{ adaptiveHint }}</el-tag>
                <el-button size="small" :type="progress[currentChapter.chapter_id]?.status==='read'?'success':'default'" @click="markChapter(currentChapter,'read')">
                  {{ progress[currentChapter.chapter_id]?.status==='read'?'✓ 已读':'标记已读' }}
                </el-button>
                <el-button size="small" :type="progress[currentChapter.chapter_id]?.status==='skipped'?'warning':'default'" @click="markChapter(currentChapter,'skipped')">忽略</el-button>
                <el-button
                  v-if="allCompleted"
                  size="small" type="warning"
                  :loading="certLoading"
                  @click="downloadCert"
                >🏆 下载证书</el-button>
              </div>
            </div>
          </template>

          <el-alert v-if="loading" title="内容生成中，请稍后刷新" type="warning" show-icon :closable="false" style="margin-bottom:16px"/>

          <div v-else-if="chapterContent">
            <div v-if="chapterContent.scene_hook" class="scene-hook">
              <span style="font-size:16px">💡</span>
              <span>{{ chapterContent.scene_hook }}</span>
            </div>
            <div v-if="chapterContent.misconception_block" class="misconception-block">
              <span v-html="chapterContent.misconception_block" />
            </div>
            <div v-if="readMode==='skim' && chapterContent.skim_summary" class="skim-view">
              <p class="skim-label">速览要点</p>
              <ul class="skim-list">
                <li v-for="(pt,i) in skimPoints" :key="i">{{ pt }}</li>
              </ul>
            </div>
            <template v-else>
              <div v-if="readMode==='deep' && chapterContent.prereq_adaptive?.if_high" class="adaptive-high">
                <strong>📈 进阶拓展：</strong>{{ chapterContent.prereq_adaptive.if_high }}
              </div>
              <div class="content">
                <template v-for="(seg,idx) in contentSegments" :key="idx">
                  <div v-if="seg.type==='text'" v-html="renderTerms(seg.text)" class="para" />
                  <div v-else class="checkpoint-bubble">
                    <div class="checkpoint-q" @click="seg.open=!seg.open">
                      <span>⏸</span><span>{{ seg.question }}</span>
                      <span class="cp-toggle">{{ (seg.open||readMode==='deep')?'收起':'展开解析' }}</span>
                    </div>
                    <div v-if="seg.open||readMode==='deep'" class="checkpoint-hint">{{ seg.hint }}</div>
                  </div>
                </template>
              </div>
            </template>

            <div v-if="readMode!=='skim' && currentChapter.hotwords?.length" class="relation-section">
              <p class="section-label">本章知识点</p>
              <div class="hotwords">
                <el-tag v-for="hw in currentChapter.hotwords" :key="hw.entity_id" type="info" size="small" :title="hw.short_definition">{{ hw.canonical_name }}</el-tag>
              </div>
            </div>

            <div class="bottom-bar">
              <el-button @click="prevChapter" :disabled="!hasPrev">← 上一章</el-button>
              <div style="display:flex;gap:8px">
                <el-button type="primary" plain @click="goChat">向 AI 提问</el-button>
                <el-button type="warning" @click="startQuiz(currentChapter)">📝 章节测验</el-button>
                <el-button type="success" plain @click="openReflect">🧠 写反思</el-button>
              </div>
              <el-button @click="nextChapter" :disabled="!hasNext">下一章 →</el-button>
            </div>

            <!-- H-5 关联知识推荐 -->
            <div v-if="relatedRecs.length" class="related-section">
              <p class="section-label">完成此章节后，推荐继续学习</p>
              <div class="related-list">
                <div
                  v-for="rec in relatedRecs" :key="rec.chapter_id"
                  class="related-card"
                  @click="jumpToRec(rec)"
                >
                  <div class="related-card-top">
                    <span class="related-chapter">{{ rec.chapter_title }}</span>
                    <el-tag type="info" size="small" effect="plain">{{ rec.stage_title }}</el-tag>
                  </div>
                  <div class="related-unlock">
                    <span class="related-key">{{ rec.source_name }}</span>
                    <span class="related-arrow"> → </span>
                    <span class="related-target">{{ rec.target_name }}</span>
                  </div>
                  <div v-if="rec.target_def" class="related-def">{{ rec.target_def }}</div>
                </div>
              </div>
            </div>

            <WallSection
              v-if="currentChapter"
              :chapter-id="currentChapter.chapter_id"
              :topic-key="topicKey"
            />

            <div class="social-section">
              <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
                <span class="section-label">同学笔记</span>
                <el-button size="small" plain @click="socialNoteVisible=true">+ 发布</el-button>
              </div>
              <div v-if="socialNotes.length" class="social-notes">
                <div v-for="note in socialNotes.slice(0,5)" :key="note.id" class="note-card" :class="note.note_type">
                  <span class="note-badge">{{ note.note_type==='stuck'?'🤔 卡住了':note.note_type==='ai_summary'?'📊 困惑摘要':'💡 经验' }}</span>
                  <span class="note-content">{{ note.content }}</span>
                  <div class="note-meta">
                    <span>{{ note.nickname }}</span>
                    <el-button v-if="!note.is_mine" link size="small" @click="likeNote(note.id)">👍 {{ note.likes }}</el-button>
                  </div>
                </div>
              </div>
              <el-empty v-else description="暂无同学笔记" :image-size="40" />
            </div>
          </div>

          <div v-else-if="currentChapter.content_text" class="content" v-html="renderTerms(currentChapter.content_text)" />
          <el-alert v-else type="info" title="本章内容正在生成，请稍后刷新" show-icon :closable="false" />
        </el-card>
        <el-empty v-else description="从左侧选择章节开始学习" />
      </el-col>
    </el-row>
  </div>

  <!-- 测验弹窗 -->
  <el-dialog v-model="quizVisible" title="章节测验" width="700px" :close-on-click-modal="false">
    <div v-if="quizLoading" style="text-align:center;padding:40px">
      <el-icon class="is-loading" style="font-size:32px;color:#409eff"><Loading /></el-icon>
      <p style="margin-top:12px;color:#606266">正在生成题目…</p>
    </div>
    <div v-else-if="quizSubmitted">
      <el-result :icon="quizScore>=60?'success':'warning'" :title="`得分 ${quizScore} 分`" :sub-title="`答对 ${quizCorrect}/${quizTotal} 题，掌握度已更新`">
        <template #extra>
          <el-button type="primary" @click="quizVisible=false">完成</el-button>
          <el-button @click="pickQuestions">换一套题</el-button>
          <el-button type="success" plain @click="quizVisible=false;openReflect()">🧠 写反思巩固</el-button>
        </template>
      </el-result>
      <div v-if="errorPatterns.length" style="margin-top:16px;text-align:left">
        <p style="font-size:13px;color:#606266;margin-bottom:8px">近期常错知识点：</p>
        <div v-for="ep in errorPatterns" :key="ep.canonical_name"
          style="display:flex;align-items:center;justify-content:space-between;
                 padding:6px 10px;margin-bottom:4px;background:#fff7e6;
                 border:1px solid #ffe0a0;border-radius:6px">
          <span style="font-size:13px;font-weight:500;color:#303133">{{ ep.canonical_name }}</span>
          <span style="font-size:12px;color:#e6a23c">错误 {{ ep.wrong_count }} 次</span>
        </div>
      </div>
    </div>
    <div v-else>
      <div v-for="(q,idx) in quizQuestions" :key="q.question_id" class="quiz-item">
        <p class="q-title">{{ idx+1 }}. 【{{ qTypeLabel(q.type) }}】{{ q.question }}</p>
        <el-radio-group v-if="q.type==='single_choice'" v-model="userAnswers[q.question_id]">
          <div v-for="(opt,key) in q.options" :key="key" style="margin-bottom:6px">
            <el-radio :value="key">{{ key }}. {{ opt }}</el-radio>
          </div>
        </el-radio-group>
        <el-radio-group v-else-if="q.type==='true_false'" v-model="userAnswers[q.question_id]">
          <el-radio value="true">正确</el-radio><el-radio value="false">错误</el-radio>
        </el-radio-group>
        <div v-else-if="q.type==='scenario'">
          <div class="scenario-box">{{ q.scenario }}</div>
          <el-radio-group v-model="userAnswers[q.question_id]">
            <div v-for="(opt,key) in q.options" :key="key" style="margin-bottom:6px">
              <el-radio :value="key">{{ key }}. {{ opt }}</el-radio>
            </div>
          </el-radio-group>
        </div>
        <div v-else>
          <el-input v-model="userAnswers[q.question_id]" type="textarea" :rows="3" placeholder="请用自己的语言解释…" />
          <el-button size="small" style="margin-top:8px" :loading="rubricChecking[q.question_id]" @click="checkRubric(q)">AI 批改</el-button>
          <div v-if="rubricFeedback[q.question_id]" class="rubric-feedback">
            <el-tag :type="rubricFeedback[q.question_id].is_correct?'success':'warning'" size="small">
              {{ Math.round((rubricFeedback[q.question_id].score||0)*100) }} 分
            </el-tag>
            <p class="rb-text">{{ rubricFeedback[q.question_id].feedback }}</p>
          </div>
        </div>
        <div v-if="quizSubmitted" class="explanation">
          {{ q.type==='single_choice'||q.type==='scenario'||q.type==='true_false' ? `答案：${q.answer}　${q.explanation||''}` : '' }}
        </div>
      </div>
      <div style="text-align:right;margin-top:16px">
        <el-button type="primary" :loading="submitting" @click="submitQuiz">提交答案</el-button>
      </div>
    </div>
  </el-dialog>

  <!-- D7 反思弹窗 -->
  <el-dialog v-model="reflectVisible" title="🧠 章末反思" width="500px">
    <div v-if="reflectLoading" style="text-align:center;padding:30px">
      <el-icon class="is-loading" style="font-size:28px;color:#409eff"><Loading /></el-icon>
      <p style="margin-top:10px;color:#606266">AI 批改中…</p>
    </div>
    <div v-else-if="reflectResult">
      <el-alert :type="reflectResult.is_correct?'success':'warning'" :title="`反思评分：${Math.round((reflectResult.ai_score||0)*100)} 分`" show-icon :closable="false" style="margin-bottom:12px" />
      <p><strong>✓ 理解到位：</strong>{{ reflectResult.ai_feedback?.strengths }}</p>
      <p v-if="reflectResult.ai_feedback?.gaps" style="margin-top:8px"><strong>△ 需要补强：</strong>{{ reflectResult.ai_feedback.gaps }}</p>
      <p v-if="reflectResult.ai_feedback?.suggestion" style="margin-top:8px"><strong>💡 建议：</strong>{{ reflectResult.ai_feedback.suggestion }}</p>
      <p v-if="reflectResult.ai_feedback?.corrected_example" style="margin-top:8px;color:#606266"><strong>参考写法：</strong>{{ reflectResult.ai_feedback.corrected_example }}</p>
      <div style="text-align:right;margin-top:16px"><el-button type="primary" @click="reflectVisible=false">完成</el-button></div>
    </div>
    <div v-else>
      <p style="color:#606266;margin-bottom:16px;font-size:14px">用自己的话解释本章核心概念，或举一个你想到的例子，AI 会给出针对性反馈。</p>
      <el-form label-position="top">
        <el-form-item label="你的例子 / 解释（50-200字）">
          <el-input v-model="reflectForm.own_example" type="textarea" :rows="4" placeholder="例如：就像我们公司项目中……" />
        </el-form-item>
        <el-form-item label="你原来有什么误解？（可选）">
          <el-input v-model="reflectForm.misconception" type="textarea" :rows="2" placeholder="例如：我之前以为……其实……" />
        </el-form-item>
      </el-form>
      <div style="text-align:right">
        <el-button @click="reflectVisible=false">取消</el-button>
        <el-button type="primary" :disabled="!reflectForm.own_example.trim()" @click="submitReflect">提交给 AI 批改</el-button>
      </div>
    </div>
  </el-dialog>

  <!-- D4 发布笔记 -->
  <el-dialog v-model="socialNoteVisible" title="发布笔记" width="440px">
    <el-form label-position="top">
      <el-form-item label="笔记类型">
        <el-radio-group v-model="noteForm.note_type">
          <el-radio value="stuck">🤔 我卡在这里了</el-radio>
          <el-radio value="tip">💡 经验分享</el-radio>
        </el-radio-group>
      </el-form-item>
      <el-form-item label="内容">
        <el-input v-model="noteForm.content" type="textarea" :rows="3" placeholder="简要描述（10-200字）" maxlength="200" show-word-limit />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="socialNoteVisible=false">取消</el-button>
      <el-button type="primary" :disabled="noteForm.content.length<10" @click="postSocialNote">发布</el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { ref, computed, watch, onMounted, reactive } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Loading } from '@element-plus/icons-vue'
import { learnerApi, knowledgeApi, tutorialApi, recommendApi, errorPatternApi, certificateApi } from '@/api'
import WallSection from '@/components/WallSection.vue'

async function getNewApis() {
  const mod = await import('@/api')
  return {
    learningModeApi: (mod as any).learningModeApi,
    reflectApi:      (mod as any).reflectApi,
    socialApi:       (mod as any).socialApi,
    rubricApi:       (mod as any).rubricApi,
  }
}

const route  = useRoute()
const router = useRouter()

const relatedRecs    = ref<any[]>([])
const chapterEnterTime = ref<number>(0)
const errorPatterns  = ref<any[]>([])
const loading        = ref(false)
const domainsLoading = ref(false)
const domains        = ref<any[]>([])
const topicKey       = ref((route.query.topic as string) || localStorage.getItem('last_topic') || '')
const tutorial       = ref<any>(null)
const currentChapter = ref<any>(null)
const progress       = ref<Record<string,any>>({})
const readMode       = ref<'skim'|'normal'|'deep'>('normal')

const chapterContent = computed(() => {
  const raw = currentChapter.value?.content_text
  if (!raw) return null
  try {
    const p = JSON.parse(raw)
    if (p.scene_hook || p.skim_summary || p.full_content) return p
  } catch (_) {}
  return { full_content: raw }
})

const adaptiveHint = computed(() => '')

const skimPoints = computed(() => {
  const s = chapterContent.value?.skim_summary
  if (!s) return []
  if (Array.isArray(s)) return s
  return s.split(/[；;]/).filter((x: string) => x.trim())
})

const contentSegments = computed(() => {
  const full = chapterContent.value?.full_content || ''
  if (!full) return []
  const parts = full.split(/<!--CHECKPOINT:(.*?)-->/)
  const segs: any[] = []
  for (let i = 0; i < parts.length; i++) {
    if (i % 2 === 0) {
      if (parts[i].trim()) segs.push({ type: 'text', text: parts[i] })
    } else {
      const [question, hint = ''] = parts[i].split('|')
      segs.push({ type: 'checkpoint', question: question.trim(), hint: hint.trim(), open: readMode.value === 'deep' })
    }
  }
  return segs
})

const chapterList = computed<any[]>(() => {
  if (!tutorial.value) return []
  if (tutorial.value.source === 'blueprint')
    return tutorial.value.stages?.flatMap((s: any) => s.chapters || []) || []
  return tutorial.value.chapter_tree || []
})

const currentIndex = computed(() => chapterList.value.findIndex(c => c.chapter_id === currentChapter.value?.chapter_id))
const hasPrev = computed(() => currentIndex.value > 0)
const hasNext = computed(() => currentIndex.value < chapterList.value.length - 1)

async function loadDomains() {
  domainsLoading.value = true
  try {
    const res: any = await knowledgeApi.getDomains()
    domains.value = res.data?.domains || []
  } finally { domainsLoading.value = false }
}

async function loadReadMode() {
  try {
    const local = localStorage.getItem('read_mode') as any
    if (local) { readMode.value = local; return }
    const { learningModeApi } = await getNewApis()
    if (!learningModeApi) return
    const res: any = await learningModeApi.get()
    readMode.value = res.data?.read_mode || 'normal'
  } catch (_) {}
}

async function saveReadMode(mode: string) {
  localStorage.setItem('read_mode', mode)
  try {
    const { learningModeApi } = await getNewApis()
    if (learningModeApi) await learningModeApi.set(mode as any)
  } catch (_) {}
}

async function loadTutorial() {
  if (!topicKey.value) return
  loading.value = true
  tutorial.value = null
  currentChapter.value = null
  localStorage.setItem('last_topic', topicKey.value)
  try {
    const res: any = await tutorialApi.getByTopic(topicKey.value)
    if (res.code === 200) {
      tutorial.value = res.data
      const list = chapterList.value
      if (list.length) {
        const lastId = localStorage.getItem('last_chapter_id')
        const target = lastId ? list.find((c: any) => c.chapter_id === lastId) : null
        selectChapter(target || list[0])
        if (target) localStorage.removeItem('last_chapter_id')
      }
    }
  } finally { loading.value = false }
}

async function selectChapter(ch: any) {
  chapterEnterTime.value = Date.now()
  errorPatterns.value = []
  currentChapter.value = ch
  const tid = tutorial.value?.tutorial_id || tutorial.value?.blueprint_id
  if (tid) {
    try {
      const res: any = await learnerApi.getChapterProgress(tid)
      progress.value = res.data?.progress || {}
    } catch (_) {}
  }
  loadSocialNotes(ch.chapter_id)
}

function onTopicChange() { loadTutorial() }
function prevChapter() { if (hasPrev.value) selectChapter(chapterList.value[currentIndex.value-1]) }
function nextChapter() { if (hasNext.value) selectChapter(chapterList.value[currentIndex.value+1]) }

function jumpToRec(rec: any) {
  if (!tutorial.value) return
  const allChapters = tutorial.value.source === 'blueprint'
    ? tutorial.value.stages?.flatMap((s: any) => s.chapters) || []
    : tutorial.value.chapter_tree || []
  const target = allChapters.find((c: any) => c.chapter_id === rec.chapter_id)
  if (target) selectChapter(target)
}

async function markChapter(chapter: any, newStatus: string) {
  if (!tutorial.value?.tutorial_id && !tutorial.value?.blueprint_id) return
  const current = progress.value[chapter.chapter_id]?.status
  const status = current === newStatus ? null : newStatus
  const durationSec = chapterEnterTime.value
    ? Math.round((Date.now() - chapterEnterTime.value) / 1000)
    : 0
  await learnerApi.markChapter({
    tutorial_id:      tutorial.value.tutorial_id || tutorial.value.blueprint_id || '',
    chapter_id:       chapter.chapter_id,
    completed:        status === 'read',
    status:           status ?? 'unread',
    duration_seconds: durationSec,
  })
  if (status) {
    progress.value[chapter.chapter_id] = { status, completed: status==='read' }
    ElMessage.success(status==='read' ? '已标记为已读' : '已标记为忽略')
    if (status === 'read') {
      relatedRecs.value = []
      try {
        const res: any = await recommendApi.getRelated(chapter.chapter_id)
        relatedRecs.value = res.data?.recommendations || []
      } catch { /* 推荐加载失败不阻断主流程 */ }
    } else {
      relatedRecs.value = []
    }
  } else {
    delete progress.value[chapter.chapter_id]
    ElMessage.success('已取消标记')
  }
}

const certLoading = ref(false)

const allCompleted = computed(() => {
  const all = tutorial.value?.stages?.flatMap((s: any) => s.chapters || []) || []
  if (all.length === 0) return false
  return all.every((ch: any) => progress.value[ch.chapter_id]?.status === 'read')
})

async function downloadCert() {
  if (!topicKey.value) return
  certLoading.value = true
  try {
    const res: any = await certificateApi.download(topicKey.value)
    const blob = res instanceof Blob ? res : new Blob([res], { type: 'application/pdf' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `certificate_${topicKey.value}.pdf`
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    setTimeout(() => URL.revokeObjectURL(url), 1000)
    ElMessage.success('证书下载成功')
  } catch (e: any) {
    const msg = e?.response?.data?.detail?.msg || '尚未完成全部章节'
    ElMessage.warning(msg)
  } finally {
    certLoading.value = false
  }
}

function goChat() {
  if (currentChapter.value?.chapter_id) {
    localStorage.setItem('last_chapter_id', currentChapter.value.chapter_id)
  }
  router.push({ path: '/chat', query: {
    topic: topicKey.value,
    chapter_id: currentChapter.value?.chapter_id || '',
    chapter:    currentChapter.value?.title || '',
  }})
}

function renderTerms(text: string): string {
  if (!text) return ''
  const hotwords = currentChapter.value?.hotwords || []
  let result = text.replace(/\n/g, '<br/>')
  hotwords.forEach((hw: any) => {
    const esc = hw.canonical_name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
    result = result.replace(
      new RegExp(`【${esc}】`, 'g'),
      `<span class="hotword" title="${hw.short_definition||''}">${hw.canonical_name}</span>`)
  })
  return result
}

const quizVisible    = ref(false)
const quizLoading    = ref(false)
const quizSubmitted  = ref(false)
const submitting     = ref(false)
const quizQuestions  = ref<any[]>([])
const userAnswers    = ref<Record<string,any>>({})
const selfEval       = ref<Record<string,boolean>>({})
const quizScore      = ref(0)
const quizCorrect    = ref(0)
const quizTotal      = ref(0)
const quizChapter    = ref<any>(null)
const allQuestions   = ref<any[]>([])
const rubricFeedback = ref<Record<string,any>>({})
const rubricChecking = ref<Record<string,boolean>>({})

function qTypeLabel(type: string) {
  return ({single_choice:'单选',true_false:'判断',short_answer:'简答',scenario:'场景判断',ordering:'排序',generative:'解释'} as any)[type] || '简答'
}

function pickQuestions() {
  const all = allQuestions.value
  const n = Math.max(3, Math.min(15, Math.round(all.length * 0.6)))
  quizQuestions.value = [...all].sort(() => Math.random()-0.5).slice(0, n)
  userAnswers.value = {}; selfEval.value = {}; rubricFeedback.value = {}; quizSubmitted.value = false
}

async function startQuiz(chapter: any) {
  quizChapter.value = chapter; quizVisible.value = true; quizLoading.value = true; quizSubmitted.value = false
  try {
    const res: any = await learnerApi.getChapterQuiz(chapter.chapter_id)
    allQuestions.value = res.data?.questions || []
    pickQuestions()
  } finally { quizLoading.value = false }
}

async function checkRubric(q: any) {
  if (!userAnswers.value[q.question_id]) return
  rubricChecking.value[q.question_id] = true
  try {
    const { rubricApi } = await getNewApis()
    if (!rubricApi) return
    const res: any = await rubricApi.check({
      question_id: q.question_id,
      ai_rubric:   q.ai_rubric || q.answer || '回答需包含核心概念',
      answer:      userAnswers.value[q.question_id],
    })
    rubricFeedback.value[q.question_id] = res.data
  } finally { rubricChecking.value[q.question_id] = false }
}

async function submitQuiz() {
  submitting.value = true
  try {
    const answers = quizQuestions.value.map(q => {
      let is_correct = false
      if (q.type==='single_choice'||q.type==='scenario') is_correct = userAnswers.value[q.question_id]===q.answer
      else if (q.type==='true_false') is_correct = String(userAnswers.value[q.question_id])===String(q.answer)
      else is_correct = rubricFeedback.value[q.question_id]?.is_correct ? rubricFeedback.value[q.question_id].is_correct : selfEval.value[q.question_id] ?? false
      return { question_id: q.question_id, entity_id: q.entity_id||'', type: q.type, is_correct }
    })
    await learnerApi.submitQuiz({ chapter_id: quizChapter.value.chapter_id, answers })
    const correct = answers.filter(a => a.is_correct).length
    quizCorrect.value = correct; quizTotal.value = answers.length
    quizScore.value = answers.length ? Math.round(correct/answers.length*100) : 0
    quizSubmitted.value = true
    // H-6 加载错题模式
    try {
      const ep: any = await errorPatternApi.get()
      errorPatterns.value = (ep.data?.patterns || []).slice(0, 5)
    } catch { /* 静默处理 */ }
  } finally { submitting.value = false }
}

const reflectVisible = ref(false)
const reflectLoading = ref(false)
const reflectResult  = ref<any>(null)
const reflectForm    = reactive({ own_example: '', misconception: '' })

function openReflect() {
  reflectResult.value = null; reflectForm.own_example = ''; reflectForm.misconception = ''; reflectVisible.value = true
}

async function submitReflect() {
  if (!reflectForm.own_example.trim()) return
  reflectLoading.value = true
  try {
    const { reflectApi } = await getNewApis()
    if (!reflectApi) { ElMessage.warning('反思接口未就绪'); return }
    const res: any = await reflectApi.submit({
      chapter_id: currentChapter.value.chapter_id,
      own_example: reflectForm.own_example,
      misconception: reflectForm.misconception,
    })
    reflectResult.value = { ai_score: res.data.ai_score, ai_feedback: res.data.ai_feedback, is_correct: (res.data.ai_score||0) >= 0.6 }
    ElMessage.success('反思已提交')
  } finally { reflectLoading.value = false }
}

const socialNotes       = ref<any[]>([])
const socialNoteVisible = ref(false)
const noteForm          = reactive({ note_type: 'tip', content: '' })

async function loadSocialNotes(chapterId: string) {
  try {
    const { socialApi } = await getNewApis()
    if (!socialApi) return
    const res: any = await socialApi.getNotes(chapterId)
    socialNotes.value = res.data?.notes || []
  } catch (_) {}
}

async function likeNote(noteId: string) {
  try {
    const { socialApi } = await getNewApis()
    if (!socialApi) return
    await socialApi.likeNote(noteId)
    const n = socialNotes.value.find(x => x.id===noteId)
    if (n) n.likes++
  } catch (_) {}
}

async function postSocialNote() {
  if (noteForm.content.length < 10) return
  try {
    const { socialApi } = await getNewApis()
    if (!socialApi) { ElMessage.warning('笔记接口未就绪'); return }
    await socialApi.postNote({
      tutorial_id: tutorial.value?.tutorial_id || tutorial.value?.blueprint_id || '',
      chapter_id: currentChapter.value.chapter_id,
      note_type: noteForm.note_type,
      content: noteForm.content,
      is_public: true,
    })
    ElMessage.success('笔记已发布')
    socialNoteVisible.value = false
    noteForm.content = ''
    await loadSocialNotes(currentChapter.value.chapter_id)
  } catch (_) { ElMessage.error('发布失败') }
}

watch(() => route.query.topic, (next) => {
  topicKey.value = (next as string) || ''
  if (topicKey.value) loadTutorial()
})

onMounted(async () => {
  await Promise.all([loadDomains(), loadReadMode()])
  if (topicKey.value) loadTutorial()
})
</script>

<style scoped>
.page { padding: 8px; }
.toc-card { height: calc(100vh - 120px); overflow-y: auto; }
.chapter-list { font-size: 13px; }
.stage-group { margin-bottom: 12px; }
.stage-title { font-size: 11px; color: #909399; padding: 8px 0 4px; letter-spacing: 0.5px; text-transform: uppercase; }
.chapter-item { padding: 6px 8px; border-radius: 4px; cursor: pointer; display: flex; align-items: baseline; gap: 6px; transition: background 0.15s; }
.chapter-item:hover { background: #f5f7fa; }
.chapter-item.active { background: #ecf5ff; color: #409eff; }
.chapter-item.read .ch-st { color: #67c23a; }
.chapter-item.skipped { opacity: 0.5; }
.ch-st { font-size: 10px; min-width: 12px; color: #c0c4cc; }
.scene-hook { background: #f0f9eb; border-left: 3px solid #67c23a; padding: 12px 14px; border-radius: 0 6px 6px 0; margin-bottom: 16px; font-size: 14px; color: #304156; display: flex; gap: 8px; align-items: flex-start; }
.misconception-block { background: #fef0f0; border-left: 3px solid #f56c6c; padding: 10px 14px; border-radius: 0 6px 6px 0; margin-bottom: 14px; font-size: 13px; color: #606266; }
.skim-view { background: #fafafa; border: 1px solid #ebeef5; border-radius: 6px; padding: 14px 18px; margin-bottom: 12px; }
.skim-label { font-size: 12px; color: #909399; margin-bottom: 8px; }
.skim-list { padding-left: 18px; }
.skim-list li { margin-bottom: 6px; font-size: 14px; color: #303133; line-height: 1.6; }
.adaptive-high { background: #f4f4f5; border-radius: 6px; padding: 10px 14px; margin-bottom: 12px; font-size: 13px; color: #73767a; }
.content { font-size: 14px; line-height: 1.9; color: #303133; }
.para { margin-bottom: 12px; }
.checkpoint-bubble { background: #ecf5ff; border: 1px dashed #a0cfff; border-radius: 8px; padding: 10px 14px; margin: 16px 0; }
.checkpoint-q { cursor: pointer; display: flex; align-items: center; gap: 8px; user-select: none; font-size: 14px; }
.cp-toggle { margin-left: auto; font-size: 12px; color: #409eff; }
.checkpoint-hint { margin-top: 10px; padding-top: 10px; border-top: 1px solid #c6e2ff; font-size: 13px; color: #606266; }
:deep(.hotword) { border-bottom: 1px dashed #409eff; color: #1a7ccc; cursor: help; }
.hotwords { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 6px; }
.relation-section { margin-top: 20px; padding-top: 14px; border-top: 1px solid #f2f6fc; }
.section-label { font-size: 12px; color: #909399; margin-bottom: 4px; }
.bottom-bar { margin-top: 24px; padding-top: 16px; border-top: 1px solid #eee; display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 8px; }
.related-section { margin-top: 24px; padding-top: 16px; border-top: 1px solid #f0f0f0; }
.related-list { display: flex; flex-direction: column; gap: 8px; margin-top: 8px; }
.related-card { background: #f0f7ff; border: 1px solid #d0e8ff; border-radius: 8px; padding: 10px 14px; cursor: pointer; transition: background .15s; }
.related-card:hover { background: #e0f0ff; }
.related-card-top { display: flex; align-items: center; justify-content: space-between; margin-bottom: 4px; }
.related-chapter { font-size: 13px; font-weight: 600; color: #1a6db5; }
.related-unlock { font-size: 12px; color: #606266; margin-bottom: 2px; }
.related-key { color: #409eff; font-weight: 500; }
.related-arrow { color: #909399; }
.related-target { color: #67c23a; font-weight: 500; }
.related-def { font-size: 11px; color: #909399; }
.social-section { margin-top: 20px; padding-top: 16px; border-top: 1px solid #eee; }
.social-notes { display: flex; flex-direction: column; gap: 8px; }
.note-card { background: #fafafa; border: 0.5px solid #ebeef5; border-radius: 8px; padding: 10px 12px; font-size: 13px; }
.note-card.stuck { background: #fdf6ec; border-color: #faecd8; }
.note-card.ai_summary { background: #ecf5ff; border-color: #d9ecff; }
.note-badge { font-size: 11px; margin-right: 6px; }
.note-content { color: #303133; }
.note-meta { margin-top: 6px; display: flex; justify-content: space-between; align-items: center; font-size: 11px; color: #c0c4cc; }
.quiz-item { margin-bottom: 24px; padding-bottom: 20px; border-bottom: 1px solid #eee; }
.q-title { font-weight: 600; margin-bottom: 10px; line-height: 1.5; }
.scenario-box { background: #f8f9fa; border: 1px solid #e9ecef; border-radius: 6px; padding: 10px; margin-bottom: 10px; font-size: 13px; color: #495057; line-height: 1.6; }
.explanation { background: #f4f4f5; border-radius: 4px; padding: 8px 10px; font-size: 13px; color: #606266; margin-top: 8px; }
.rubric-feedback { margin-top: 8px; padding: 8px 10px; background: #f0f9eb; border-radius: 6px; font-size: 13px; }
.rb-text { color: #606266; margin-top: 4px; }
</style>
