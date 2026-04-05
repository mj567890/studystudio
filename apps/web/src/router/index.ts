import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/login',    component: () => import('@/views/auth/LoginView.vue') },
    { path: '/register', component: () => import('@/views/auth/RegisterView.vue') },
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
      ]
    },
    { path: '/:pathMatch(.*)*', redirect: '/' }
  ]
})

router.beforeEach(async (to) => {
  const auth = useAuthStore()
  if (to.meta.requiresAuth && !auth.isLoggedIn) return '/login'
  if (to.meta.requiresAdmin && !auth.isAdmin) return '/'
  if (auth.isLoggedIn && !auth.user) {
    try { await auth.fetchMe() } catch { auth.logout(); return '/login' }
  }
})

export default router
