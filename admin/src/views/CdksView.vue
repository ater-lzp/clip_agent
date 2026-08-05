<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { request, type CdkItem, type Page } from '../api'
import PaginationBar from '../components/PaginationBar.vue'
import { formatDate, money, yuanToCents } from '../utils'

interface GeneratedCdk { code: string; amount_cents: number }
const cdks = ref<CdkItem[]>([])
const generated = ref<GeneratedCdk[]>([])
const amountYuan = ref(100)
const count = ref(1)
const status = ref<'' | 'unused' | 'used'>('')
const page = ref(1)
const pages = ref(0)
const total = ref(0)
const loading = ref(true)
const busy = ref(false)
const error = ref('')
const notice = ref('')
const generatedTotal = computed(() => generated.value.reduce((sum, item) => sum + item.amount_cents, 0))

async function load(reset = false): Promise<void> {
  if (reset) page.value = 1
  loading.value = true
  error.value = ''
  const params = new URLSearchParams({ page: String(page.value), page_size: '30' })
  if (status.value) params.set('status', status.value)
  try {
    const result = await request<Page<CdkItem>>(`/api/v1/admin/cdks?${params}`)
    cdks.value = result.items
    pages.value = result.pages
    total.value = result.total
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : 'CDK 加载失败'
  } finally {
    loading.value = false
  }
}

async function createCdks(): Promise<void> {
  busy.value = true
  error.value = ''
  notice.value = ''
  try {
    const amountCents = yuanToCents(amountYuan.value)
    const value = await request<{ items: GeneratedCdk[] }>('/api/v1/admin/cdks', {
      method: 'POST', body: { amount_cents: amountCents, count: count.value },
    })
    generated.value = value.items
    notice.value = `已生成 ${value.items.length} 个 CDK，请立即保存完整兑换码`
    await load(true)
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '生成失败'
  } finally {
    busy.value = false
  }
}

async function copyGenerated(): Promise<void> {
  await navigator.clipboard.writeText(generated.value.map((item) => `${item.code},${money(item.amount_cents)}`).join('\n'))
  notice.value = '本批 CDK 已复制到剪贴板'
}

function exportGenerated(): void {
  const csv = `code,amount_yuan\n${generated.value.map((item) => `${item.code},${(item.amount_cents / 100).toFixed(2)}`).join('\n')}`
  const url = URL.createObjectURL(new Blob([`\uFEFF${csv}`], { type: 'text/csv;charset=utf-8' }))
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = `clip-agent-cdks-${Date.now()}.csv`
  anchor.click()
  URL.revokeObjectURL(url)
}

async function changePage(value: number): Promise<void> { page.value = value; await load() }
onMounted(load)
</script>

<template>
  <section class="content">
    <div class="heading"><div><p class="eyebrow">Recharge codes</p><h1>CDK 管理</h1></div><select v-model="status" aria-label="CDK 状态" @change="load(true)"><option value="">全部状态</option><option value="unused">未使用</option><option value="used">已使用</option></select></div>
    <p v-if="notice" class="notice" role="status">{{ notice }}</p><p v-if="error" class="error" role="alert">{{ error }}</p>
    <form class="cdk-form" data-testid="cdk-form" @submit.prevent="createCdks">
      <label>面额（元）<input v-model.number="amountYuan" data-testid="cdk-amount-yuan" type="number" min="0.01" max="10000" step="0.01" required /></label>
      <div class="presets" aria-label="快捷面额"><button v-for="preset in [10, 30, 50, 100, 200, 500]" :key="preset" class="secondary small" type="button" @click="amountYuan = preset">¥{{ preset }}</button></div>
      <label>数量<input v-model.number="count" type="number" min="1" max="100" required /></label>
      <button :disabled="busy">{{ busy ? '正在生成…' : '生成 CDK' }}</button>
    </form>
    <div v-if="generated.length" class="generated"><div class="card-heading"><div><strong>本批完整 CDK（仅本次显示）</strong><small>{{ generated.length }} 个 · 总面额 {{ money(generatedTotal) }}</small></div><div class="row-actions"><button class="secondary small" type="button" @click="copyGenerated">复制全部</button><button class="secondary small" type="button" @click="exportGenerated">导出 CSV</button></div></div><code v-for="item in generated" :key="item.code">{{ item.code }} · {{ money(item.amount_cents) }}</code></div>
    <p v-if="loading">CDK 加载中…</p>
    <div v-else-if="!cdks.length" class="empty surface-card">当前筛选下暂无 CDK</div>
    <div v-else class="table-wrap"><table><thead><tr><th>CDK 提示</th><th>面额</th><th>状态</th><th>使用者</th><th>创建时间</th><th>使用时间</th></tr></thead><tbody><tr v-for="item in cdks" :key="item.id"><td><code>{{ item.code_hint }}</code></td><td>{{ money(item.amount_cents) }}</td><td><span :class="item.status === 'used' ? 'stopped' : 'ok'">{{ item.status === 'used' ? '已使用' : '未使用' }}</span></td><td>{{ item.used_by_nickname || item.used_by_email || '—' }}</td><td>{{ formatDate(item.created_at) }}</td><td>{{ formatDate(item.used_at) }}</td></tr></tbody></table></div>
    <PaginationBar :page="page" :pages="pages" :total="total" :busy="loading" @change="changePage" />
  </section>
</template>
