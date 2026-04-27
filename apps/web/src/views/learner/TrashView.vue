<template>
  <div class="page">
    <el-page-header @back="$router.push('/spaces')" content="回收站" style="margin-bottom:12px">
      <template #extra>
        <el-popconfirm
          title="确定要清空回收站吗？所有无 fork 引用的空间将被彻底删除，不可恢复。"
          @confirm="doEmptyTrash"
        >
          <template #reference>
            <el-button size="small" type="danger" :loading="emptying">清空回收站</el-button>
          </template>
        </el-popconfirm>
      </template>
    </el-page-header>

    <el-card v-loading="loading">
      <template #header>
        <span>已删除的空间</span>
        <el-tag size="small" type="info" style="margin-left:8px">{{ total }}</el-tag>
      </template>

      <el-table :data="spaces" size="small">
        <el-table-column prop="name" label="名称" min-width="160">
          <template #default="{ row }">
            <el-icon style="vertical-align:middle"><FolderOpened /></el-icon>
            <span style="margin-left:6px">{{ row.name || '(未命名)' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="删除时间" width="180">
          <template #default="{ row }">{{ formatDate(row.deleted_at) }}</template>
        </el-table-column>
        <el-table-column label="剩余天数" width="120">
          <template #default="{ row }">
            <el-tag v-if="row.days_remaining <= 3" size="small" type="danger">
              {{ row.days_remaining }} 天
            </el-tag>
            <el-tag v-else size="small" type="warning">
              {{ row.days_remaining }} 天
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="Fork 引用" width="100" align="center">
          <template #default="{ row }">
            <span v-if="row.fork_count > 0" style="color:#e6a23c">
              有 {{ row.fork_count }} 个
            </span>
            <span v-else style="color:#67c23a">无</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="240">
          <template #default="{ row }">
            <el-button size="small" text type="primary" @click="doRestore(row)">
              还原
            </el-button>
            <el-popconfirm
              v-if="row.can_permanent_delete"
              :title="`彻底删除「${row.name}」？所有数据将永久丢失，不可恢复。`"
              confirm-button-text="确认删除"
              cancel-button-text="取消"
              @confirm="doPermanentDelete(row)"
            >
              <template #reference>
                <el-button size="small" text type="danger">
                  彻底删除
                </el-button>
              </template>
            </el-popconfirm>
            <el-tooltip
              v-else
              content="此空间有 fork 引用，无法彻底删除。文档仍被引用。"
              placement="top"
            >
              <el-button size="small" text type="info" disabled>不可删除</el-button>
            </el-tooltip>
          </template>
        </el-table-column>
      </el-table>

      <el-empty v-if="!loading && spaces.length === 0" description="回收站是空的" />

      <div v-if="total > pageSize" style="margin-top:12px; text-align:right">
        <el-pagination
          v-model:current-page="currentPage"
          :page-size="pageSize"
          :total="total"
          layout="prev, pager, next"
          @current-change="load"
        />
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { spaceApi } from '@/api'

const router = useRouter()
const loading = ref(false)
const emptying = ref(false)
const spaces = ref<any[]>([])
const total = ref(0)
const pageSize = 20
const currentPage = ref(1)

async function load() {
  loading.value = true
  try {
    const offset = (currentPage.value - 1) * pageSize
    const res: any = await spaceApi.listTrash(pageSize, offset)
    spaces.value = res.data.spaces || []
    total.value = res.data.total || 0
  } catch {} finally { loading.value = false }
}

async function doRestore(row: any) {
  try {
    await spaceApi.restoreSpace(row.space_id)
    ElMessage.success('空间已还原')
    await load()
  } catch {}
}

async function doPermanentDelete(row: any) {
  try {
    await spaceApi.permanentDelete(row.space_id)
    ElMessage.success('空间已彻底删除')
    await load()
  } catch {}
}

async function doEmptyTrash() {
  emptying.value = true
  try {
    const res: any = await spaceApi.emptyTrash()
    const d = res.data
    const msg = d.skipped?.length
      ? `已删除 ${d.deleted.length} 个空间，${d.skipped.length} 个因 fork 引用跳过`
      : `已删除 ${d.deleted.length} 个空间`
    ElMessage.success(msg)
    await load()
  } catch {} finally { emptying.value = false }
}

function formatDate(d: string) {
  return d ? new Date(d).toLocaleString('zh-CN') : '-'
}

onMounted(load)
</script>

<style scoped>
.page { padding: 8px; }
</style>
