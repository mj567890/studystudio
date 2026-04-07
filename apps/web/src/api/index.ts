// src/api/index.ts
// 统一 API 请求封装，自动注入 Token，统一错误处理

import axios from 'axios'
import { ElMessage } from 'element-plus'

const http = axios.create({
  baseURL: '/api',
  timeout: 30000,
})

// 请求拦截：注入 JWT Token
http.interceptors.request.use(config => {
  const token = localStorage.getItem('access_token')
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

// 响应拦截：统一错误处理
http.interceptors.response.use(
  res => res.data,
  err => {
    const status = err.response?.status
    const msg = err.response?.data?.detail?.msg || err.message || '请求失败'

    if (status === 401) {
      localStorage.removeItem('access_token')
      window.location.href = '/login'
      return Promise.reject(err)
    }

    ElMessage.error(msg)
    return Promise.reject(err)
  }
)

// ── Auth ─────────────────────────────────────────────────────
export const authApi = {
  register: (data: { email: string; password: string; nickname: string }) =>
    http.post('/auth/register', data),
  login: (data: { email: string; password: string }) =>
    http.post('/auth/login', data),
  getMe: () => http.get('/users/me'),
}

// ── Learner ───────────────────────────────────────────────────
export const learnerApi = {
  getProfile: () => http.get('/learners/me/profile'),
  getPlacementQuiz: (topicKey: string) =>
    http.get(`/learners/me/placement-quiz?topic_key=${topicKey}`),
  submitPlacementResult: (data: any) =>
    http.post('/learners/me/placement-result', data),
  getGaps: (topicKey: string) =>
    http.get(`/learners/me/gaps?topic_key=${topicKey}`),
  getRepairPath: (topicKey: string) =>
    http.get(`/learners/me/repair-path?topic_key=${topicKey}`),
  markChapter: (data: { tutorial_id: string; chapter_id: string; completed: boolean }) =>
    http.post('/learners/me/chapter-progress', data),
  getChapterProgress: (tutorialId: string) =>
    http.get(`/learners/me/chapter-progress/${tutorialId}`),
}

// ── Files ─────────────────────────────────────────────────────
export const fileApi = {
  upload: (file: File, spaceType = 'personal', domainTag = '') => {
    const form = new FormData()
    form.append('file', file)
    form.append('space_type', spaceType)
    if (domainTag) form.append('domain_tag', domainTag)
    return http.post('/files/upload', form, {
      headers: { 'Content-Type': 'multipart/form-data' }
    })
  },
  getMyDocuments: () => http.get('/files/my-documents'),
}

// ── Knowledge ─────────────────────────────────────────────────
export const knowledgeApi = {
  getDomains: () => http.get('/knowledge/domains'),
  getSubgraph: (topicKey: string) =>
    http.post('/knowledge/subgraph', { topic_key: topicKey }),
}

// ── Tutorial ──────────────────────────────────────────────────
export const tutorialApi = {
  getByTopic: (topicKey: string) =>
    http.get(`/tutorials/topic/${topicKey}`),
}

// ── Teaching ──────────────────────────────────────────────────
export const teachingApi = {
  createConversation: (topicKey: string) =>
    http.post(`/teaching/conversations?topic_key=${topicKey}`),
  chat: (data: { conversation_id: string; message: string; context: any }) =>
    http.post('/teaching/chat', data),
}

// ── Admin ─────────────────────────────────────────────────────
export const adminApi = {
  // 用户管理
  listUsers:        ()    => http.get('/admin/users'),
  updateUserRole:   (data: { user_id: string; role_name: string }) =>
    http.post('/admin/users/role', data),
  updateUserStatus: (data: { user_id: string; status: string }) =>
    http.post('/admin/users/status', data),

  // 知识审核
  listPendingEntities: () => http.get('/admin/entities/pending'),
  listEntities: (params: { review_status?: string; domain_tag?: string; limit?: number } = {}) =>
    http.get('/admin/entities', { params }),
  reviewEntity: (data: { entity_id: string; action: string; reason?: string }) =>
    http.post('/admin/entities/review', data),
  reviewEntitiesBatch: (data: { entity_ids: string[]; action: string; reason?: string }) =>
    http.post('/admin/entities/review/batch', data),
  updateEntity: (data: {
    entity_id: string
    canonical_name: string
    entity_type: string
    domain_tag: string
    short_definition?: string
    detailed_explanation?: string
    review_status?: string
    is_core?: boolean
  }) => http.post('/admin/entities/update', data),
  createKnowledgeSpace: (data: { name: string; space_type?: string; description?: string }) =>
    http.post('/admin/knowledge/spaces', data),

  // 系统初始化与配置
  getInitStatus:    ()    => http.get('/admin/system/init-status'),
  seedKnowledge:    ()    => http.post('/admin/system/seed-knowledge', {}),
  prebuildBanks:    ()    => http.post('/admin/system/prebuild-banks', {}),
  getSystemConfigs: ()    => http.get('/admin/system/configs'),
  updateConfig:     (data: { config_key: string; config_value: string }) =>
    http.post('/admin/system/configs', data),
  getStats:         ()    => http.get('/admin/system/stats'),
}
