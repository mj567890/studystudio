import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { installApi } from '@/api'

// 安装状态缓存（避免每次导航都请求）
let _initCompleted: boolean | null = null

async function checkInitCompleted(): Promise<boolean> {
  if (_initCompleted !== null) return _initCompleted
  try {
    const res: any = await installApi.getStatus()
    _initCompleted = !!res.data?.init_completed
  } catch {
    // 网络错误时不阻塞，默认为已安装
    _initCompleted = true
  }
  return _initCompleted
}

/** 安装完成后调用，清除缓存使下一次导航重新检查 */
export function invalidateInitCache() {
  _initCompleted = null
}

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/install',  component: () => import('@/views/auth/InstallView.vue') },
    { path: '/login',    component: () => import('@/views/auth/LoginView.vue') },
    { path: '/register', component: () => import('@/views/auth/RegisterView.vue') },
    { path: '/join/:code', component: () => import('@/views/JoinSpaceView.vue') },
    {
      path: '/',
      component: () => import('@/views/LayoutView.vue'),
      meta: { requiresAuth: true },
      children: [
        { path: '',         component: () => import('@/views/HomeView.vue') },
        { path: 'profile',  component: () => import('@/views/learner/ProfileView.vue') },
        { path: 'quiz',     component: () => import('@/views/learner/QuizView.vue') },
        { path: 'gaps',     component: () => import('@/views/learner/GapsView.vue') },
        { path: 'path',     component: () => import('@/views/learner/RepairPathView.vue') },
        { path: 'tutorial', component: () => import('@/views/tutorial/TutorialView.vue') },
        { path: 'chat',     component: () => import('@/views/tutorial/ChatView.vue') },
        { path: 'upload',   component: () => import('@/views/learner/UploadView.vue') },
        { path: 'notes',    component: () => import('@/views/learner/NotesView.vue') },
        { path: 'templates', component: () => import('@/views/learner/TemplateManageView.vue') },
        { path: 'spaces',              component: () => import('@/views/learner/SpacesView.vue') },
        { path: 'spaces/trash',          component: () => import('@/views/learner/TrashView.vue') },
        { path: 'spaces/:space_id',    component: () => import('@/views/learner/SpaceDetailView.vue') },
        { path: 'spaces/:space_id/posts', component: () => import('@/views/learner/SpacePostsView.vue') },
        { path: 'community',           component: () => import('@/views/learner/CommunityView.vue') },
        { path: 'discuss',             component: () => import('@/views/learner/DiscussView.vue') },
      ]
    },
    {
      path: '/admin',
      component: () => import('@/views/AdminLayoutView.vue'),
      meta: { requiresAuth: true, requiresAdmin: true },
      children: [
        { path: '',           component: () => import('@/views/admin/DashboardView.vue') },
        { path: 'review',     component: () => import('@/views/admin/ReviewView.vue') },
        { path: 'users',      component: () => import('@/views/admin/UsersView.vue') },
        { path: 'knowledge',  component: () => import('@/views/admin/KnowledgeView.vue') },
        { path: 'config',     component: () => import('@/views/admin/ConfigView.vue') },
        { path: 'ai-config',  component: () => import('@/views/admin/AiConfigView.vue') },
        { path: 'system-health', component: () => import('@/views/admin/SystemHealthView.vue') },
        { path: 'tasks',          component: () => import('@/views/admin/TaskManagementView.vue') },
      ]
    },
    { path: '/:pathMatch(.*)*', redirect: '/' }
  ]
})

router.beforeEach(async (to) => {
  // ── 系统安装向导：未安装 → 强制跳转 /install ──
  if (to.path === '/install') {
    const installed = await checkInitCompleted()
    if (installed) return '/login'
    return true
  }

  // 非 /install 页面：检测是否已完成安装
  const installed = await checkInitCompleted()
  if (!installed) return '/install'

  // ── 认证守卫 ──
  const auth = useAuthStore()
  if (to.meta.requiresAuth && !auth.isLoggedIn) return '/login'
  if (auth.isLoggedIn && !auth.user) {
    try { await auth.fetchMe() } catch { auth.logout(); return '/login' }
  }
  if (to.meta.requiresAdmin && !auth.isAdmin) return '/'
})

export default router
