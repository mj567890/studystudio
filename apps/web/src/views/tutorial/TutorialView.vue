<template>
  <div class="tutorial-page">
    <div class="toolbar">
      <el-select
        v-model="selectedTopic"
        filterable
        placeholder="选择领域"
        class="topic-select"
        @change="handleTopicChange"
      >
        <el-option
          v-for="item in topics"
          :key="`${item.space_type}:${item.space_id || 'none'}:${item.topic_key}`"
          :label="`${item.topic_key} · ${item.chapter_count}章`"
          :value="item.topic_key"
        />
      </el-select>

      <el-button :loading="rebuilding" @click="reloadTopic(false)">刷新</el-button>
      <el-button type="primary" :loading="rebuilding" @click="reloadTopic(true)">重新生成教程</el-button>
    </div>

    <div v-if="blueprint" class="summary-card">
      <el-card>
        <template #header>
          <div class="summary-header">
            <span>{{ blueprint.topic_key }}</span>
            <el-tag>{{ blueprint.status }}</el-tag>
            <el-tag type="success">v{{ blueprint.version }}</el-tag>
          </div>
        </template>
        <p class="summary-text">{{ blueprint.skill_goal }}</p>
        <p class="summary-subtext">{{ blueprint.summary }}</p>
      </el-card>
    </div>

    <div class="body">
      <div class="left">
        <el-scrollbar height="calc(100vh - 220px)">
          <div v-if="!blueprint" class="empty-tip">
            请选择领域后加载技能教程。
          </div>
          <div v-else>
            <div
              v-for="stage in blueprint.stages"
              :key="stage.stage_id"
              class="stage-block"
            >
              <div class="stage-title">{{ stage.stage_order }}. {{ stage.title }}</div>
              <div class="stage-objective">{{ stage.objective }}</div>

              <el-button
                v-for="chapter in stage.chapters"
                :key="chapter.chapter_id"
                class="chapter-btn"
                :type="activeChapterId === chapter.chapter_id ? 'primary' : 'default'"
                @click="selectChapter(chapter.chapter_id)"
              >
                <div class="chapter-btn-title">{{ chapter.title }}</div>
                <div class="chapter-btn-sub">{{ chapter.estimated_minutes }} 分钟</div>
              </el-button>
            </div>
          </div>
        </el-scrollbar>
      </div>

      <div class="center">
        <el-card v-if="chapterContent">
          <template #header>
            <div class="chapter-header">
              <div>
                <div class="chapter-title">{{ chapterContent.title }}</div>
                <div class="chapter-objective">{{ chapterContent.objective }}</div>
              </div>
              <el-button text @click="glossaryDrawer = true">查看热词</el-button>
            </div>
          </template>

          <div class="chapter-meta">
            <el-tag type="success">学完可做到：{{ chapterContent.can_do_after }}</el-tag>
          </div>

          <div class="section" v-for="section in chapterContent.sections" :key="section.title">
            <h3>{{ section.title }}</h3>
            <pre class="section-body">{{ section.body }}</pre>
          </div>

          <div class="section">
            <h3>练习任务</h3>
            <pre class="section-body">{{ chapterContent.practice_task }}</pre>
          </div>

          <div class="section">
            <h3>通过标准</h3>
            <pre class="section-body">{{ chapterContent.pass_criteria }}</pre>
          </div>

          <div class="section">
            <h3>本章学习点</h3>
            <ul>
              <li v-for="item in chapterContent.learning_points" :key="item">{{ item }}</li>
            </ul>
          </div>
        </el-card>

        <el-empty v-else description="选择左侧章节查看内容" />
      </div>
    </div>

    <el-drawer v-model="glossaryDrawer" title="本章热词 / 术语解释" size="40%">
      <div v-if="chapterContent?.glossary?.length">
        <el-card
          v-for="item in chapterContent.glossary"
          :key="`${item.link_role}-${item.entity_id}`"
          class="glossary-card"
        >
          <template #header>
            <div class="glossary-header">
              <span>{{ item.canonical_name }}</span>
              <el-tag size="small">{{ item.entity_type || item.link_role }}</el-tag>
            </div>
          </template>
          <p class="glossary-short">{{ item.short_definition }}</p>
          <p class="glossary-detail">{{ item.detailed_explanation }}</p>
        </el-card>
      </div>
      <el-empty v-else description="本章还没有热词解释" />
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { skillBlueprintApi, type SkillBlueprint, type ChapterContent, type TopicCard } from '@/api/skillBlueprint'

const route = useRoute()
const router = useRouter()

const topics = ref<TopicCard[]>([])
const blueprint = ref<SkillBlueprint | null>(null)
const selectedTopic = ref<string>('')
const activeChapterId = ref<string>('')
const chapterContent = ref<ChapterContent | null>(null)
const rebuilding = ref(false)
const glossaryDrawer = ref(false)

async function loadTopics() {
  topics.value = await skillBlueprintApi.listTopics()
  const routeTopic = String(route.query.topic || '')
  if (routeTopic) {
    selectedTopic.value = routeTopic
  } else if (!selectedTopic.value && topics.value.length > 0) {
    selectedTopic.value = topics.value[0].topic_key
  }
}

async function reloadTopic(force: boolean) {
  if (!selectedTopic.value) return
  rebuilding.value = force
  try {
    blueprint.value = force
      ? await skillBlueprintApi.regenerateTopic(selectedTopic.value)
      : await skillBlueprintApi.getTopic(selectedTopic.value, { force: false })

    const firstChapter = blueprint.value.stages?.flatMap((stage) => stage.chapters || [])[0]
    if (firstChapter) {
      await selectChapter(firstChapter.chapter_id)
    } else {
      chapterContent.value = null
      activeChapterId.value = ''
    }

    if (force) {
      ElMessage.success('已按最新知识点重新生成技能教程')
    }
  } catch (error: any) {
    ElMessage.error(error?.response?.data?.detail || '加载教程失败')
  } finally {
    rebuilding.value = false
  }
}

async function selectChapter(chapterId: string) {
  activeChapterId.value = chapterId
  chapterContent.value = await skillBlueprintApi.getChapterContent(chapterId)
}

async function handleTopicChange() {
  await router.replace({ query: { ...route.query, topic: selectedTopic.value } })
  await reloadTopic(false)
}

onMounted(async () => {
  await loadTopics()
  if (selectedTopic.value) {
    await reloadTopic(false)
  }
})
</script>

<style scoped>
.tutorial-page {
  padding: 16px;
}
.toolbar {
  display: flex;
  gap: 12px;
  margin-bottom: 16px;
}
.topic-select {
  width: 320px;
}
.summary-card {
  margin-bottom: 16px;
}
.summary-header {
  display: flex;
  align-items: center;
  gap: 8px;
}
.summary-text {
  font-size: 16px;
  font-weight: 600;
}
.summary-subtext {
  margin-top: 8px;
  color: #666;
}
.body {
  display: grid;
  grid-template-columns: 320px 1fr;
  gap: 16px;
}
.left {
  border-right: 1px solid #eee;
  padding-right: 12px;
}
.stage-block {
  margin-bottom: 16px;
}
.stage-title {
  font-size: 16px;
  font-weight: 700;
}
.stage-objective {
  color: #666;
  margin: 6px 0 10px;
  line-height: 1.5;
}
.chapter-btn {
  width: 100%;
  margin-bottom: 8px;
  height: auto;
  text-align: left;
  justify-content: flex-start;
  white-space: normal;
}
.chapter-btn-title {
  font-weight: 600;
}
.chapter-btn-sub {
  font-size: 12px;
  opacity: 0.7;
}
.chapter-header {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: flex-start;
}
.chapter-title {
  font-size: 20px;
  font-weight: 700;
}
.chapter-objective {
  color: #666;
  margin-top: 6px;
}
.chapter-meta {
  margin-bottom: 12px;
}
.section {
  margin-top: 18px;
}
.section-body {
  white-space: pre-wrap;
  font-family: inherit;
  background: #fafafa;
  padding: 12px;
  border-radius: 8px;
}
.glossary-card {
  margin-bottom: 12px;
}
.glossary-header {
  display: flex;
  justify-content: space-between;
  gap: 8px;
}
.glossary-short {
  font-weight: 600;
}
.glossary-detail {
  color: #555;
  line-height: 1.6;
}
.empty-tip {
  color: #888;
  padding: 24px 8px;
}
</style>
