<script setup lang="ts">
import { useRouter } from 'vue-router'
import { useAdminSession } from './session'

const session = useAdminSession()
const router = useRouter()
async function logout(): Promise<void> { await session.logout(); await router.push('/login') }
</script>

<template>
  <main>
    <header v-if="session.authenticated.value">
      <div><strong>Clip Agent Admin</strong><small>运营与账户安全</small></div>
      <nav aria-label="管理员导航">
        <RouterLink to="/">概览</RouterLink>
        <RouterLink to="/users">用户管理</RouterLink>
        <RouterLink to="/tasks">任务监控</RouterLink>
        <RouterLink to="/cdks">CDK 管理</RouterLink>
        <RouterLink to="/audit-logs">审计日志</RouterLink>
        <RouterLink to="/ads">广告管理</RouterLink>
      </nav>
      <button class="ghost" type="button" @click="logout">退出</button>
    </header>
    <RouterView />
  </main>
</template>
