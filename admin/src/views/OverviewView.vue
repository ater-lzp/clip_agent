<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { request, type AdminTask, type AuditLog, type Dashboard, type Page } from '../api'
import { formatDate, money, statusLabel } from '../utils'

const dashboard = ref<Dashboard | null>(null)
const recentTasks = ref<AdminTask[]>([])
const recentAudits = ref<AuditLog[]>([])
const error = ref('')

interface ChartItem {
  label: string
  value: number
  color: string
}

function percentage(value: number, total: number): number {
  if (total <= 0) return 0
  return Math.round((value / total) * 1000) / 10
}

function donutBackground(items: ChartItem[]): string {
  const total = items.reduce((sum, item) => sum + item.value, 0)
  if (total <= 0) return '#e2e8f0'
  let cursor = 0
  const stops = items
    .filter((item) => item.value > 0)
    .map((item) => {
      const start = cursor
      cursor += (item.value / total) * 100
      return `${item.color} ${start.toFixed(2)}% ${cursor.toFixed(2)}%`
    })
  return `conic-gradient(${stops.join(', ')})`
}

const taskBreakdown = computed<ChartItem[]>(() => {
  if (!dashboard.value) return []
  const known = dashboard.value.completed_tasks
    + dashboard.value.awaiting_tasks
    + dashboard.value.in_progress_tasks
    + dashboard.value.failed_tasks
  return [
    { label: '已完成', value: dashboard.value.completed_tasks, color: '#16a34a' },
    { label: '待人工处理', value: dashboard.value.awaiting_tasks, color: '#f59e0b' },
    { label: '生成中', value: dashboard.value.in_progress_tasks, color: '#0284c7' },
    { label: '失败', value: dashboard.value.failed_tasks, color: '#dc2626' },
    { label: '其他', value: Math.max(0, dashboard.value.task_total - known), color: '#94a3b8' },
  ]
})

const taskDonut = computed(() => donutBackground(taskBreakdown.value))

const membershipBreakdown = computed<ChartItem[]>(() => {
  if (!dashboard.value) return []
  return [
    {
      label: '免费用户',
      value: Math.max(0, dashboard.value.user_total - dashboard.value.vip_users - dashboard.value.svip_users),
      color: '#64748b',
    },
    { label: 'VIP', value: dashboard.value.vip_users, color: '#0ea5e9' },
    { label: 'SVIP', value: dashboard.value.svip_users, color: '#8b5cf6' },
  ]
})

const activeRate = computed(() => dashboard.value
  ? percentage(dashboard.value.active_users, dashboard.value.user_total)
  : 0)
const cdkRate = computed(() => dashboard.value
  ? percentage(dashboard.value.cdk_used, dashboard.value.cdk_total)
  : 0)

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
      <div class="overview-kpis" aria-label="核心运营指标">
        <article>
          <span class="kpi-icon" aria-hidden="true">人</span>
          <div><small>用户总数</small><strong>{{ dashboard.user_total }}</strong><span>今日新增 {{ dashboard.today_users }}</span></div>
        </article>
        <article>
          <span class="kpi-icon task" aria-hidden="true">片</span>
          <div><small>视频任务</small><strong>{{ dashboard.task_total }}</strong><span>完成率 {{ percentage(dashboard.completed_tasks, dashboard.task_total) }}%</span></div>
        </article>
        <article>
          <span class="kpi-icon revenue" aria-hidden="true">¥</span>
          <div><small>会员收入</small><strong>{{ money(dashboard.membership_revenue_cents) }}</strong><span>模拟余额支付累计</span></div>
        </article>
      </div>

      <div class="analytics-grid">
        <article class="chart-card task-chart-card">
          <div class="card-heading"><div><p class="chart-kicker">任务状态</p><h2>生产健康度</h2></div><RouterLink to="/tasks">查看任务</RouterLink></div>
          <div class="donut-layout">
            <div class="donut-chart" :style="{ background: taskDonut }" role="img" :aria-label="`任务总数 ${dashboard.task_total}`">
              <div><strong>{{ dashboard.task_total }}</strong><span>全部任务</span></div>
            </div>
            <ul class="chart-legend">
              <li v-for="item in taskBreakdown" :key="item.label">
                <i :style="{ backgroundColor: item.color }"></i>
                <span>{{ item.label }}</span>
                <strong>{{ item.value }}</strong>
                <small>{{ percentage(item.value, dashboard.task_total) }}%</small>
              </li>
            </ul>
          </div>
        </article>

        <article class="chart-card membership-chart-card">
          <div class="card-heading"><div><p class="chart-kicker">用户结构</p><h2>会员分布</h2></div><RouterLink to="/users">管理用户</RouterLink></div>
          <div class="bar-chart" role="img" :aria-label="`用户总数 ${dashboard.user_total}`">
            <div v-for="item in membershipBreakdown" :key="item.label" class="bar-row">
              <div><span>{{ item.label }}</span><strong>{{ item.value }}</strong></div>
              <div class="bar-track"><span :style="{ width: `${percentage(item.value, dashboard.user_total)}%`, backgroundColor: item.color }"></span></div>
              <small>{{ percentage(item.value, dashboard.user_total) }}%</small>
            </div>
          </div>
        </article>

        <article class="chart-card efficiency-card">
          <div class="card-heading"><div><p class="chart-kicker">转化效率</p><h2>账户与 CDK</h2></div><RouterLink to="/cdks">CDK 管理</RouterLink></div>
          <div class="ring-grid">
            <div class="ring-metric">
              <div class="mini-ring" :style="{ background: `conic-gradient(#0284c7 0 ${activeRate}%, #e2e8f0 ${activeRate}% 100%)` }"><span>{{ activeRate }}%</span></div>
              <strong>用户启用率</strong>
              <small>{{ dashboard.active_users }} / {{ dashboard.user_total }}</small>
            </div>
            <div class="ring-metric">
              <div class="mini-ring" :style="{ background: `conic-gradient(#8b5cf6 0 ${cdkRate}%, #e2e8f0 ${cdkRate}% 100%)` }"><span>{{ cdkRate }}%</span></div>
              <strong>CDK 兑换率</strong>
              <small>{{ dashboard.cdk_used }} / {{ dashboard.cdk_total }}</small>
            </div>
          </div>
        </article>
      </div>

      <div class="activity-grid">
        <article class="surface-card">
          <div class="card-heading"><div><p class="chart-kicker">实时动态</p><h2>最近任务</h2></div><RouterLink to="/tasks">查看全部</RouterLink></div>
          <div v-if="!recentTasks.length" class="empty">暂无任务</div>
          <div v-for="task in recentTasks" :key="task.id" class="compact-row">
            <div><strong>{{ task.topic }}</strong><small>{{ task.user_nickname || task.user_email }}</small></div>
            <span class="status-pill" :data-status="task.status">{{ statusLabel(task.status) }}</span>
          </div>
        </article>
        <article class="surface-card">
          <div class="card-heading"><div><p class="chart-kicker">安全动态</p><h2>最近事件</h2></div><RouterLink to="/audit-logs">查看全部</RouterLink></div>
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
