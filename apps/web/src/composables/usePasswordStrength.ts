// src/composables/usePasswordStrength.ts
// 密码强度校验逻辑 —— 供 RegisterView 和 InstallView 共用
import { computed, type Ref } from 'vue'

export function usePasswordStrength(password: Ref<string>) {
  const pwdRules = computed(() => {
    const p = password.value
    return [
      { label: '至少 8 位',    pass: p.length >= 8 },
      { label: '包含大写字母',  pass: /[A-Z]/.test(p) },
      { label: '包含小写字母',  pass: /[a-z]/.test(p) },
      { label: '包含数字',      pass: /\d/.test(p) },
      { label: '包含特殊字符',  pass: /[^A-Za-z0-9]/.test(p) },
    ]
  })

  const strengthScore = computed(() => {
    const p = password.value
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

  const strengthPct = computed(() => Math.min(100, (strengthScore.value / 6) * 100))
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
    const checks = [
      /[A-Z]/.test(value),
      /[a-z]/.test(value),
      /\d/.test(value),
      /[^A-Za-z0-9]/.test(value),
    ]
    if (value.length < 8) return callback(new Error('密码至少 8 位'))
    if (checks.filter(Boolean).length < 3)
      return callback(new Error('须包含大写、小写、数字、特殊字符中至少三种'))
    callback()
  }

  return { pwdRules, strengthScore, strengthPct, strengthText, strengthClass, validatePassword }
}
