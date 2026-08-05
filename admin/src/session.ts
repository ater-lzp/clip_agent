import { computed, readonly, ref } from 'vue'
import { request } from './api'

interface AdminIdentity { id:string; email:string; nickname:string|null; role:'user'|'admin' }
const user = ref<AdminIdentity|null>(null)
let restored = false

async function restore(): Promise<void> {
  if (restored) return
  try {
    const identity = await request<AdminIdentity>('/api/v1/auth/me')
    user.value = identity.role === 'admin' ? identity : null
  } catch { user.value = null }
  restored = true
}

export function useAdminSession() {
  return {
    user: readonly(user),
    authenticated: computed(() => user.value !== null),
    restore,
    async login(email: string, password: string) {
      const identity = await request<AdminIdentity>('/api/v1/auth/login', { method: 'POST', body: { email, password } })
      if (identity.role !== 'admin') {
        await request('/api/v1/auth/session', { method: 'DELETE' }).catch(() => undefined)
        throw new Error('该账户不是管理员')
      }
      user.value = identity
      restored = true
    },
    async logout() {
      try { await request('/api/v1/auth/session', { method: 'DELETE' }) }
      finally { user.value = null; restored = true }
    },
  }
}
