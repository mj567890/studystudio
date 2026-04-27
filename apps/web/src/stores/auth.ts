// src/stores/auth.ts
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { authApi } from '@/api'

export const useAuthStore = defineStore('auth', () => {
  const token = ref(localStorage.getItem('access_token') || '')
  const user  = ref<any>(null)

  const isLoggedIn = computed(() => !!token.value)
  const isAdmin    = computed(() =>
    user.value?.roles?.includes('admin') || user.value?.roles?.includes('knowledge_reviewer')
  )

  async function login(email: string, password: string) {
    const res: any = await authApi.login({ email, password })
    token.value = res.data.access_token
    localStorage.setItem('access_token', token.value)
    await fetchMe()
  }

  async function fetchMe() {
    const res: any = await authApi.getMe()
    user.value = res.data
  }

  function logout() {
    token.value = ''
    user.value  = null
    localStorage.removeItem('access_token')
  }

  return { token, user, isLoggedIn, isAdmin, login, fetchMe, logout }
})
