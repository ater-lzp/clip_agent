<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ApiError } from '../api/client'
import { useSession } from '../composables/useSession'

const props = defineProps<{ mode: 'login' | 'register' }>()
const email = ref('')
const password = ref('')
const confirmPassword = ref('')
const errorMessage = ref('')
const busy = ref(false)
const router = useRouter()
const route = useRoute()
const session = useSession()
const isRegister = computed(() => props.mode === 'register')

async function submit(): Promise<void> {
  errorMessage.value = ''
  if (isRegister.value && password.value !== confirmPassword.value) {
    errorMessage.value = '两次输入的密码不一致'
    return
  }
  busy.value = true
  try {
    if (isRegister.value) await session.register(email.value, password.value)
    else await session.login(email.value, password.value)
    const redirect = typeof route.query.redirect === 'string' ? route.query.redirect : '/tasks'
    await router.push(redirect.startsWith('/') ? redirect : '/tasks')
  } catch (error) {
    errorMessage.value = error instanceof ApiError ? error.message : '暂时无法完成登录，请重试'
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="auth-layout">
    <section class="auth-pitch">
      <div class="brand large"><span class="brand-mark">C</span><strong>Clip Agent</strong></div>
      <p class="eyebrow">From idea to aligned video</p>
      <h1>把创意交给流程，<br />把决定留给你。</h1>
      <p>剧本与分镜逐步审核，真实配音时长驱动画面，可随时刷新、离开并安全恢复。</p>
      <div class="pitch-steps" aria-hidden="true">
        <span>01 剧本</span><i></i><span>02 分镜</span><i></i><span>03 成片</span>
      </div>
    </section>
    <section class="auth-card" :aria-labelledby="`${mode}-heading`">
      <p class="eyebrow">{{ isRegister ? '开始创作' : '欢迎回来' }}</p>
      <h2 :id="`${mode}-heading`">{{ isRegister ? '创建账号' : '登录工作台' }}</h2>
      <p class="muted">{{ isRegister ? '你的任务和媒体只对当前账号可见。' : '继续上次中断的创作流程。' }}</p>
      <form @submit.prevent="submit">
        <label for="email">邮箱</label>
        <input id="email" v-model.trim="email" type="email" autocomplete="email" required maxlength="254" />
        <label for="password">密码</label>
        <input
          id="password"
          v-model="password"
          type="password"
          :autocomplete="isRegister ? 'new-password' : 'current-password'"
          minlength="10"
          maxlength="128"
          required
        />
        <template v-if="isRegister">
          <label for="confirm-password">确认密码</label>
          <input
            id="confirm-password"
            v-model="confirmPassword"
            type="password"
            autocomplete="new-password"
            minlength="10"
            maxlength="128"
            required
          />
        </template>
        <p v-if="errorMessage" class="form-error" role="alert">{{ errorMessage }}</p>
        <button class="button primary full" type="submit" :disabled="busy">
          {{ busy ? '请稍候…' : isRegister ? '注册并进入' : '登录' }}
        </button>
      </form>
      <p class="auth-switch">
        {{ isRegister ? '已有账号？' : '还没有账号？' }}
        <RouterLink :to="isRegister ? '/login' : '/register'">{{ isRegister ? '直接登录' : '创建账号' }}</RouterLink>
      </p>
    </section>
  </div>
</template>

