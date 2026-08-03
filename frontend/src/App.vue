<script setup lang="ts">
import { useRouter } from 'vue-router'
import { useSession } from './composables/useSession'

const session = useSession()
const router = useRouter()

async function logout(): Promise<void> {
  await session.logout()
  await router.push('/login')
}
</script>

<template>
  <div class="app-shell">
    <header v-if="session.authenticated.value" class="topbar">
      <RouterLink class="brand" to="/tasks" aria-label="Clip Agent 首页">
        <span class="brand-mark" aria-hidden="true">C</span>
        <span><strong>Clip Agent</strong><small>短视频工作台</small></span>
      </RouterLink>
      <nav aria-label="主导航">
        <RouterLink to="/tasks">历史</RouterLink>
        <RouterLink to="/tasks/new">新建视频</RouterLink>
        <RouterLink to="/settings">设置</RouterLink>
      </nav>
      <div class="account">
        <span :title="session.user.value?.email">{{ session.user.value?.email }}</span>
        <button class="text-button" type="button" @click="logout">退出</button>
      </div>
    </header>
    <main :class="{ 'auth-main': !session.authenticated.value }">
      <RouterView />
    </main>
  </div>
</template>

