import { computed, readonly, ref } from 'vue'
import { authApi } from '../api'
import { ApiError } from '../api/client'
import type { User } from '../types/domain'

const user = ref<User | null>(null)
const restoring = ref(false)
let restored = false

async function restore(): Promise<void> {
  if (restored || restoring.value) return
  restoring.value = true
  try {
    user.value = await authApi.me()
  } catch (error) {
    if (!(error instanceof ApiError) || error.status !== 401) throw error
    user.value = null
  } finally {
    restored = true
    restoring.value = false
  }
}

async function refresh(): Promise<void> {
  user.value = await authApi.me()
  restored = true
}

function clear(): void {
  user.value = null
  restored = true
}

window.addEventListener('clip:unauthorized', clear)

export function useSession() {
  return {
    user: readonly(user),
    restoring: readonly(restoring),
    authenticated: computed(() => user.value !== null),
    restore,
    refresh,
    setUser(value: User) {
      user.value = value
      restored = true
    },
    async login(email: string, password: string) {
      user.value = await authApi.login(email, password)
      restored = true
    },
    async register(email: string, password: string) {
      user.value = await authApi.register(email, password)
      restored = true
    },
    async logout() {
      try {
        await authApi.logout()
      } finally {
        clear()
      }
    },
    clear,
  }
}
