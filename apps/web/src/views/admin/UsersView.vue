<template>
  <div class="page">
    <el-card>
      <template #header>
        <span>用户管理</span>
        <el-button size="small" style="float:right" @click="load">刷新</el-button>
      </template>

      <el-table :data="users" v-loading="loading" size="small">
        <el-table-column prop="nickname" label="昵称" width="120" />
        <el-table-column prop="email" label="邮箱" show-overflow-tooltip />
        <el-table-column label="角色" width="160">
          <template #default="{ row }">
            <el-select v-model="row._newRole" size="small" style="width:130px"
              @change="updateRole(row)">
              <el-option label="学习者" value="learner" />
              <el-option label="教师" value="teacher" />
              <el-option label="知识审核员" value="knowledge_reviewer" />
              <el-option label="管理员" value="admin" />
            </el-select>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-switch v-model="row._active"
              active-text="正常" inactive-text="禁用"
              @change="updateStatus(row)" />
          </template>
        </el-table-column>
        <el-table-column prop="created_at" label="注册时间" width="160">
          <template #default="{ row }">
            {{ formatDate(row.created_at) }}
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { adminApi } from '@/api'

const loading = ref(false)
const users   = ref<any[]>([])

function formatDate(d: string) {
  return d ? new Date(d).toLocaleDateString('zh-CN') : '-'
}

async function load() {
  loading.value = true
  try {
    const res: any = await adminApi.listUsers()
    users.value = (res.data?.users || []).map((u: any) => ({
      ...u,
      _newRole: u.roles?.[0] || 'learner',
      _active:  u.status === 'active',
    }))
  } finally { loading.value = false }
}

async function updateRole(row: any) {
  try {
    await adminApi.updateUserRole({ user_id: row.user_id, role_name: row._newRole })
    ElMessage.success(`已将 ${row.nickname} 的角色改为 ${row._newRole}`)
  } catch {}
}

async function updateStatus(row: any) {
  const status = row._active ? 'active' : 'disabled'
  try {
    await adminApi.updateUserStatus({ user_id: row.user_id, status })
    ElMessage.success(`已${status === 'active' ? '启用' : '禁用'} ${row.nickname}`)
  } catch {}
}

onMounted(load)
</script>
<style scoped>.page { padding: 8px; }</style>
