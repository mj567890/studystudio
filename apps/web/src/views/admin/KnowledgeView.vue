<template>
  <div class="knowledge-view">
    <div class="toolbar">
      <el-button type="primary" @click="loadTopics">刷新领域蓝图</el-button>
    </div>

    <el-table :data="topics" stripe>
      <el-table-column prop="topic_key" label="领域" min-width="160" />
      <el-table-column prop="chapter_count" label="教程章节数" width="120" />
      <el-table-column prop="approved_entity_count" label="已审核术语数" width="120" />
      <el-table-column prop="version" label="蓝图版本" width="100" />
      <el-table-column prop="status" label="状态" width="100" />
      <el-table-column label="技能目标" min-width="260">
        <template #default="{ row }">
          <div class="goal-cell">{{ row.skill_goal }}</div>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="260">
        <template #default="{ row }">
          <el-button size="small" @click="openTutorial(row.topic_key)">查看教程</el-button>
          <el-button size="small" type="primary" :loading="busyTopic === row.topic_key" @click="rebuild(row.topic_key)">
            重建蓝图
          </el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-empty v-if="!topics.length" description="还没有可用的技能蓝图" />
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { skillBlueprintApi, type TopicCard } from '@/api/skillBlueprint'

const router = useRouter()
const topics = ref<TopicCard[]>([])
const busyTopic = ref('')

async function loadTopics() {
  topics.value = await skillBlueprintApi.listTopics()
}

function openTutorial(topicKey: string) {
  router.push({ path: '/tutorial', query: { topic: topicKey } })
}

async function rebuild(topicKey: string) {
  busyTopic.value = topicKey
  try {
    await skillBlueprintApi.regenerateTopic(topicKey)
    ElMessage.success('蓝图已重建')
    await loadTopics()
  } catch (error: any) {
    ElMessage.error(error?.response?.data?.detail || '蓝图重建失败')
  } finally {
    busyTopic.value = ''
  }
}

onMounted(async () => {
  await loadTopics()
})
</script>

<style scoped>
.knowledge-view {
  padding: 16px;
}
.toolbar {
  margin-bottom: 16px;
}
.goal-cell {
  line-height: 1.5;
}
</style>
