<template>
  <div class="auth-page">
    <el-card class="auth-card">
      <h2 class="title">自适应学习平台</h2>
      <p class="subtitle">创建新账号</p>

      <el-form :model="form" :rules="rules" ref="formRef" @submit.prevent="submit">
        <el-form-item prop="nickname">
          <el-input v-model="form.nickname" placeholder="昵称" prefix-icon="User" size="large" />
        </el-form-item>
        <el-form-item prop="email">
          <el-input v-model="form.email" placeholder="邮箱" prefix-icon="Message" size="large" />
        </el-form-item>
        <el-form-item prop="password">
          <el-input v-model="form.password" type="password" placeholder="密码（至少8位）"
            prefix-icon="Lock" size="large" show-password />
        </el-form-item>
        <el-button type="primary" size="large" :loading="loading"
          native-type="submit" style="width:100%">
          注册
        </el-button>
      </el-form>

      <p class="switch-tip">
        已有账号？<router-link to="/login">直接登录</router-link>
      </p>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { authApi } from '@/api'

const router  = useRouter()
const formRef = ref()
const loading = ref(false)
const form    = ref({ nickname: '', email: '', password: '' })

const rules = {
  nickname: [{ required: true, min: 1, max: 100, message: '请输入昵称', trigger: 'blur' }],
  email:    [{ required: true, type: 'email', message: '请输入正确的邮箱', trigger: 'blur' }],
  password: [{ required: true, min: 8, message: '密码至少8位', trigger: 'blur' }],
}

async function submit() {
  await formRef.value.validate()
  loading.value = true
  try {
    await authApi.register(form.value)
    ElMessage.success('注册成功，请登录')
    router.push('/login')
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.auth-page {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
}
.auth-card { width: 400px; padding: 20px; }
.title    { text-align: center; font-size: 24px; color: #303133; margin-bottom: 8px; }
.subtitle { text-align: center; color: #909399; margin-bottom: 24px; }
.switch-tip { text-align: center; margin-top: 16px; color: #909399; font-size: 14px; }
</style>
