<template>
  <el-container class="layout">
    <el-aside width="220px" class="sidebar">
      <div class="logo">📚 学习平台</div>
      <el-menu :default-active="route.path" router>
        <el-menu-item index="/">
          <el-icon><House /></el-icon>学习首页
        </el-menu-item>
        <el-menu-item index="/profile">
          <el-icon><UserFilled /></el-icon>学习画像
        </el-menu-item>
        <el-menu-item index="/quiz">
          <el-icon><EditPen /></el-icon>定位自检
        </el-menu-item>
        <el-menu-item index="/gaps">
          <el-icon><Warning /></el-icon>知识漏洞
        </el-menu-item>
        <el-menu-item index="/path">
          <el-icon><Guide /></el-icon>学习路径
        </el-menu-item>
        <el-menu-item index="/tutorial">
          <el-icon><Reading /></el-icon>教程中心
        </el-menu-item>
        <el-menu-item index="/chat">
          <el-icon><ChatDotRound /></el-icon>AI 对话
        </el-menu-item>
        <el-menu-item index="/upload">
          <el-icon><Upload /></el-icon>上传资料
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

const route  = useRoute()
const router = useRouter()
const auth   = useAuthStore()

const titleMap: Record<string, string> = {
  '/':         '学习首页',
  '/profile':  '学习画像',
  '/quiz':     '定位自检',
  '/gaps':     '知识漏洞',
  '/path':     '学习路径',
  '/tutorial': '教程中心',
  '/chat':     'AI 对话',
  '/upload':   '上传资料',
  '/admin':    '管理后台',
}
const pageTitle = computed(() => titleMap[route.path] || '自适应学习平台')
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
