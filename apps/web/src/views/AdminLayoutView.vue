<template>
  <el-container class="layout">
    <el-aside width="200px" class="sidebar">
      <div class="logo">⚙️ 管理后台</div>
      <el-menu :default-active="route.path" router>
        <el-menu-item index="/admin"><el-icon><DataBoard /></el-icon>管理首页</el-menu-item>
        <el-menu-item index="/admin/review"><el-icon><Check /></el-icon>知识审核</el-menu-item>
        <el-menu-item index="/admin/users"><el-icon><User /></el-icon>用户管理</el-menu-item>
        <el-menu-item index="/admin/knowledge"><el-icon><Collection /></el-icon>知识库管理</el-menu-item>
        <el-menu-item index="/admin/config"><el-icon><Tools /></el-icon>系统配置</el-menu-item>
        <el-divider style="margin:8px 0;border-color:#2d3f50" />
        <el-menu-item index="/"><el-icon><Back /></el-icon>返回学习端</el-menu-item>
      </el-menu>
    </el-aside>
    <el-container>
      <el-header class="header">
        <span>{{ pageTitle }}</span>
        <el-button text @click="auth.logout(); router.push('/login')">退出</el-button>
      </el-header>
      <el-main style="background:#f5f7fa"><router-view /></el-main>
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
  '/admin':            '管理首页',
  '/admin/review':     '知识审核',
  '/admin/users':      '用户管理',
  '/admin/knowledge':  '知识库管理',
  '/admin/config':     '系统配置',
}
const pageTitle = computed(() => titleMap[route.path] || '管理后台')
</script>

<style scoped>
.layout  { height: 100vh; }
.sidebar { background: #1d2b3a; }
.logo    { color: #fff; font-size: 16px; font-weight: bold; padding: 20px 16px; }
.sidebar .el-menu { border-right: none; background: #1d2b3a; }
.sidebar .el-menu-item { color: #c0c4cc; }
.sidebar .el-menu-item:hover,
.sidebar .el-menu-item.is-active { background: #2d3f50 !important; color: #fff; }
.header { display: flex; align-items: center; justify-content: space-between;
          border-bottom: 1px solid #eee; background: #fff; font-size: 18px; font-weight: 600; }
</style>
