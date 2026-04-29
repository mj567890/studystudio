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
                  :label="d.domain_tag"
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
            <div v-if="tutorial.source==='blueprint' && tutorial.title" class="course-title">
              {{ tutorial.title }}
            </div>
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
        <div v-if="subUpdate.hasUpdate" class="sub-update-banner">
          📢 课程结构已更新（当前 v{{ subUpdate.subscribedVersion }}，最新 v{{ subUpdate.currentVersion }}）
          <el-button size="small" type="primary" plain style="margin-left:12px"
            @click="ackAndReload">查看新版本</el-button>
          <el-button size="small" style="margin-left:6px"
            @click="subUpdate.hasUpdate=false">稍后再说</el-button>
        </div>
        <el-card v-if="currentChapter">
          <template #header>
            <div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:8px">
              <span style="font-size:16px;font-weight:600">{{ currentChapter.title }}</span>
              <div style="display:flex;gap:6px;align-items:center;flex-wrap:wrap">
                <el-tag v-if="adaptiveHint" type="info" size="small">{{ adaptiveHint }}</el-tag>
                <!-- chapter_header_btn_v1 -->
                <el-tag
                  v-if="progress[currentChapter.chapter_id]?.status==='read'"
                  type="success" effect="dark" size="small">
                  🎉 已完成
                </el-tag>
                <el-button
                  v-else
                  size="small" type="primary"
                  @click="startQuiz(currentChapter)">
                  📝 做测验
                </el-button>
                <el-button size="small" :type="progress[currentChapter.chapter_id]?.status==='skipped'?'warning':'default'" @click="markChapter(currentChapter,'skipped')">忽略</el-button>
                <el-button v-if="readMode==='deep'" size="small" plain @click="openSource">📄 查看原文</el-button>
                <el-button
                  size="small" type="warning" plain
                  :loading="refiningChapterId === currentChapter?.chapter_id"
                  @click="refineChapter">✨ 精调本章</el-button>
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
                    <div class="checkpoint-q">
                      <span>⏸</span><span>{{ seg.question }}</span>
                    </div>
                    <div class="checkpoint-hint">{{ seg.hint }}</div>
                  </div>
                </template>
              </div>
            </template>

            <div v-if="readMode!=='skim' && chapterContent.code_example" class="code-example-block">
              <p class="section-label">💻 代码示例</p>
              <div v-html="chapterContent.code_example" class="code-example-body" />
            </div>

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
              :space-id="tutorial?.space_id"
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

          <div v-else-if="currentChapter.content_text" class="content" v-html="renderTerms(currentChapter.content_text)"></div>
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
    <div v-else-if="quizSubmitted" style="max-height:70vh;overflow-y:auto;padding-right:4px"> <!-- quiz_scroll_v1 -->
      <!-- quiz_fix_v2 -->
      <el-result :icon="quizScore>=60?'success':'warning'" :title="`得分 ${quizScore} 分`"
        :sub-title="quizScore>=60?`答对 ${quizCorrect}/${quizTotal} 题，章节已标记完成 🎉`:`答对 ${quizCorrect}/${quizTotal} 题，60分以上自动标记完成`">
        <template #extra>
          <el-button type="primary" @click="quizVisible=false">完成</el-button>
          <el-button @click="pickQuestions">换一套题重做</el-button>
          <el-button type="success" plain @click="quizVisible=false;openReflect()">🧠 写反思巩固</el-button>
          <el-button v-if="quizScore<60" plain
            @click="markChapter(quizChapter,'read');quizVisible=false">
            仍然标记已读
          </el-button>
        </template>
      </el-result>
      <!-- 答题回顾 quiz_fix_v2 -->
      <div style="margin-top:20px;text-align:left">
        <p style="font-size:13px;font-weight:600;color:#303133;margin-bottom:10px">答题回顾</p>
        <div v-for="(q,idx) in quizQuestions" :key="q.question_id+'_r'"
          :style="{background: answersResult[q.question_id] ? '#f0f9eb' : '#fef0f0',
                   borderRadius:'8px', padding:'10px 14px', marginBottom:'8px',
                   borderLeft: '3px solid ' + (answersResult[q.question_id] ? '#67c23a' : '#f56c6c')}">
          <p style="font-size:13px;font-weight:500;margin:0 0 4px">
            {{ idx+1 }}. {{ q.question }}
            <el-tag :type="answersResult[q.question_id]?'success':'danger'" size="small" style="margin-left:6px">
              {{ answersResult[q.question_id] ? '✓ 正确' : '✗ 错误' }}
            </el-tag>
          </p>
          <p style="font-size:12px;color:#606266;margin:2px 0" v-if="userAnswers[q.question_id]">
            你的答案：{{ userAnswers[q.question_id] }}
          </p>
          <p style="font-size:12px;color:#409eff;margin:2px 0"
            v-if="q.type==='single_choice'||q.type==='scenario'||q.type==='true_false'">
            正确答案：{{ q.answer }}
          </p>
          <p style="font-size:12px;color:#909399;margin:4px 0 0" v-if="q.explanation">
            解析：{{ q.explanation }}
          </p>
        </div>
      </div>

      <!-- 掌握度变化 mastery_feedback_v1 -->
      <div v-if="quizMasteryChanges.length" style="margin-top:16px;text-align:left">
        <p style="font-size:13px;font-weight:600;color:#303133;margin-bottom:8px">📊 知识掌握度变化</p>
        <div style="display:flex;flex-wrap:wrap;gap:8px">
          <el-tag v-for="m in quizMasteryChanges" :key="m.entity_id"
            size="small"
            :type="m.correct ? 'success' : 'danger'"
            effect="plain">
            {{ m.entity_name || '知识点' }}
            <span :style="{color: m.correct ? '#67c23a' : '#f56c6c'}">
              {{ m.correct ? '↑' : '↓' }}{{ Math.abs(m.delta).toFixed(2) }}
            </span>
          </el-tag>
        </div>
        <p style="font-size:11px;color:#909399;margin-top:6px">
          {{ quizMasteryChanges.filter(m => m.correct).length }} 项提升，
          {{ quizMasteryChanges.filter(m => !m.correct).length }} 项需复习
        </p>
      </div>

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
<div v-if="hwPopover.visible" class="hw-popover" :style="{ left: hwPopover.x + 'px', top: hwPopover.y + 'px' }">
  <div class="hw-pop-header">
    <span class="hw-pop-name">{{ hwPopover.name }}</span>
    <span class="hw-pop-close" @click="closeHwPopover">✕</span>
  </div>
  <div class="hw-pop-def">{{ hwPopover.definition }}</div>
</div>

  <!-- ── 原文溯源抽屉 ── -->
  <el-drawer v-model="sourceVisible" title="原文对照" direction="rtl"
    size="45%" :destroy-on-close="false">
    <div v-if="sourceLoading" style="text-align:center;padding:40px">
      <el-icon class="is-loading" style="font-size:28px;color:#409eff"><Loading /></el-icon>
      <p style="margin-top:12px;color:#606266">加载原文中…</p>
    </div>
    <div v-else-if="sourcePages.length === 0" style="padding:20px">
      <el-empty description="暂无原文来源（可重新解析文档后查看）" />
    </div>
    <div v-else class="source-body">
      <div v-for="doc in sourceDocs" :key="doc.document_id" class="source-doc">
        <div class="source-doc-header">
          <span>📄</span>
          <span class="source-doc-name">{{ doc.file_name || doc.title }}</span>
        </div>
        <div v-for="chunk in doc.chunks" :key="chunk.chunk_id" class="source-chunk">
          <div v-if="chunk.page_no" class="source-page-num">第 {{ chunk.page_no }} 页</div>
          <div class="source-text">{{ chunk.content }}</div>
        </div>
      </div>
    </div>
  </el-drawer>

</template>

<script setup lang="ts">
import { ref, computed, watch, onMounted, reactive, nextTick } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Loading } from '@element-plus/icons-vue'
import { learnerApi, knowledgeApi, tutorialApi, teachingApi, recommendApi, errorPatternApi, certificateApi } from '@/api'
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
const spaceIdQuery   = ref((route.query.space_id as string) || '')
const tutorial       = ref<any>(null)
const currentChapter = ref<any>(null)
const progress       = ref<Record<string,any>>({})
const readMode       = ref<'skim'|'normal'|'deep'>('normal')

const chapterContent = computed(() => {
  const ch = currentChapter.value
  if (!ch) return null

  // Phase 8：优先使用 API 返回的结构化字段，无 JSON 解析开销
  if (ch.scene_hook || ch.code_example || ch.skim_summary) {
    return {
      full_content:        ch.full_content || ch.content_text || '',
      scene_hook:          ch.scene_hook || '',
      code_example:        ch.code_example || '',
      misconception_block: ch.misconception_block || '',
      skim_summary:        ch.skim_summary || '',
      prereq_adaptive:     ch.prereq_adaptive || '',
    }
  }

  // Fallback：旧数据，从 content_text JSON 解析
  const raw = ch.content_text
  if (!raw) return null
  try {
    const p = JSON.parse(raw)
    if (p.scene_hook || p.skim_summary || p.full_content) return p
  } catch (_) {}
  // JSON 解析失败：做基本的文本清理，避免裸 JSON 结构暴露在页面上
  let cleaned = raw
    .replace(/\u23f8/g, '').replace(/⏸/g, '')     // 去暂停标记
    .replace(/```(\w*)\n([\s\S]*?)```/g, '<pre><code class="language-$1">$2</code></pre>')  // 代码围栏转 HTML
  // 如果看起来是 JSON 字符串（以 { 开头），尝试提取 full_content
  if (raw.trim().startsWith('{')) {
    const m = raw.match(/"full_content"\s*:\s*"([\s\S]*?)(?:"\s*[,}])/)
    if (m) cleaned = m[1].replace(/\\n/g, '\n').replace(/\\"/g, '"')
  }
  return { full_content: cleaned }
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
      segs.push({ type: 'checkpoint', question: question.trim(), hint: hint.trim() })
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
    const res: any = await tutorialApi.getByTopic(topicKey.value, false, spaceIdQuery.value || undefined)
    if (res.code === 200) {
      tutorial.value = res.data
      const list = chapterList.value
      if (list.length) {
        // progress_on_load_v1: 页面加载时立即拉取进度，不等点击章节
        const tid = res.data?.tutorial_id || res.data?.blueprint_id
        if (tid) {
          try {
            const pr: any = await learnerApi.getChapterProgress(tid)
            progress.value = pr.data?.progress || {}
          } catch (_) {}
        }
        // chapter 深链接优先级最高（管理员预览 etc.）
        const chapterFromQuery = route.query.chapter as string
        const lastId = localStorage.getItem('last_chapter_id')
        const savedId = localStorage.getItem(`last_chapter:${topicKey.value}`)
        const target = chapterFromQuery ? list.find((c: any) => c.chapter_id === chapterFromQuery)
          : lastId ? list.find((c: any) => c.chapter_id === lastId)
          : savedId ? list.find((c: any) => c.chapter_id === savedId) : null
        selectChapter(target || list[0])
        if (lastId) localStorage.removeItem('last_chapter_id')
      }
    }
  } finally { loading.value = false }
  checkSubscriptionUpdate()
}

async function selectChapter(ch: any) {
  sourcePages.value = []  // 切换章节时重置原文缓存
  chapterEnterTime.value = Date.now()
  errorPatterns.value = []
  currentChapter.value = ch
  // scroll active chapter into view (admin preview deep-link etc.)
  if (ch?.chapter_id) {
    nextTick(() => {
      const el = document.querySelector('.chapter-item.active')
      if (el) el.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
    })
  }
  // persist_last_chapter: 刷新页面时留在当前章节
  if (topicKey.value && ch?.chapter_id) {
    localStorage.setItem(`last_chapter:${topicKey.value}`, ch.chapter_id)
  }
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
const refiningChapterId = ref<string | null>(null)

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

  // 保护 <pre> 块：不在代码块内做 \n→<br> 转换
  const preBlocks: string[] = []
  let processed = text.replace(/<pre[\s>][\s\S]*?<\/pre>/gi, (match) => {
    preBlocks.push(match)
    return `__PRE_BLOCK_${preBlocks.length - 1}__`
  })

  // 在非代码区域：换行转 <br>，术语高亮
  processed = processed.replace(/\n/g, '<br/>')
  hotwords.forEach((hw: any) => {
    const esc = hw.canonical_name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
    processed = processed.replace(
      new RegExp(`【${esc}】`, 'g'),
      `<span class="hotword" data-hw="${hw.canonical_name}">${hw.canonical_name}</span>`)
  })

  // 还原 <pre> 块
  processed = processed.replace(/__PRE_BLOCK_(\d+)__/g, (_, i) => preBlocks[parseInt(i)] || '')

  return processed
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
const answersResult  = ref<Record<string,boolean>>({}) // quiz_fix_v2
const quizChapter    = ref<any>(null)
const quizMasteryChanges = ref<Array<{entity_id: string; entity_name: string; delta: number; correct: boolean}>>([])
const allQuestions   = ref<any[]>([])
const rubricFeedback = ref<Record<string,any>>({})
/* SUBSCRIPTION_BANNER_INJECTED */
const subUpdate = ref({ hasUpdate: false, subscribedVersion: 0, currentVersion: 0, spaceId: '' })

async function checkSubscriptionUpdate() {
  if (!topicKey.value) return
  try {
    const sid = tutorial.value?.space_id
    if (!sid) return
    const { spaceApi } = await import('@/api/index')
    const res: any = await spaceApi.checkUpdate(sid, topicKey.value)
    if (res.code === 200 && res.data?.has_update) {
      subUpdate.value = { hasUpdate: true, subscribedVersion: res.data.subscribed_version, currentVersion: res.data.current_version, spaceId: sid }
    }
  } catch (_) {}
}

async function ackAndReload() {
  try {
    const { spaceApi } = await import('@/api/index')
    await spaceApi.ackUpdate(subUpdate.value.spaceId, topicKey.value)
  } catch (_) {}
  subUpdate.value.hasUpdate = false
  await loadTutorial()
}

/* HOTWORD_POPOVER_INJECTED */
const hwPopover = ref({ visible: false, name: '', definition: '', x: 0, y: 0 })
function closeHwPopover() { hwPopover.value.visible = false }

const rubricChecking = ref<Record<string,boolean>>({})

function qTypeLabel(type: string) {
  return ({single_choice:'单选',true_false:'判断',short_answer:'简答',scenario:'场景判断',ordering:'排序',generative:'解释'} as any)[type] || '简答'
}

function pickQuestions() {
  const all = allQuestions.value
  const n = Math.max(3, Math.min(15, Math.round(all.length * 0.6)))
  quizQuestions.value = [...all].sort(() => Math.random()-0.5).slice(0, n)
  userAnswers.value = {}; selfEval.value = {}; rubricFeedback.value = {}; answersResult.value = {}; quizSubmitted.value = false; quizMasteryChanges.value = []
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
    // quiz_fix_v2: 记录每题对错
    answersResult.value = Object.fromEntries(answers.map(a => [a.question_id, a.is_correct]))
    const res: any = await learnerApi.submitQuiz({ chapter_id: quizChapter.value.chapter_id, answers })
    quizMasteryChanges.value = res.data?.updated || []
    const correct = answers.filter(a => a.is_correct).length
    quizCorrect.value = correct; quizTotal.value = answers.length
    quizScore.value = answers.length ? Math.round(correct/answers.length*100) : 0
    quizSubmitted.value = true
    // 得分 >= 60 自动标记章节已读
    if (quizScore.value >= 60 && quizChapter.value) {
      const alreadyRead = progress.value[quizChapter.value.chapter_id]?.status === 'read'
      if (!alreadyRead) {
        try { await markChapter(quizChapter.value, 'read') }
        catch (e) { console.error('markChapter failed', e) }
      }
    }
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
const sourceDocs = computed(() => {
  const map = new Map<string, any>()
  for (const s of sourcePages.value) {
    const key = s.document_id || 'unknown'
    if (!map.has(key)) {
      map.set(key, { document_id: key, file_name: s.file_name, title: s.title, chunks: [] })
    }
    map.get(key)!.chunks.push(s)
  }
  return [...map.values()]
})
const sourceVisible  = ref(false)
const sourceLoading  = ref(false)
const sourcePages    = ref<any[]>([])
const reflectForm    = reactive({ own_example: '', misconception: '' })

function openReflect() {
  reflectResult.value = null; reflectForm.own_example = ''; reflectForm.misconception = ''; reflectVisible.value = true
}


async function openSource() {
  if (!currentChapter.value) return
  sourceVisible.value = true
  if (sourcePages.value.length) return
  sourceLoading.value = true
  try {
    const res: any = await teachingApi.getChapterSource(currentChapter.value.chapter_id)
    sourcePages.value = res.data?.pages || []
  } catch {
    sourcePages.value = []
  } finally {
    sourceLoading.value = false
  }
}

async function refineChapter() {
  if (!currentChapter.value) return
  const ch = currentChapter.value
  const result = await (ElMessageBox as any).prompt(
    '输入修改指令，AI 将按你的要求重写本章。\n\n例如："增加实操案例，弱化理论推导"、"加入航空维修安全规范"、"难度下调，适配中职基础"',
    `精调章节：${ch.title}`,
    { inputType: 'textarea', inputRows: 4, confirmButtonText: '执行精调', cancelButtonText: '取消' }
  ).catch(() => null)
  if (!result?.value?.trim()) return
  refiningChapterId.value = ch.chapter_id
  try {
    const { http } = await import('@/api')
    await http.post(`/admin/courses/chapters/${ch.chapter_id}/refine`, {
      instruction: result.value.trim()
    }, { timeout: 180000 })
    ElMessage.success('章节已按你的指令更新')
    // 重新加载课程以获取更新的章节内容
    await loadTutorial()
  } catch (err: any) {
    ElMessage.error('精调失败：' + (err?.response?.data?.msg || err?.message || '未知'))
  } finally {
    refiningChapterId.value = null
  }
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
  document.addEventListener("click", (e: MouseEvent) => {
    const el = (e.target as HTMLElement).closest(".hotword") as HTMLElement | null
    if (!el) { hwPopover.value.visible = false; return }
    const name = el.dataset.hw || ""
    const hw = (currentChapter.value?.hotwords || []).find((h: any) => h.canonical_name === name)
    if (!hw) return
    const rect = el.getBoundingClientRect()
    hwPopover.value = { visible: true, name: hw.canonical_name, definition: hw.short_definition || "暂无定义", x: rect.left, y: rect.bottom + 6 }
  })

  await Promise.all([loadDomains(), loadReadMode()])
  if (topicKey.value) loadTutorial()
})
</script>

<style scoped>
.page { padding: 8px; }
.toc-card { height: calc(100vh - 120px); overflow-y: auto; }
.chapter-list { font-size: 13px; }
.stage-group { margin-bottom: 12px; }
.course-title { font-size: 13px; font-weight: 600; color: #303133; padding: 0 0 10px; border-bottom: 1px solid #ebeef5; margin-bottom: 8px; line-height: 1.4; }
.stage-title { font-size: 11px; color: #909399; padding: 8px 0 4px; letter-spacing: 0.5px; text-transform: uppercase; }
.chapter-item { padding: 6px 8px; border-radius: 4px; cursor: pointer; display: flex; align-items: baseline; gap: 6px; transition: background 0.15s; }
.chapter-item:hover { background: #f5f7fa; }
.chapter-item.active { background: #ecf5ff; color: #409eff; }
.chapter-item.read .ch-st { color: #67c23a; }
.chapter-item.skipped { opacity: 0.5; }
.ch-st { font-size: 10px; min-width: 12px; color: #c0c4cc; }
.scene-hook { background: #f9fafb; border-left: 3px solid #a8c5a0; padding: 11px 14px; border-radius: 0 6px 6px 0; margin-bottom: 14px; font-size: 14px; color: #3a3a3a; display: flex; gap: 8px; align-items: flex-start; }
.misconception-block { background: #fdf6f0; border-left: 3px solid #d4956a; padding: 10px 14px; border-radius: 0 6px 6px 0; margin-bottom: 12px; font-size: 13px; color: #5a4a3a; }
.code-example-block { margin: 16px 0; }
.code-example-block .section-label { font-size: 13px; font-weight: 600; color: #303133; margin-bottom: 8px; }
.code-example-body :deep(pre) { background: #1e1e2e; border-radius: 8px; padding: 16px; overflow-x: auto; margin: 0; }
.code-example-body :deep(pre code) { font-family: 'Fira Code', 'Consolas', 'Monaco', monospace; font-size: 13px; line-height: 1.7; color: #cdd6f4; white-space: pre; }
.para :deep(pre) { background: #f6f8fa; border: 1px solid #e1e4e8; border-radius: 6px; padding: 12px; overflow-x: auto; margin: 8px 0; }
.para :deep(pre code) { font-family: 'Fira Code', 'Consolas', monospace; font-size: 12px; color: #24292e; }
.skim-view { background: #f7f8fa; border-radius: 6px; padding: 12px 16px; margin-bottom: 12px; }
.skim-label { font-size: 12px; color: #909399; margin-bottom: 8px; }
.skim-list { padding-left: 18px; }
.skim-list li { margin-bottom: 6px; font-size: 14px; color: #303133; line-height: 1.6; }
.adaptive-high { background: #f7f8fa; border-left: 3px solid #c5ccd6; border-radius: 0 6px 6px 0; padding: 10px 14px; margin-bottom: 12px; font-size: 13px; color: #606266; }
.content { font-size: 14px; line-height: 1.8; color: #2c2c2c; }
.para { margin-bottom: 10px; }
.checkpoint-bubble { background: #f7f9fc; border: 1px solid #dde3ea; border-radius: 6px; padding: 10px 14px; margin: 14px 0; }
.checkpoint-q { display: flex; align-items: center; gap: 8px; font-size: 14px; font-weight: 500; color: #303133; }
.checkpoint-hint { margin-top: 8px; padding-top: 8px; border-top: 1px solid #e4e8ed; font-size: 13px; color: #5a6270; }
:deep(.hotword) { border-bottom: 1px dashed #409eff; color: #1a7ccc; cursor: pointer; }
.sub-update-banner { background: #ecf5ff; border: 1px solid #b3d8ff; border-radius: 6px; padding: 10px 16px; margin-bottom: 12px; font-size: 13px; color: #303133; display: flex; align-items: center; flex-wrap: wrap; gap: 6px; }
.hw-popover { position: fixed; z-index: 9999; background: #fff; border: 1px solid #d0e8ff; border-radius: 8px; padding: 12px 14px; max-width: 280px; box-shadow: 0 4px 16px rgba(0,0,0,0.12); }
.hw-pop-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
.hw-pop-name { font-weight: 600; font-size: 14px; color: #1a6db5; }
.hw-pop-close { font-size: 12px; color: #909399; cursor: pointer; padding: 2px 4px; }
.hw-pop-close:hover { color: #303133; }
.hw-pop-def { font-size: 13px; color: #606266; line-height: 1.7; }
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
/* source-styles-v2 */
.source-doc { margin-bottom: 24px; }
.source-doc-header {
  font-weight: 600;
  color: #303133;
  margin-bottom: 12px;
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
}
.source-doc-name { color: #409eff; }
.source-chunk { margin-bottom: 14px; }
.source-page-num {
  font-size: 12px;
  color: #909399;
  margin-bottom: 4px;
}
.source-text {
  background: #f5f7fa;
  border-left: 3px solid #409eff;
  padding: 10px 14px;
  font-size: 13px;
  color: #606266;
  line-height: 1.8;
  border-radius: 0 4px 4px 0;
  white-space: pre-wrap;
  word-break: break-word;
}
</style>
