<template>
  <div class="page">
    <div class="profile-wrap">

      <!-- 用户信息展示 -->
      <el-card class="section-card">
        <div class="user-card">
          <div class="avatar-wrap">
            <el-avatar :size="80" :src="editForm.avatar_url || ''" icon="UserFilled" />
            <div class="avatar-actions">
              <input ref="fileInput" type="file" accept="image/*" style="display:none"
                @change="onAvatarSelected" />
              <el-button size="small" @click="fileInput?.click()">更换头像</el-button>
            </div>
          </div>
          <div class="user-info">
            <div class="user-name">{{ auth.user?.nickname || auth.user?.email }}</div>
            <div class="user-email">{{ auth.user?.email }}</div>
            <el-tag size="small">{{ auth.user?.roles?.[0] || 'learner' }}</el-tag>
          </div>
        </div>
      </el-card>

      <!-- 编辑资料（页内展开）-->
      <el-card class="section-card">
        <template #header>
          <div style="display:flex;justify-content:space-between;align-items:center">
            <span>编辑资料</span>
          </div>
        </template>
        <el-form :model="editForm" label-width="70px">
          <el-form-item label="昵称">
            <el-input v-model="editForm.nickname" placeholder="请输入昵称" />
          </el-form-item>
        </el-form>
        <div style="text-align:right;margin-top:8px">
          <el-button type="primary" :loading="saving" @click="saveProfile">保存资料</el-button>
        </div>
      </el-card>

      <!-- 修改密码（页内展开）-->
      <el-card class="section-card">
        <template #header>修改密码</template>
        <el-form :model="pwdForm" label-width="90px">
          <el-form-item label="旧密码">
            <el-input v-model="pwdForm.old_password" type="password" show-password />
          </el-form-item>
          <el-form-item label="新密码">
            <el-input v-model="pwdForm.new_password" type="password" show-password placeholder="至少 8 位" />
          </el-form-item>
          <!-- 强度条 -->
          <div v-if="pwdForm.new_password" style="margin:-8px 0 8px;padding:0 0 0 90px">
            <div style="display:flex;align-items:center;gap:8px;margin-bottom:6px">
              <div style="flex:1;height:6px;background:#eee;border-radius:3px;overflow:hidden">
                <div :style="{width: pwdStrengthPct + '%', background: pwdStrengthColor,
                  height:'100%', borderRadius:'3px', transition:'all 0.3s'}" />
              </div>
              <span style="font-size:12px;width:20px" :style="{color: pwdStrengthColor}">
                {{ pwdStrengthText }}
              </span>
            </div>
            <div style="background:#f8f9fa;border-radius:6px;padding:8px 10px">
              <div v-for="r in pwdRules" :key="r.label"
                style="font-size:12px;color:#606266;line-height:1.8">
                <span :style="{color: r.pass ? '#67c23a' : '#c0c4cc',
                  fontWeight:'bold', marginRight:'4px'}">{{ r.pass ? '✓' : '✗' }}</span>
                {{ r.label }}
              </div>
            </div>
          </div>
          <el-form-item label="确认新密码">
            <el-input v-model="pwdForm.confirm" type="password" show-password />
          </el-form-item>
        </el-form>
        <div style="text-align:right;margin-top:8px">
          <el-button type="primary" :loading="savingPwd" @click="savePassword">确认修改</el-button>
        </div>
      </el-card>

      <!-- 注销账号 -->
      <el-card class="section-card">
        <template #header>危险操作</template>
        <div v-if="!showDeactivateForm">
          <p style="font-size:13px;color:#606266;margin:0 0 12px">
            注销后账号不可恢复，数据将保留但无法登录。
          </p>
          <el-button type="danger" plain @click="showDeactivateForm=true">注销账号</el-button>
        </div>
        <div v-else>
          <p style="font-size:13px;color:#f56c6c;margin:0 0 8px">
            请输入 <b>DELETE</b> 确认注销：
          </p>
          <el-input v-model="deactivateConfirm" placeholder="输入 DELETE" style="margin-bottom:8px" />
          <div style="display:flex;gap:8px">
            <el-button @click="showDeactivateForm=false;deactivateConfirm=''">取消</el-button>
            <el-button type="danger"
              :disabled="deactivateConfirm !== 'DELETE'"
              :loading="deactivating"
              @click="doDeactivate">
              确认注销
            </el-button>
          </div>
        </div>
      </el-card>

    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useAuthStore } from '@/stores/auth'
import { profileApi } from '@/api'

const router = useRouter()
const auth   = useAuthStore()

// 编辑资料
const saving    = ref(false)
const editForm  = ref({ nickname: '', avatar_url: '' })
const fileInput = ref<HTMLInputElement | null>(null)
const selectedFile = ref<File | null>(null)

function onAvatarSelected(e: Event) {
  const file = (e.target as HTMLInputElement).files?.[0]
  if (!file) return
  if (file.size > 5 * 1024 * 1024) { ElMessage.warning('图片不超过 5MB'); return }
  selectedFile.value = file
  editForm.value.avatar_url = URL.createObjectURL(file)
}

async function saveProfile() {
  saving.value = true
  try {
    if (selectedFile.value) {
      const form = new FormData()
      form.append('file', selectedFile.value)
      const uploadRes: any = await profileApi.uploadAvatar(form)
      editForm.value.avatar_url = uploadRes.data.avatar_url
      selectedFile.value = null
    }
    await profileApi.update({
      nickname:   editForm.value.nickname   || undefined,
      avatar_url: editForm.value.avatar_url || undefined,
    })
    await auth.fetchMe()
    ElMessage.success('资料已更新')
  } catch { ElMessage.error('更新失败') }
  finally { saving.value = false }
}

// 修改密码
const savingPwd = ref(false)
const pwdForm   = ref({ old_password: '', new_password: '', confirm: '' })

const pwdRules = computed(() => {
  const p = pwdForm.value.new_password
  return [
    { label: '至少 8 位',   pass: p.length >= 8 },
    { label: '包含大写字母', pass: /[A-Z]/.test(p) },
    { label: '包含小写字母', pass: /[a-z]/.test(p) },
    { label: '包含数字',     pass: /\d/.test(p) },
    { label: '包含特殊字符', pass: /[^A-Za-z0-9]/.test(p) },
  ]
})
const pwdStrengthScore = computed(() => {
  const p = pwdForm.value.new_password
  if (!p) return 0
  let s = 0
  if (p.length >= 8) s++; if (p.length >= 12) s++
  if (/[A-Z]/.test(p)) s++; if (/[a-z]/.test(p)) s++
  if (/\d/.test(p)) s++; if (/[^A-Za-z0-9]/.test(p)) s++
  return s
})
const pwdStrengthPct   = computed(() => Math.min(100, (pwdStrengthScore.value / 6) * 100))
const pwdStrengthText  = computed(() => pwdStrengthScore.value <= 2 ? '弱' : pwdStrengthScore.value <= 4 ? '中' : '强')
const pwdStrengthColor = computed(() => pwdStrengthScore.value <= 2 ? '#f56c6c' : pwdStrengthScore.value <= 4 ? '#e6a23c' : '#67c23a')

async function savePassword() {
  if (pwdForm.value.new_password !== pwdForm.value.confirm) {
    ElMessage.warning('两次输入的新密码不一致'); return
  }
  savingPwd.value = true
  try {
    await profileApi.changePassword({
      old_password: pwdForm.value.old_password,
      new_password: pwdForm.value.new_password,
    })
    ElMessage.success('密码已修改，请重新登录')
    pwdForm.value = { old_password: '', new_password: '', confirm: '' }
    setTimeout(() => { auth.logout(); router.push('/login') }, 1500)
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail?.msg || '修改失败')
  } finally { savingPwd.value = false }
}

// 注销
const showDeactivateForm = ref(false)
const deactivateConfirm  = ref('')
const deactivating       = ref(false)

async function doDeactivate() {
  deactivating.value = true
  try {
    await profileApi.deactivate()
    ElMessage.success('账号已注销')
    auth.logout()
    router.push('/login')
  } catch { ElMessage.error('注销失败，请稍后重试') }
  finally { deactivating.value = false }
}

onMounted(() => {
  editForm.value.nickname   = auth.user?.nickname || ''
  editForm.value.avatar_url = auth.user?.avatar_url || ''
})
</script>

<style scoped>
.page { padding: 16px; }
.profile-wrap { max-width: 480px; margin: 0 auto; display: flex; flex-direction: column; gap: 16px; }
.section-card {}
.user-card { display: flex; align-items: center; gap: 20px; }
.avatar-wrap { display: flex; flex-direction: column; align-items: center; gap: 8px; flex-shrink: 0; }
.user-info { flex: 1; }
.user-name  { font-size: 18px; font-weight: 600; color: #303133; margin-bottom: 4px; }
.user-email { font-size: 13px; color: #909399; margin-bottom: 8px; }
</style>
