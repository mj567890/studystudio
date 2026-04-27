<template>
  <div class="join-page">
    <el-card class="card">
      <div class="icon">📨</div>
      <div class="title">加入知识空间</div>
      <div class="code">邀请码: <span>{{ code }}</span></div>

      <div v-if="status === 'pending'" class="status">
        <el-icon class="is-loading"><Loading /></el-icon>
        <span>正在验证邀请码...</span>
      </div>
      <div v-else-if="status === 'need-login'" class="status">
        <p style="color:#606266">你需要先登录才能加入空间</p>
        <el-button type="primary" @click="goLogin">前往登录</el-button>
      </div>
      <div v-else-if="status === 'ok'" class="status">
        <p style="color:#67c23a">
          {{ alreadyMember ? '你已经是' : '已加入' }}「{{ spaceName }}」
        </p>
        <el-button type="primary" @click="router.push(`/spaces/${spaceId}`)">
          前往空间
        </el-button>
      </div>
      <div v-else-if="status === 'error'" class="status">
        <p style="color:#f56c6c">{{ errorMsg }}</p>
        <el-button @click="router.push('/spaces')">返回空间列表</el-button>
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { spaceApi } from '@/api'
import { useAuthStore } from '@/stores/auth'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

const code = (route.params.code as string || '').toUpperCase()
const status = ref<'pending' | 'need-login' | 'ok' | 'error'>('pending')
const errorMsg = ref('')
const spaceName = ref('')
const spaceId = ref('')
const alreadyMember = ref(false)

function goLogin() {
  sessionStorage.setItem('pending_join_code', code)
  router.push('/login?redirect=' + encodeURIComponent(`/join/${code}`))
}

async function tryJoin() {
  if (!code) {
    status.value = 'error'
    errorMsg.value = '无效的邀请链接'
    return
  }
  if (!auth.isLoggedIn) {
    status.value = 'need-login'
    return
  }
  try {
    const res: any = await spaceApi.joinByCode(code)
    const d = res.data
    spaceId.value = d.space_id
    spaceName.value = d.space_name
    alreadyMember.value = d.already_member
    status.value = 'ok'
  } catch (e: any) {
    status.value = 'error'
    errorMsg.value = e?.response?.data?.detail?.msg || '加入失败,邀请码可能已失效'
  }
}

onMounted(tryJoin)
</script>

<style scoped>
.join-page { min-height: 100vh; display: flex; align-items: center; justify-content: center;
             background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); }
.card { width: 400px; text-align: center; padding: 24px 12px; }
.icon { font-size: 48px; margin-bottom: 12px; }
.title { font-size: 22px; font-weight: bold; margin-bottom: 8px; }
.code { font-family: monospace; color: #606266; margin-bottom: 24px; }
.code span { color: #409eff; font-weight: bold; letter-spacing: 2px; font-size: 18px; }
.status { margin-top: 16px; }
.status p { margin: 12px 0; }
</style>
