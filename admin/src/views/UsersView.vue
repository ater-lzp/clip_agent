<script setup lang="ts">
import { nextTick, onMounted, ref } from 'vue'
import { request, type AdminUser, type AdminUserDetail, type MembershipTier, type Page, type UserRole } from '../api'
import PaginationBar from '../components/PaginationBar.vue'
import { formatDate, money } from '../utils'

const users = ref<AdminUser[]>([])
const query = ref('')
const active = ref<'' | 'true' | 'false'>('')
const role = ref<'' | UserRole>('')
const membership = ref<'' | MembershipTier>('')
const page = ref(1)
const pages = ref(0)
const total = ref(0)
const loading = ref(true)
const busy = ref(false)
const error = ref('')
const notice = ref('')
const detail = ref<AdminUserDetail | null>(null)
const passwordUser = ref<AdminUser | null>(null)
const newPassword = ref('')
const confirmPassword = ref('')
const dialog = ref<HTMLElement | null>(null)

async function load(reset = false): Promise<void> {
  if (reset) page.value = 1
  loading.value = true
  error.value = ''
  const params = new URLSearchParams({ page: String(page.value), page_size: '30' })
  if (query.value.trim()) params.set('q', query.value.trim())
  if (active.value) params.set('active', active.value)
  if (role.value) params.set('role', role.value)
  if (membership.value) params.set('membership', membership.value)
  try {
    const result = await request<Page<AdminUser>>(`/api/v1/admin/users?${params}`)
    users.value = result.items
    pages.value = result.pages ?? (result.items.length ? 1 : 0)
    total.value = result.total ?? result.items.length
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '用户加载失败'
  } finally {
    loading.value = false
  }
}

async function updateUser(user: AdminUser, patch: Partial<Pick<AdminUser, 'is_active' | 'role' | 'generation_quota'>>): Promise<void> {
  busy.value = true
  error.value = ''
  notice.value = ''
  try {
    await request(`/api/v1/admin/users/${user.id}`, { method: 'PATCH', body: patch })
    notice.value = `已更新 ${user.email}`
    await load()
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '更新失败'
  } finally {
    busy.value = false
  }
}

async function openDetail(user: AdminUser): Promise<void> {
  error.value = ''
  try {
    detail.value = await request<AdminUserDetail>(`/api/v1/admin/users/${user.id}`)
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '用户详情加载失败'
  }
}

async function openPassword(user: AdminUser): Promise<void> {
  passwordUser.value = user
  newPassword.value = ''
  confirmPassword.value = ''
  error.value = ''
  await nextTick()
  dialog.value?.focus()
}

function closePassword(): void { if (!busy.value) passwordUser.value = null }

async function resetPassword(): Promise<void> {
  if (!passwordUser.value) return
  busy.value = true
  error.value = ''
  notice.value = ''
  try {
    await request(`/api/v1/admin/users/${passwordUser.value.id}/password`, {
      method: 'POST',
      body: { new_password: newPassword.value, confirm_password: confirmPassword.value },
    })
    notice.value = `已重置 ${passwordUser.value.email} 的登录密码，原会话已失效`
    passwordUser.value = null
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '密码修改失败'
  } finally {
    busy.value = false
  }
}

async function changePage(value: number): Promise<void> { page.value = value; await load() }
onMounted(load)
</script>

<template>
  <section class="content">
    <div class="heading"><div><p class="eyebrow">Accounts</p><h1>用户管理</h1></div><button class="secondary" type="button" :disabled="loading" @click="load()">刷新</button></div>
    <form class="filters" @submit.prevent="load(true)">
      <label>搜索<input v-model="query" placeholder="邮箱或昵称" /></label>
      <label>账户状态<select v-model="active" @change="load(true)"><option value="">全部状态</option><option value="true">启用</option><option value="false">停用</option></select></label>
      <label>角色<select v-model="role" @change="load(true)"><option value="">全部角色</option><option value="user">普通用户</option><option value="admin">管理员</option></select></label>
      <label>会员<select v-model="membership" @change="load(true)"><option value="">全部会员</option><option value="free">免费</option><option value="vip">VIP</option><option value="svip">SVIP</option></select></label>
      <button type="submit">查询</button>
    </form>
    <p v-if="notice" class="notice" role="status">{{ notice }}</p>
    <p v-if="error" class="error" role="alert">{{ error }}</p>
    <p v-if="loading">用户加载中…</p>
    <div v-else-if="!users.length" class="empty surface-card">没有符合条件的用户</div>
    <div v-else class="table-wrap"><table><thead><tr><th>用户</th><th>角色</th><th>会员</th><th>余额</th><th>任务</th><th>额度</th><th>状态</th><th>操作</th></tr></thead><tbody><tr v-for="user in users" :key="user.id"><td><strong>{{ user.nickname || '未设置昵称' }}</strong><small>{{ user.email }}</small></td><td><select :value="user.role" :disabled="busy" @change="updateUser(user, { role: ($event.target as HTMLSelectElement).value as UserRole })"><option value="user">用户</option><option value="admin">管理员</option></select></td><td><span class="membership-pill" :data-tier="user.membership_tier">{{ user.membership_tier.toUpperCase() }}</span><small>{{ formatDate(user.membership_expires_at) }}</small></td><td>{{ money(user.balance_cents) }}</td><td>{{ user.task_count ?? '—' }}</td><td><input class="quota" type="number" :value="user.generation_quota" :min="user.generations_used" :disabled="busy" @change="updateUser(user, { generation_quota: Number(($event.target as HTMLInputElement).value) })" /><small>已用 {{ user.generations_used }} / 剩余 {{ user.generations_remaining }}</small></td><td><span :class="user.is_active ? 'ok' : 'stopped'">{{ user.is_active ? '启用' : '停用' }}</span></td><td><div class="row-actions"><button class="small secondary" type="button" :disabled="busy" @click="openDetail(user)">详情</button><button class="small" type="button" :disabled="busy" @click="updateUser(user, { is_active: !user.is_active })">{{ user.is_active ? '停用' : '启用' }}</button><button class="small secondary" :data-testid="`reset-password-${user.id}`" type="button" :disabled="busy" @click="openPassword(user)">修改密码</button></div></td></tr></tbody></table></div>
    <PaginationBar :page="page" :pages="pages" :total="total" :busy="loading" @change="changePage" />

    <div v-if="detail" class="admin-modal-backdrop" @mousedown.self="detail = null"><section class="admin-modal detail-modal" role="dialog" aria-modal="true" aria-labelledby="detail-title"><div class="heading"><div><p class="eyebrow">User detail</p><h2 id="detail-title">{{ detail.nickname || detail.email }}</h2></div><button class="close" type="button" aria-label="关闭详情" @click="detail = null">×</button></div><dl class="detail-grid"><div><dt>邮箱</dt><dd>{{ detail.email }}</dd></div><div><dt>注册时间</dt><dd>{{ formatDate(detail.created_at) }}</dd></div><div><dt>任务总数</dt><dd>{{ detail.task_count }}</dd></div><div><dt>完成 / 失败</dt><dd>{{ detail.completed_task_count }} / {{ detail.failed_task_count }}</dd></div><div><dt>余额</dt><dd>{{ money(detail.balance_cents) }}</dd></div><div><dt>剩余额度</dt><dd>{{ detail.generations_remaining }}</dd></div></dl><h3>最近余额流水</h3><div v-if="!detail.recent_ledger.length" class="empty">暂无流水</div><div v-for="entry in detail.recent_ledger" :key="entry.id" class="compact-row"><div><strong>{{ entry.kind === 'cdk_recharge' ? 'CDK 充值' : '会员支付' }}</strong><small>{{ formatDate(entry.created_at) }}</small></div><span>{{ entry.amount_cents > 0 ? '+' : '' }}{{ money(entry.amount_cents) }}</span></div></section></div>

    <div v-if="passwordUser" class="admin-modal-backdrop" @mousedown.self="closePassword"><section ref="dialog" class="admin-modal" role="dialog" aria-modal="true" aria-labelledby="password-title" tabindex="-1" @keydown.esc="closePassword"><div class="heading"><div><p class="eyebrow">Security</p><h2 id="password-title">修改用户密码</h2></div><button class="close" type="button" @click="closePassword">×</button></div><p>{{ passwordUser.email }}</p><form data-testid="password-reset-form" @submit.prevent="resetPassword"><label>新密码<input v-model="newPassword" type="password" minlength="8" maxlength="128" required autocomplete="new-password" /></label><label>确认新密码<input v-model="confirmPassword" type="password" minlength="8" maxlength="128" required autocomplete="new-password" /></label><small>必须包含大写字母、小写字母和数字。修改后该用户的所有登录会话立即失效。</small><p v-if="error" class="error" role="alert">{{ error }}</p><div class="modal-actions"><button class="secondary" type="button" :disabled="busy" @click="closePassword">取消</button><button data-testid="confirm-password-reset" type="submit" :disabled="busy">{{ busy ? '正在修改…' : '确认修改' }}</button></div></form></section></div>
  </section>
</template>
