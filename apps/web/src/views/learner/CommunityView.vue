<template>
  <div class="page">
    <div class="page-header">
      <div>
        <h2 style="margin:0 0 4px">发现课程</h2>
        <span style="color:#888;font-size:13px">社区公开的学习资料，加入即可学习</span>
      </div>
      <el-input
        v-model="keyword"
        placeholder="搜索课程名称"
        clearable
        style="width:220px"
        @input="onSearch"
      >
        <template #prefix><el-icon><Search /></el-icon></template>
      </el-input>
    </div>

    <div v-if="loading" style="padding:40px 0">
      <el-skeleton :rows="3" animated />
    </div>

    <el-empty
      v-else-if="filtered.length === 0"
      description="暂无公开课程，快去「我的课程」将课程设为公开吧"
      style="padding:60px 0"
    />

    <div v-else class="card-grid">
      <el-card
        v-for="space in filtered"
        :key="space.space_id"
        class="course-card"
        shadow="hover"
      >
        <div class="course-name">{{ space.name }}</div>
        <div class="course-desc">{{ space.description || '暂无介绍' }}</div>
        <div class="course-meta">
          <span>👤 {{ space.owner_nickname }}</span>
          <span>📚 {{ space.entity_count }} 个知识点</span>
          <span>👥 {{ space.member_count }} 人学习</span>
        </div>
        <div class="course-footer">
          <el-tag
            size="small"
            :type="space.blueprint_status === 'published' ? 'success' : 'info'"
          >
            {{ space.blueprint_status === 'published' ? '课程已就绪' : '生成中' }}
          </el-tag>
          <el-button
            v-if="space.is_member"
            size="small"
            type="primary"
            @click="goLearn(space)"
          >
            继续学习 →
          </el-button>
          <el-button
            v-else
            size="small"
            type="primary"
            plain
            :loading="joiningId === space.space_id"
            @click="joinSpace(space)"
          >
            加入学习
          </el-button>
        </div>
      </el-card>
    </div>

    <div v-if="total > pageSize" style="margin-top:24px;display:flex;justify-content:center">
      <el-pagination
        v-model:current-page="page"
        :page-size="pageSize"
        :total="total"
        layout="prev, pager, next"
        @current-change="load"
      />
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { spaceApi } from '@/api'

const router   = useRouter()
const loading  = ref(false)
const spaces   = ref<any[]>([])
const total    = ref(0)
const page     = ref(1)
const pageSize = 24
const keyword  = ref('')
const joiningId = ref('')

const filtered = computed(() => {
  if (!keyword.value) return spaces.value
  const kw = keyword.value.toLowerCase()
  return spaces.value.filter((s: any) =>
    s.name.toLowerCase().includes(kw) ||
    (s.description || '').toLowerCase().includes(kw)
  )
})

async function load() {
  loading.value = true
  try {
    const offset = (page.value - 1) * pageSize
    const res: any = await spaceApi.listPublic(pageSize, offset)
    spaces.value = res.data?.spaces || []
    total.value  = res.data?.total  || 0
  } catch {
    ElMessage.error('加载失败')
  } finally {
    loading.value = false
  }
}

function onSearch() {
  page.value = 1
}

async function joinSpace(space: any) {
  joiningId.value = space.space_id
  try {
    const res: any = await spaceApi.joinPublic(space.space_id)
    const d = res.data
    if (d.already_member) {
      ElMessage.info(`你已经是「${d.space_name}」的成员`)
    } else {
      ElMessage.success(`已加入「${d.space_name}」，快去学习吧`)
    }
    // 刷新列表，is_member 状态会更新
    await load()
  } catch {
    ElMessage.error('加入失败，请稍后重试')
  } finally {
    joiningId.value = ''
  }
}

function goLearn(space: any) {
  router.push({ path: '/tutorial', query: { topic: space.name, space_id: space.space_id } })
}

onMounted(load)
</script>

<style scoped>
.page { padding: 8px; }
.page-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 20px;
}
.card-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 16px;
}
.course-card { cursor: default; }
.course-name {
  font-size: 16px;
  font-weight: 600;
  color: #303133;
  margin-bottom: 6px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.course-desc {
  font-size: 13px;
  color: #606266;
  margin-bottom: 10px;
  line-height: 1.5;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  min-height: 40px;
}
.course-meta {
  display: flex;
  gap: 12px;
  font-size: 12px;
  color: #909399;
  margin-bottom: 12px;
  flex-wrap: wrap;
}
.course-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
</style>
