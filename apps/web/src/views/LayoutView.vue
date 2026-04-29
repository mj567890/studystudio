<template>
  <el-container class="layout">
    <el-aside width="220px" class="sidebar">
      <div class="logo">📚 StudyStudio</div>
      <el-menu :default-active="route.path" router>
        <el-menu-item index="/">
          <el-icon><House /></el-icon>首页
        </el-menu-item>
        <el-divider style="margin:8px 0;border-color:#2d3f50" />
        <div style="padding:4px 20px 2px;font-size:11px;color:#5a7a9a;letter-spacing:1px">学习</div>
        <el-menu-item index="/tutorial">
          <el-icon><Reading /></el-icon>课程学习
        </el-menu-item>
        <el-menu-item index="/chat">
          <el-icon><ChatDotRound /></el-icon>AI 对话
        </el-menu-item>
        <el-menu-item index="/gaps">
          <el-icon><Warning /></el-icon>薄弱环节
        </el-menu-item>
        <el-divider style="margin:8px 0;border-color:#2d3f50" />
        <div style="padding:4px 20px 2px;font-size:11px;color:#5a7a9a;letter-spacing:1px">资源</div>
        <el-menu-item index="/spaces">
          <el-icon><FolderOpened /></el-icon>课程信息
        </el-menu-item>
        <el-menu-item index="/upload">
          <el-icon><Upload /></el-icon>资料库
        </el-menu-item>
        <el-menu-item index="/notes">
          <el-icon><Notebook /></el-icon>我的笔记
        </el-menu-item>
        <el-menu-item index="/templates">
          <el-icon><Document /></el-icon>课程模板
        </el-menu-item>
        <el-divider style="margin:8px 0;border-color:#2d3f50" />
        <div style="padding:4px 20px 2px;font-size:11px;color:#5a7a9a;letter-spacing:1px">社区</div>
        <el-menu-item index="/discuss">
          <el-icon><Comment /></el-icon>讨论
        </el-menu-item>
        <el-menu-item index="/community">
          <el-icon><Star /></el-icon>发现课程
        </el-menu-item>
        <el-divider style="margin:8px 0;border-color:#2d3f50" />
        <el-menu-item index="/profile">
          <el-icon><UserFilled /></el-icon>账号设置
        </el-menu-item>
        <el-divider v-if="auth.isAdmin" style="margin:8px 0;border-color:#2d3f50" />
        <el-menu-item v-if="auth.isAdmin" index="/admin">
          <el-icon><Setting /></el-icon>管理后台
        </el-menu-item>
      </el-menu>
    </el-aside>
    <el-container>
      <el-header class="header">
        <span class="page-title">{{ pageTitle }}</span>
        <div class="user-info">
          <NotificationBell style="margin-right:12px" />
          <el-tag size="small" v-if="auth.isAdmin" type="danger" style="margin-right:8px">管理员</el-tag>
          <span>{{ auth.user?.nickname }}</span>
          <el-button text @click="auth.logout(); router.push('/login')">退出</el-button>
        </div>
      </el-header>
      <el-main class="main">
        <router-view />
      </el-main>
    </el-container>
  </el-container>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import NotificationBell from '@/components/NotificationBell.vue'

const route  = useRoute()
const router = useRouter()
const auth   = useAuthStore()

const titleMap: Record<string, string> = {
  '/':          '首页',
  '/profile':   '账号设置',
  '/gaps':      '薄弱环节',
  '/tutorial':  '学习',
  '/chat':      'AI 对话',
  '/upload':    '资料库',
  '/spaces':    '我的课程',
  '/community': '发现课程',
  '/discuss':   '讨论',
  '/notes':     '我的笔记',
  '/templates': '课程模板',
  '/admin':     '管理后台',
}
const pageTitle = computed(() => titleMap[route.path] || 'StudyStudio')
</script>

<style scoped>
.layout  { height: 100vh; }
.sidebar { background: #1d2b3a; }
.logo    { color: #fff; font-size: 18px; font-weight: bold; padding: 20px; }
.sidebar .el-menu { border-right: none; background: #1d2b3a; }
.sidebar .el-menu-item { color: #c0c4cc; }
.sidebar .el-menu-item.is-active,
.sidebar .el-menu-item:hover { background: #2d3f50 !important; color: #fff; }
.header { display: flex; align-items: center; justify-content: space-between;
          border-bottom: 1px solid #eee; background: #fff; }
.page-title { font-size: 18px; font-weight: 600; color: #303133; }
.user-info  { display: flex; align-items: center; gap: 8px; color: #606266; }
.main { background: #f5f7fa; }
</style>
