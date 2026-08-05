<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { request, type AuditLog, type Page } from '../api'
import PaginationBar from '../components/PaginationBar.vue'
import { formatDate } from '../utils'

const logs = ref<AuditLog[]>([])
const query = ref('')
const action = ref('')
const page = ref(1)
const pages = ref(0)
const total = ref(0)
const loading = ref(true)
const error = ref('')

async function load(reset = false): Promise<void> {
  if (reset) page.value = 1
  loading.value = true
  error.value = ''
  const params = new URLSearchParams({ page: String(page.value), page_size: '30' })
  if (query.value.trim()) params.set('q', query.value.trim())
  if (action.value) params.set('action', action.value)
  try {
    const result = await request<Page<AuditLog>>(`/api/v1/admin/audit-logs?${params}`)
    logs.value = result.items
    pages.value = result.pages
    total.value = result.total
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '审计日志加载失败'
  } finally {
    loading.value = false
  }
}

async function changePage(value: number): Promise<void> { page.value = value; await load() }
onMounted(load)
</script>

<template>
  <section class="content">
    <div class="heading"><div><p class="eyebrow">Security trail</p><h1>审计日志</h1></div><button class="secondary" type="button" :disabled="loading" @click="load()">刷新</button></div>
    <form class="filters" @submit.prevent="load(true)">
      <label>搜索<input v-model="query" placeholder="操作者、动作或目标 ID" /></label>
      <label>安全动作<select v-model="action" @change="load(true)"><option value="">全部动作</option><option value="admin_user_updated">管理员修改用户</option><option value="admin_user_password_reset">管理员重置密码</option><option value="cdk_batch_created">生成 CDK</option><option value="cdk_redeemed">兑换 CDK</option><option value="membership_purchased">购买会员</option><option value="payment_password_set">设置支付密码</option><option value="password_changed">用户修改密码</option><option value="community_post_published">发布社区作品</option><option value="community_post_deleted">删除社区作品</option></select></label>
      <button type="submit">查询</button>
    </form>
    <p v-if="error" class="error" role="alert">{{ error }}</p>
    <p v-if="loading">审计日志加载中…</p>
    <div v-else-if="!logs.length" class="empty surface-card">暂无符合条件的审计记录</div>
    <div v-else class="table-wrap"><table><thead><tr><th>时间</th><th>操作者</th><th>动作</th><th>目标</th><th>IP 地址</th></tr></thead><tbody><tr v-for="item in logs" :key="item.id"><td>{{ formatDate(item.created_at) }}</td><td><strong>{{ item.actor_nickname || item.actor_email || '系统' }}</strong><small>{{ item.actor_id || '—' }}</small></td><td><code>{{ item.action }}</code></td><td>{{ item.target_type || '—' }}<small>{{ item.target_id || '—' }}</small></td><td><code>{{ item.ip_address }}</code></td></tr></tbody></table></div>
    <PaginationBar :page="page" :pages="pages" :total="total" :busy="loading" @change="changePage" />
  </section>
</template>
