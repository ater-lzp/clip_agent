<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { request, type AdminTask, type Page, type ProviderMode, type TaskStatus } from '../api'
import PaginationBar from '../components/PaginationBar.vue'
import { formatDate, formatDuration, statusLabel } from '../utils'

const tasks = ref<AdminTask[]>([])
const query = ref('')
const status = ref<'' | TaskStatus>('')
const providerMode = ref<'' | ProviderMode>('')
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
  if (status.value) params.set('status', status.value)
  if (providerMode.value) params.set('provider_mode', providerMode.value)
  try {
    const result = await request<Page<AdminTask>>(`/api/v1/admin/tasks?${params}`)
    tasks.value = result.items
    pages.value = result.pages
    total.value = result.total
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '任务加载失败'
  } finally {
    loading.value = false
  }
}

async function changePage(value: number): Promise<void> {
  page.value = value
  await load()
}

onMounted(load)
</script>

<template>
  <section class="content">
    <div class="heading"><div><p class="eyebrow">Workflow operations</p><h1>任务监控</h1></div><button class="secondary" type="button" :disabled="loading" @click="load()">刷新</button></div>
    <form class="filters" @submit.prevent="load(true)">
      <label>搜索<input v-model="query" placeholder="主题、用户邮箱或昵称" /></label>
      <label>任务状态<select v-model="status" @change="load(true)"><option value="">全部状态</option><option value="awaiting_script_review">待审剧本</option><option value="awaiting_storyboard_review">待审分镜</option><option value="awaiting_bgm_decision">待选 BGM</option><option value="completed">已完成</option><option value="failed">失败</option><option value="processing_bgm">处理 BGM</option></select></label>
      <label>供应商模式<select v-model="providerMode" @change="load(true)"><option value="">全部模式</option><option value="real">真实服务</option><option value="fake">测试模式</option></select></label>
      <button type="submit">查询</button>
    </form>
    <p v-if="error" class="error" role="alert">{{ error }}</p>
    <p v-if="loading">任务加载中…</p>
    <div v-else-if="!tasks.length" class="empty surface-card">没有符合条件的任务</div>
    <div v-else class="table-wrap">
      <table><thead><tr><th>任务</th><th>用户</th><th>状态</th><th>模式</th><th>时长</th><th>画幅</th><th>创建时间</th><th>诊断</th></tr></thead>
        <tbody><tr v-for="task in tasks" :key="task.id"><td class="wide-cell"><strong>{{ task.topic }}</strong><small>{{ task.id }}</small></td><td><strong>{{ task.user_nickname || '未设置昵称' }}</strong><small>{{ task.user_email }}</small></td><td><span class="status-pill" :data-status="task.status">{{ statusLabel(task.status) }}</span><small>{{ task.current_stage }}</small></td><td><span class="mode-pill" :data-mode="task.provider_mode">{{ task.provider_mode === 'real' ? 'REAL' : 'FAKE' }}</span></td><td>{{ formatDuration(task.final_duration_seconds ?? task.target_duration_seconds) }}<small>目标 {{ formatDuration(task.target_duration_seconds) }}</small></td><td>{{ task.aspect_ratio }}</td><td>{{ formatDate(task.created_at) }}</td><td><span v-if="task.error_code" class="failure-text">{{ task.error_code }}</span><small v-if="task.error_message">{{ task.error_message }}</small><span v-else>—</span></td></tr></tbody>
      </table>
    </div>
    <PaginationBar :page="page" :pages="pages" :total="total" :busy="loading" @change="changePage" />
  </section>
</template>
