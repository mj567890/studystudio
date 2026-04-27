<template>
  <div class="auth-page">
    <el-card class="auth-card">
      <h2 class="title">系统安装</h2>
      <p class="subtitle">欢迎使用自适应学习平台，请完成初始化配置</p>

      <el-form :model="form" :rules="rules" ref="formRef" @submit.prevent="submit"
               label-position="top" size="large">
        <!-- ── 管理员信息 ── -->
        <div class="section-title">管理员账号</div>
        <el-form-item label="昵称" prop="admin_nickname">
          <el-input v-model="form.admin_nickname" placeholder="管理员显示名称" />
        </el-form-item>
        <el-form-item label="邮箱" prop="admin_email">
          <el-input v-model="form.admin_email" placeholder="用于登录的邮箱" />
        </el-form-item>
        <el-form-item label="密码" prop="admin_password">
          <el-input v-model="form.admin_password" type="password"
                    placeholder="管理员登录密码" show-password />
        </el-form-item>

        <!-- 密码强度指示 -->
        <div v-if="form.admin_password" class="strength-wrap">
          <div class="strength-bar">
            <div class="strength-fill" :class="strengthClass" :style="{width: strengthPct + '%'}" />
          </div>
          <span class="strength-label" :class="strengthClass">{{ strengthText }}</span>
        </div>
        <div class="pwd-rules">
          <div v-for="r in pwdRules" :key="r.label" class="rule-item">
            <span :class="r.pass ? 'rule-pass' : 'rule-fail'">{{ r.pass ? '✓' : '✗' }}</span>
            {{ r.label }}
          </div>
        </div>

        <el-form-item label="确认密码" prop="confirm_password">
          <el-input v-model="form.confirm_password" type="password"
                    placeholder="再次输入密码" show-password />
        </el-form-item>

        <!-- ── 系统设置 ── -->
        <div class="section-title">系统设置</div>
        <el-form-item label="系统名称">
          <el-input v-model="form.site_name" placeholder="我的学习平台" />
        </el-form-item>
        <el-form-item label="版权信息">
          <el-input v-model="form.copyright" placeholder="Copyright 2026" />
        </el-form-item>
        <el-form-item label="注册协议">
          <el-input v-model="form.registration_agreement" type="textarea"
                    :rows="3" placeholder="注册即表示同意本平台服务条款..." />
        </el-form-item>

        <el-button type="primary" size="large" :loading="loading"
                   native-type="submit" style="width:100%;margin-top:8px">
          开始安装
        </el-button>
      </el-form>

      <p class="switch-tip">
        安装完成后，请勿重复运行此向导。
      </p>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { installApi } from '@/api'
import { invalidateInitCache } from '@/router'

const router = useRouter()
const formRef = ref()
const loading = ref(false)

const form = ref({
  admin_nickname: '',
  admin_email: '',
  admin_password: '',
  confirm_password: '',
  site_name: '',
  copyright: '',
  registration_agreement: '',
})

// ── 密码强度（与 RegisterView 相同逻辑） ──
const pwdRules = computed(() => {
  const p = form.value.admin_password
  return [
    { label: '至少 8 位',    pass: p.length >= 8 },
    { label: '包含大写字母',  pass: /[A-Z]/.test(p) },
    { label: '包含小写字母',  pass: /[a-z]/.test(p) },
    { label: '包含数字',      pass: /\d/.test(p) },
    { label: '包含特殊字符',  pass: /[^A-Za-z0-9]/.test(p) },
  ]
})

const strengthScore = computed(() => {
  const p = form.value.admin_password
  if (!p) return 0
  let score = 0
  if (p.length >= 8) score++
  if (p.length >= 12) score++
  if (/[A-Z]/.test(p)) score++
  if (/[a-z]/.test(p)) score++
  if (/\d/.test(p)) score++
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
  admin_nickname: [{ required: true, min: 1, max: 100, message: '请输入管理员昵称', trigger: 'blur' }],
  admin_email: [{ required: true, type: 'email', message: '请输入正确的邮箱', trigger: 'blur' }],
  admin_password: [
    { required: true, validator: validatePassword, trigger: 'blur' },
  ],
  confirm_password: [
    { required: true, message: '请再次输入密码', trigger: 'blur' },
    {
      validator: (_: any, value: string, callback: any) => {
        if (value !== form.value.admin_password) {
          callback(new Error('两次输入的密码不一致'))
        } else {
          callback()
        }
      },
      trigger: 'blur',
    },
  ],
}

async function submit() {
  await formRef.value.validate()
  loading.value = true
  try {
    const { confirm_password, ...installData } = form.value
    await installApi.install(installData)
    ElMessage.success('系统安装完成！请使用管理员账号登录')
    invalidateInitCache()  // 清除缓存，否则守卫会把 /login 重定向回 /install
    router.push('/login')
  } catch (e: any) {
    const detail = e?.response?.data?.detail
    if (Array.isArray(detail)) {
      ElMessage.error(detail[0]?.msg?.replace('Value error, ', '') || '安装失败')
    } else if (detail?.msg) {
      ElMessage.error(detail.msg)
    } else {
      ElMessage.error('安装失败，请稍后重试')
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
.auth-card { width: 500px; padding: 28px; max-height: 90vh; overflow-y: auto; }
.title    { text-align: center; font-size: 24px; color: #303133; margin-bottom: 8px; }
.subtitle { text-align: center; color: #909399; margin-bottom: 20px; }

.section-title {
  font-size: 14px; font-weight: 600; color: #409eff;
  padding: 8px 0 4px; border-bottom: 1px solid #e4e7ed; margin-bottom: 12px;
}

.switch-tip { text-align: center; margin-top: 16px; color: #c0c4cc; font-size: 13px; }

/* ── password strength ── */
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
