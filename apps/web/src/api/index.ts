// src/api/index.ts
// 统一 API 请求封装，自动注入 Token，统一错误处理

import axios from 'axios'
import { ElMessage } from 'element-plus'

const http = axios.create({
  baseURL: '/api',
  timeout: 30000,
})
export { http }

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
    const status   = err.response?.status
    const detail   = err.response?.data?.detail
    const dataMsg  = err.response?.data?.msg

    // 提取可读错误信息：兼容 {detail:{msg}} / {detail:"string"} / {msg} 三种格式
    let msg: string
    if (detail && typeof detail === 'object' && detail.msg) {
      msg = detail.msg
    } else if (typeof detail === 'string' && detail) {
      msg = detail
    } else if (dataMsg) {
      msg = dataMsg
    } else {
      // 根据状态码给出中文提示，不暴露英文原始错误
      const statusMessages: Record<number, string> = {
        400: '请求参数有误，请检查后重试',
        401: '登录已过期，请重新登录',
        403: '权限不足，无法执行此操作',
        404: '请求的资源不存在',
        422: '提交的数据格式有误',
        500: '服务器内部错误，请稍后重试',
        502: '服务暂时不可用，请稍后重试',
        503: '服务维护中，请稍后重试',
      }
      msg = statusMessages[status ?? 0] || '网络请求失败，请检查网络连接'
    }

    if (status === 401) {
      localStorage.removeItem('access_token')
      window.location.href = '/login'
      return Promise.reject(err)
    }

    ElMessage.error(msg)
    return Promise.reject(err)
  }
)

// ── Install (系统安装向导) ──────────────────────────────────
export const installApi = {
  getStatus: () => http.get('/install/status'),
  install: (data: {
    admin_email: string
    admin_password: string
    admin_nickname: string
    site_name: string
    copyright: string
    registration_agreement: string
  }) => http.post('/install', data),
}

// ── Auth ─────────────────────────────────────────────────────
export const authApi = {
  register: (data: { email: string; password: string; nickname: string }) =>
    http.post('/auth/register', data),
  login: (data: { email: string; password: string }) =>
    http.post('/auth/login', data),
  getMe: () => http.get('/users/me'),
}

// ── Learner ───────────────────────────────────────────────────
export const blueprintApi = {
  getStatus: (topic: string) =>
    http.get(`/blueprints/${topic}/status`),
  generate: (topic: string, force = false, teacherInstruction?: string, typeInstructions?: Record<string, string>) =>
    http.post(`/blueprints/${topic}/generate`, {
      force_regen: force,
      teacher_instruction: teacherInstruction || undefined,
      type_instructions: typeInstructions || undefined,
    }),
}

// ── Course Templates ──────────────────────────────────────────────
export const templateApi = {
  list: () => http.get('/course-templates'),
  get: (templateId: string) => http.get(`/course-templates/${templateId}`),
  create: (data: { name: string; content: string; is_public?: boolean }) =>
    http.post('/course-templates', data),
  update: (templateId: string, data: { name?: string; content?: string; is_public?: boolean }) =>
    http.put(`/course-templates/${templateId}`, data),
  delete: (templateId: string) => http.delete(`/course-templates/${templateId}`),
  setSpaceDefault: (spaceId: string, templateId: string | null,
                    theoryId?: string | null, taskId?: string | null, projectId?: string | null) =>
    http.put(`/spaces/${spaceId}/default-template`, {
      template_id: templateId,
      theory_template_id: theoryId,
      task_template_id: taskId,
      project_template_id: projectId,
    }),
}

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
  markChapter: (data: { tutorial_id: string; chapter_id: string; completed: boolean; status?: string; duration_seconds?: number }) =>
    http.post('/learners/me/chapter-progress', data),
  getChapterQuiz: (chapterId: string) =>
    http.get(`/learners/me/chapter-quiz/${chapterId}`),
  submitQuiz: (data: { chapter_id: string; answers: any[] }) =>
    http.post('/learners/me/chapter-quiz/submit', data),
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
  viewDocument: (docId: string) =>
    http.get(`/files/documents/${docId}/view`),
  retryDocument: (docId: string) =>
    http.post(`/files/documents/${docId}/retry`),
  deleteDocument: (docId: string) =>
    http.delete(`/files/documents/${docId}`),
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
  getByTopic: (topicKey: string, forceRefresh = false, spaceId?: string) =>
    http.get(`/tutorials/topic/${topicKey}`, {
      params: { force_refresh: forceRefresh, ...(spaceId ? { space_id: spaceId } : {}) },
    }),
}

// ── Teaching ──────────────────────────────────────────────────
export const teachingApi = {
  createConversation: (topicKey: string, title?: string, spaceId?: string) =>
    http.post(`/teaching/conversations?topic_key=${encodeURIComponent(topicKey)}&title=${encodeURIComponent(title || topicKey)}&space_id=${encodeURIComponent(spaceId || '')}`),
  chat: (data: { conversation_id: string; message: string; context: any }) =>
    http.post('/teaching/chat', data),
  getSpaces: () =>
    http.get('/teaching/spaces'),
  getChapterSource: (chapterId: string) =>
    http.get(`/teaching/chapters/${chapterId}/source`),
  listConversations: (spaceId?: string) =>
    http.get('/teaching/conversations', { params: spaceId ? { space_id: spaceId } : {} }),
  deleteConversation: (conversationId: string) =>
    http.delete(`/teaching/conversations/${conversationId}`),
  getTurns: (conversationId: string) =>
    http.get(`/teaching/conversations/${conversationId}/turns`),
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
    http.post('/spaces', data),

  // AI 自动审核
  triggerAutoReview: () =>
    http.post('/admin/auto-review/trigger', {}),
  getAutoReviewStatus: (spaceId: string) =>
    http.get('/admin/auto-review/status', { params: { space_id: spaceId } }),
  getAutoReviewSpaces: () =>
    http.get('/admin/auto-review/spaces'),

  // 系统初始化与配置
  getInitStatus:    ()    => http.get('/admin/system/init-status'),
  seedKnowledge:    ()    => http.post('/admin/system/seed-knowledge', {}),
  prebuildBanks:    ()    => http.post('/admin/system/prebuild-banks', {}),
  getSystemConfigs: ()    => http.get('/admin/system/configs'),
  updateConfig:     (data: { config_key: string; config_value: string }) =>
    http.post('/admin/system/configs', data),
  getAllDocuments: (params?: { status?: string; space_type?: string; page?: number; page_size?: number; sort_by?: string; sort_order?: string }) =>
    http.get('/files/all-documents', { params }),
  reparseDocument: (documentId: string) => http.post(`/files/reparse/${documentId}`),
  refineChapter: (chapterId: string, data: { instruction: string; auto_regenerate_quiz?: boolean; auto_regenerate_discussion?: boolean }) =>
    http.post(`/admin/courses/chapters/${chapterId}/refine`, data),
  backfillPageNo:   ()    => http.post('/admin/documents/backfill-page-no'),
  getStats:         ()    => http.get('/admin/system/stats'),

  // 任务管理
  getTaskStats:     ()    => http.get('/admin/tasks/stats'),
  listTasks:        (params?: any) => http.get('/admin/tasks', { params }),
  listFailedTasks:  (params?: any) => http.get('/admin/tasks/failed', { params }),
  getTaskDetail:    (id: string) => http.get(`/admin/tasks/${id}`),
  retryTask:        (id: string) => http.post(`/admin/tasks/${id}/retry`),
  cancelTask:       (id: string) => http.post(`/admin/tasks/${id}/cancel`),
  batchRetryTasks:  (data: { execution_ids: string[] }) => http.post('/admin/tasks/batch-retry', data),
  getTaskFilters:   ()    => http.get('/admin/tasks/meta/filters'),

  // 系统健康监控（管线）
  getPipelineStatus:  ()    => http.get('/admin/health/pipeline-status'),
  getLlmStatus:       ()    => http.get('/admin/health/llm-status'),
  retryStuckDoc:      (data: { document_id: string; action: string; space_type?: string; space_id?: string }) =>
    http.post('/admin/health/retry-stuck', data),
  retryAllFailed:     ()    => http.post('/admin/health/retry-all-failed'),
  triggerRecovery:    ()    => http.post('/admin/health/trigger-recovery'),
  resetStuckBlueprint:(blueprintId: string) =>
    http.post('/admin/health/reset-stuck-blueprint', { blueprint_id: blueprintId }),
}

// ══ 八维度学习增强系统 API ════════════════════════════════════

// D6：学习节奏偏好
export const learningModeApi = {
  get: () =>
    http.get('/learners/me/learning-mode'),
  set: (readMode: 'skim' | 'normal' | 'deep') =>
    http.post('/learners/me/learning-mode', { read_mode: readMode }),
}

// D7：章末反思
export const reflectApi = {
  get: (chapterId: string) =>
    http.get(`/learners/me/reflect/${chapterId}`),
  submit: (data: { chapter_id: string; own_example: string; misconception?: string }) =>
    http.post('/learners/me/reflect', data),
}

// D4：社区笔记
export const socialApi = {
  getNotes: (chapterId: string) =>
    http.get(`/tutorials/social-notes/${chapterId}`),
  postNote: (data: {
    tutorial_id: string; chapter_id: string
    note_type: string; content: string; is_public: boolean
  }) => http.post('/tutorials/social-notes', data),
  likeNote: (noteId: string) =>
    http.post(`/tutorials/social-notes/${noteId}/like`),
}

// D8：成就 + 掌握度雷达
export const achievementApi = {
  list: () =>
    http.get('/learners/me/achievements'),
  radar: (topicKey: string) =>
    http.get('/learners/me/mastery-radar', { params: { topic_key: topicKey } }),
}


// D2/D7：主观题 AI 批改
export const rubricApi = {
  check: (data: { question_id: string; ai_rubric: string; answer: string }) =>
    http.post('/learners/me/rubric-check', data),
}

// H-5：关联知识推荐
export const recommendApi = {
  getRelated: (chapterId: string) =>
    http.get('/learners/me/related-recommendations', { params: { chapter_id: chapterId } }),
}

// H-6：错题模式
export const errorPatternApi = {
  get: () => http.get('/learners/me/error-patterns'),
}

// 个人笔记
export const notesApi = {
  list:   (params?: { topic_key?: string; keyword?: string }) =>
    http.get('/learners/me/notes', { params }),
  create: (data: {
    title?: string; content: string; source_type?: string
    topic_key?: string; chapter_id?: string; chapter_title?: string
    conversation_id?: string; tags?: string[]
  }) => http.post('/learners/me/notes', data),
  update: (noteId: string, data: { title?: string; content?: string; tags?: string[] }) =>
    http.put(`/learners/me/notes/${noteId}`, data),
  remove: (noteId: string) =>
    http.delete(`/learners/me/notes/${noteId}`),
  aiMerge: (noteIds: string[], notebookId?: string) =>
    http.post('/learners/me/notes/ai-merge', { note_ids: noteIds, notebook_id: notebookId || '' }),
  getByEntity: (entityId: string) =>
    http.get(`/learners/me/notes/by-entity/${entityId}`),
}

// 对话重命名
export const convRenameApi = {
  rename: (conversationId: string, title: string) =>
    http.put(`/teaching/conversations/${conversationId}/title`, { title }),
}

// 笔记本
export const notebooksApi = {
  list:   () => http.get('/learners/me/notebooks'),
  create: (data: { name: string; topic_key?: string }) =>
    http.post('/learners/me/notebooks', data),
  rename: (notebookId: string, name: string) =>
    http.put(`/learners/me/notebooks/${notebookId}`, { name }),
  remove: (notebookId: string) =>
    http.delete(`/learners/me/notebooks/${notebookId}`),
  moveNote: (noteId: string, notebookId: string | null) =>
    http.put(`/learners/me/notes/${noteId}/notebook`, { notebook_id: notebookId }),
}


// 学习仪表板 (Phase 9.3)
export const dashboardApi = {
  get: () => http.get('/learners/me/dashboard'),
}

// 复习提醒
export const reviewApi = {
  getDue:       () => http.get('/learners/me/notes/due-review'),
  markReviewed: (noteId: string) => http.post(`/learners/me/notes/${noteId}/reviewed`, {}),
}

// 证书下载
export const certificateApi = {
  download: (topicKey: string) =>
    http.get(`/learners/me/certificate`, {
      params: { topic_key: topicKey },
      responseType: 'blob',
    }),
}

// ── 课程讨论区 (Phase 3a) ────────────────────────────────────
export const discussApi = {
  listPosts: (spaceId: string, params?: { chapter_id?: string; post_type?: string; limit?: number; offset?: number }) =>
    http.get(`/discuss/spaces/${spaceId}/posts`, { params }),
  createPost: (spaceId: string, data: { post_type: string; title?: string; content: string; chapter_id?: string }) =>
    http.post(`/discuss/spaces/${spaceId}/posts`, data),
  deletePost: (postId: string) =>
    http.delete(`/discuss/posts/${postId}`),
  listReplies: (postId: string) =>
    http.get(`/discuss/posts/${postId}/replies`),
  createReply: (postId: string, content: string) =>
    http.post(`/discuss/posts/${postId}/replies`, { content }),
  deleteReply: (replyId: string) =>
    http.delete(`/discuss/replies/${replyId}`),
  feed: (limit = 30) =>
    http.get('/discuss/feed', { params: { limit } }),
  listSourcePosts: (spaceId: string, params?: { chapter_id?: string; limit?: number }) =>
    http.get(`/discuss/spaces/${spaceId}/source-posts`, { params }),
}


// 学习墙
export const wallApi = {
  list:    (params?: { chapter_id?: string; space_id?: string; post_type?: string; status?: string }) =>
    http.get('/wall/posts', { params }),
  listBySpace: (spaceId: string, params?: { post_type?: string; status?: string }) =>
    http.get('/wall/posts', { params: { space_id: spaceId, ...params } }),
  create:  (data: { chapter_id: string; topic_key?: string; space_id?: string; post_type: string; content: string }) =>
    http.post('/wall/posts', data),
  replies: (postId: string) =>
    http.get(`/wall/posts/${postId}/replies`),
  reply:   (postId: string, content: string) =>
    http.post(`/wall/posts/${postId}/replies`, { content }),
  resolve: (postId: string) =>
    http.post(`/wall/posts/${postId}/resolve`, {}),
  like:    (postId: string) =>
    http.post(`/wall/posts/${postId}/like`, {}),
  joined:  (params?: { limit?: number; offset?: number }) =>
    http.get('/wall/posts/joined', { params }),
}


// ── Space (社交学习 Phase 1) ────────────────────────────────
export const spaceApi = {
  list: () =>
    http.get('/spaces'),
  get: (spaceId: string) =>
    http.get(`/spaces/${spaceId}`),
  update: (spaceId: string, data: { name?: string; description?: string; visibility?: string; allow_fork?: boolean }) =>
    http.patch(`/spaces/${spaceId}`, data),
  listMembers: (spaceId: string) =>
    http.get(`/spaces/${spaceId}/members`),
  removeMember: (spaceId: string, userId: string) =>
    http.delete(`/spaces/${spaceId}/members/${userId}`),
  resetInviteCode: (spaceId: string) =>
    http.post(`/spaces/${spaceId}/invite-code`),
  revokeInviteCode: (spaceId: string) =>
    http.delete(`/spaces/${spaceId}/invite-code`),
  joinByCode: (code: string) =>
    http.post('/spaces/join', { code }),
  subscribe:   (spaceId: string, topicKey: string) =>
    http.post(`/spaces/${spaceId}/subscribe`, { topic_key: topicKey }),
  unsubscribe: (spaceId: string, topicKey: string) =>
    http.delete(`/spaces/${spaceId}/subscribe/${topicKey}`),
  checkUpdate: (spaceId: string, topicKey: string) =>
    http.get(`/spaces/${spaceId}/subscribe/${topicKey}/check`),
  ackUpdate:   (spaceId: string, topicKey: string) =>
    http.post(`/spaces/${spaceId}/subscribe/${topicKey}/ack`),
  listSubscriptions: () => http.get('/subscriptions'),
  fork: (spaceId: string, name?: string) =>
    http.post(`/spaces/${spaceId}/fork`, { name: name || null }),
  getForkStatus: (taskId: string) =>
    http.get(`/fork-tasks/${taskId}`),
  joinPublic: (spaceId: string) =>
    http.post(`/spaces/${spaceId}/join-public`),
  listPublic: (limit = 20, offset = 0) =>
    http.get('/spaces/public', { params: { limit, offset } }),
  listEntities: (spaceId: string, limit = 100, offset = 0) =>
    http.get(`/spaces/${spaceId}/entities`, { params: { limit, offset } }),
  getBlueprint: (spaceId: string) =>
    http.get(`/spaces/${spaceId}/blueprint`),
  getChapters: (spaceId: string) =>
    http.get(`/spaces/${spaceId}/chapters`),
  // 删除与回收站
  deleteSpace: (spaceId: string) =>
    http.delete(`/spaces/${spaceId}`),
  restoreSpace: (spaceId: string) =>
    http.post(`/spaces/${spaceId}/restore`),
  permanentDelete: (spaceId: string) =>
    http.delete(`/spaces/${spaceId}/permanent`),
  listTrash: (limit = 20, offset = 0) =>
    http.get('/spaces/trash', { params: { limit, offset } }),
  emptyTrash: () =>
    http.delete('/spaces/trash'),
  getDeletionImpact: (spaceId: string) =>
    http.get(`/spaces/${spaceId}/deletion-impact`),
  getPublicInfo: (spaceId: string) =>
    http.get(`/spaces/${spaceId}/public-info`),
}

export const profileApi = {
  update: (data: { nickname?: string; avatar_url?: string }) =>
    http.patch('/users/me', data),
  changePassword: (data: { old_password: string; new_password: string }) =>
    http.post('/users/me/password', data),
  uploadAvatar: (form: FormData) =>
    http.post('/users/me/avatar', form, { headers: { 'Content-Type': 'multipart/form-data' } }),
  deactivate: () => http.delete('/users/me'),
}

export const communityApi = {
 submit: (payload: { entity_id: string; space_id: string; tags?: string[]; note?: string }) =>
   http.post('/community/curate', payload),
 list: (params?: { space_id?: string; tag?: string; limit?: number; offset?: number }) =>
   http.get('/community/curations', { params }),
 listPending: (params?: { limit?: number; offset?: number }) =>
   http.get('/community/curations/pending', { params }),
 review: (curationId: string, status: 'approved' | 'rejected') =>
   http.patch(`/community/curations/${curationId}`, { status }),
}

export const notificationApi = {
  list: (params?: any) => http.get('/notifications', { params }),
  markRead: (id: string) => http.post(`/notifications/${id}/read`),
  markAllRead: () => http.post('/notifications/read-all'),
}
