<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { request, type AdminTask, type AuditLog, type Dashboard, type Page } from '../api'
import { formatDate, money, statusLabel } from '../utils'

const dashboard = ref<Dashboard | null>(null)
const recentTasks = ref<AdminTask[]>([])
const recentAudits = ref<AuditLog[]>([])
const error = ref('')

async function load(): Promise<void> {
  error.value = ''
  try {
    const [summary, tasks, audits] = await Promise.all([
      request<Dashboard>('/api/v1/admin/dashboard'),
      request<Page<AdminTask>>('/api/v1/admin/tasks?page_size=5'),
      request<Page<AuditLog>>('/api/v1/admin/audit-logs?page_size=5'),
    ])
    dashboard.value = summary
    recentTasks.value = tasks.items
    recentAudits.value = audits.items
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '概览加载失败'
  }
}

onMounted(load)
</script>

<template>
  <section class="content">
    <div class="heading">
      <div><p class="eyebrow">Dashboard</p><h1>运营概览</h1></div>
      <button class="secondary" type="button" @click="load">刷新数据</button>
    </div>
    <p v-if="error" class="error" role="alert">{{ error }}</p>
    <p v-else-if="!dashboard">数据加载中…</p>
    <template v-else>
      <div class="stats">
        <article><span>用户总数</span><strong>{{ dashboard.user_total }}</strong><small>今日 +{{ dashboard.today_users }}</small></article>
        <article><span>启用用户</span><strong>{{ dashboard.active_users }}</strong><small>{{ dashboard.vip_users }} VIP / {{ dashboard.svip_users }} SVIP</small></article>
        <article><span>任务总数</span><strong>{{ dashboard.task_total }}</strong><small>{{ dashboard.completed_tasks }} 个已完成</small></article>
        <article><span>待人工处理</span><strong>{{ dashboard.awaiting_tasks }}</strong><small>{{ dashboard.in_progress_tasks }} 个生成中</small></article>
        <article><span>失败任务</span><strong>{{ dashboard.failed_tasks }}</strong><small>可在任务监控中排查</small></article>
        <article><span>会员收入</span><strong>{{ money(dashboard.membership_revenue_cents) }}</strong><small>模拟余额支付累计</small></article>
        <article><span>CDK 使用率</span><strong>{{ dashboard.cdk_used }} / {{ dashboard.cdk_total }}</strong><small>已兑换 / 已生成</small></article>
      </div>
      <div class="dashboard-grid">
        <article class="surface-card">
          <div class="card-heading"><h2>最近任务</h2><RouterLink to="/tasks">查看全部</RouterLink></div>
          <div v-if="!recentTasks.length" class="empty">暂无任务</div>
          <div v-for="task in recentTasks" :key="task.id" class="compact-row">
            <div><strong>{{ task.topic }}</strong><small>{{ task.user_nickname || task.user_email }}</small></div>
            <span class="status-pill" :data-status="task.status">{{ statusLabel(task.status) }}</span>
          </div>
        </article>
        <article class="surface-card">
          <div class="card-heading"><h2>最近安全事件</h2><RouterLink to="/audit-logs">查看全部</RouterLink></div>
          <div v-if="!recentAudits.length" class="empty">暂无审计记录</div>
          <div v-for="item in recentAudits" :key="item.id" class="compact-row">
            <div><strong>{{ item.action }}</strong><small>{{ item.actor_nickname || item.actor_email || '系统' }}</small></div>
            <time>{{ formatDate(item.created_at) }}</time>
          </div>
        </article>
      </div>
    </template>
  </section>
</template>
