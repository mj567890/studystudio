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
          <el-input v-model="form.password" type="password" placeholder="密码"
            prefix-icon="Lock" size="large" show-password />
        </el-form-item>

        <!-- 密码强度条 -->
        <div v-if="form.password" class="strength-wrap">
          <div class="strength-bar">
            <div class="strength-fill" :class="strengthClass" :style="{width: strengthPct + '%'}" />
          </div>
          <span class="strength-label" :class="strengthClass">{{ strengthText }}</span>
        </div>

        <!-- 密码规则提示 -->
        <div class="pwd-rules">
          <div v-for="r in pwdRules" :key="r.label" class="rule-item">
            <span :class="r.pass ? 'rule-pass' : 'rule-fail'">{{ r.pass ? '✓' : '✗' }}</span>
            {{ r.label }}
          </div>
        </div>

        <el-button type="primary" size="large" :loading="loading"
          native-type="submit" style="width:100%;margin-top:8px">
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
import { ref, computed } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { authApi } from '@/api'

const router  = useRouter()
const formRef = ref()
const loading = ref(false)
const form    = ref({ nickname: '', email: '', password: '' })

// 密码规则检查
const pwdRules = computed(() => {
  const p = form.value.password
  return [
    { label: '至少 8 位',       pass: p.length >= 8 },
    { label: '包含大写字母',     pass: /[A-Z]/.test(p) },
    { label: '包含小写字母',     pass: /[a-z]/.test(p) },
    { label: '包含数字',         pass: /\d/.test(p) },
    { label: '包含特殊字符',     pass: /[^A-Za-z0-9]/.test(p) },
  ]
})

const strengthScore = computed(() => {
  const p = form.value.password
  if (!p) return 0
  let score = 0
  if (p.length >= 8)  score++
  if (p.length >= 12) score++
  if (/[A-Z]/.test(p)) score++
  if (/[a-z]/.test(p)) score++
  if (/\d/.test(p))    score++
  if (/[^A-Za-z0-9]/.test(p)) score++
  return score
})

const strengthPct  = computed(() => Math.min(100, (strengthScore.value / 6) * 100))
const strengthText = computed(() => {
  const s = strengthScore.value
  if (s <= 2) return '弱'
  if (s <= 4) return '中'
  return '强'
})
const strengthClass = computed(() => {
  const s = strengthScore.value
  if (s <= 2) return 'weak'
  if (s <= 4) return 'medium'
  return 'strong'
})

function validatePassword(_: any, value: string, callback: any) {
  const checks = [/[A-Z]/.test(value), /[a-z]/.test(value), /\d/.test(value), /[^A-Za-z0-9]/.test(value)]
  if (value.length < 8) return callback(new Error('密码至少 8 位'))
  if (checks.filter(Boolean).length < 3) return callback(new Error('须包含大写、小写、数字、特殊字符中至少三种'))
  callback()
}

const rules = {
  nickname: [{ required: true, min: 1, max: 100, message: '请输入昵称', trigger: 'blur' }],
  email:    [{ required: true, type: 'email', message: '请输入正确的邮箱', trigger: 'blur' }],
  password: [{ required: true, validator: validatePassword, trigger: 'blur' }],
}

async function submit() {
  await formRef.value.validate()
  loading.value = true
  try {
    await authApi.register(form.value)
    ElMessage.success('注册成功，请登录')
    router.push('/login')
  } catch (e: any) {
    const detail = e?.response?.data?.detail
    if (Array.isArray(detail)) {
      ElMessage.error(detail[0]?.msg?.replace('Value error, ', '') || '注册失败')
    } else {
      ElMessage.error('注册失败，请稍后再试')
    }
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.auth-page {
  min-height: 100vh; display: flex;
  align-items: center; justify-content: center;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
}
.auth-card  { width: 420px; padding: 20px; }
.title      { text-align: center; font-size: 24px; color: #303133; margin-bottom: 8px; }
.subtitle   { text-align: center; color: #909399; margin-bottom: 24px; }
.switch-tip { text-align: center; margin-top: 16px; color: #909399; font-size: 14px; }

.strength-wrap { display: flex; align-items: center; gap: 8px; margin: -8px 0 8px; }
.strength-bar  { flex: 1; height: 6px; background: #eee; border-radius: 3px; overflow: hidden; }
.strength-fill { height: 100%; border-radius: 3px; transition: width 0.3s, background 0.3s; }
.weak   .strength-fill, .strength-fill.weak   { background: #f56c6c; }
.medium .strength-fill, .strength-fill.medium { background: #e6a23c; }
.strong .strength-fill, .strength-fill.strong { background: #67c23a; }
.strength-label { font-size: 12px; width: 20px; }
.strength-label.weak   { color: #f56c6c; }
.strength-label.medium { color: #e6a23c; }
.strength-label.strong { color: #67c23a; }

.pwd-rules   { margin: 0 0 12px; padding: 10px 12px; background: #f8f9fa; border-radius: 6px; }
.rule-item   { font-size: 12px; color: #606266; line-height: 1.8; }
.rule-pass   { color: #67c23a; font-weight: bold; margin-right: 4px; }
.rule-fail   { color: #c0c4cc; margin-right: 4px; }
</style>
