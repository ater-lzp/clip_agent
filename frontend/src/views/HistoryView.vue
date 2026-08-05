<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { tasksApi } from '../api'
import { ApiError } from '../api/client'
import GenerationArchive from '../components/GenerationArchive.vue'
import AdSlot from '../components/AdSlot.vue'
import StatusBadge from '../components/StatusBadge.vue'
import type { TaskDetail, TaskListStatus, TaskPage, TaskStats, TaskSummary } from '../types/domain'
import { formatDate, formatDuration } from '../utils/format'

type StatusFilter = 'all' | TaskListStatus

const router = useRouter()
const tasks = ref<TaskPage | null>(null)
const stats = ref<TaskStats | null>(null)
const loading = ref(true)
const errorMessage = ref('')
const expandedTaskId = ref<string | null>(null)
const taskDetails = ref<Record<string, TaskDetail>>({})
const archiveLoadingIds = ref<string[]>([])
const archiveErrors = ref<Record<string, string>>({})
const coverErrors = ref<string[]>([])
const loadMoreTarget = ref<HTMLElement | null>(null)
const loadingMore = ref(false)
const duplicatingTaskIds = ref<string[]>([])
const selectedTaskIds = ref<string[]>([])
const selectAllRecords = ref(false)
const deletingSelection = ref(false)
const searchQuery = ref('')
const statusFilter = ref<StatusFilter>('all')
let observer: IntersectionObserver | null = null

const statusTabs: Array<{ value: StatusFilter; label: string }> = [
  { value: 'all', label: '全部' },
  { value: 'awaiting_script_review', label: '待审剧本' },
  { value: 'awaiting_storyboard_review', label: '待审分镜' },
  { value: 'awaiting_bgm_decision', label: '待选 BGM' },
  { value: 'in_progress', label: '生成中' },
  { value: 'completed', label: '已完成' },
  { value: 'failed', label: '失败' },
]

const activeStatus = (value: StatusFilter): TaskListStatus | undefined =>
  value === 'all' ? undefined : value
const selectedCount = computed(() =>
  selectAllRecords.value ? (stats.value?.total ?? tasks.value?.total ?? 0) : selectedTaskIds.value.length,
)

let debounceTimer: ReturnType<typeof setTimeout> | null = null

async function loadStats(): Promise<void> {
  try {
    stats.value = await tasksApi.stats()
  } catch {
    stats.value = null
  }
}

async function load(page = 1, append = false): Promise<void> {
  if (append) loadingMore.value = true
  else loading.value = true
  errorMessage.value = ''
  try {
    const loaded = await tasksApi.list(page, activeStatus(statusFilter.value), 40, searchQuery.value.trim())
    tasks.value = append && tasks.value
      ? { ...loaded, items: [...tasks.value.items, ...loaded.items] }
      : loaded
  } catch (error) {
    errorMessage.value = error instanceof ApiError ? error.message : '历史记录加载失败'
  } finally {
    loading.value = false
    loadingMore.value = false
  }
}

async function loadMore(): Promise<void> {
  if (!tasks.value || loadingMore.value || tasks.value.page >= tasks.value.pages) return
  await load(tasks.value.page + 1, true)
}

function onSearchInput(): void {
  if (debounceTimer) clearTimeout(debounceTimer)
  debounceTimer = setTimeout(() => {
    expandedTaskId.value = null
    void load()
  }, 400)
}

function changeStatus(value: StatusFilter): void {
  statusFilter.value = value
  expandedTaskId.value = null
  void load()
}

function toggleAllRecords(): void {
  selectAllRecords.value = !selectAllRecords.value
  selectedTaskIds.value = selectAllRecords.value ? (tasks.value?.items.map((task) => task.id) ?? []) : []
}

function toggleTaskSelection(taskId: string): void {
  if (selectAllRecords.value) {
    selectAllRecords.value = false
    selectedTaskIds.value = (tasks.value?.items.map((task) => task.id) ?? []).filter((id) => id !== taskId)
    return
  }
  selectedTaskIds.value = selectedTaskIds.value.includes(taskId)
    ? selectedTaskIds.value.filter((id) => id !== taskId)
    : [...selectedTaskIds.value, taskId]
}

async function deleteSelection(): Promise<void> {
  if (!selectedCount.value || deletingSelection.value) return
  const label = selectAllRecords.value ? `全部 ${selectedCount.value} 条生成记录` : `${selectedCount.value} 条选中记录`
  if (!window.confirm(`确认永久删除${label}及其媒体文件？此操作不可恢复。`)) return
  deletingSelection.value = true
  errorMessage.value = ''
  try {
    await tasksApi.bulkDelete({
      mode: selectAllRecords.value ? 'all' : 'selected',
      task_ids: selectAllRecords.value ? [] : selectedTaskIds.value,
    })
    selectAllRecords.value = false
    selectedTaskIds.value = []
    taskDetails.value = {}
    expandedTaskId.value = null
    await Promise.all([load(), loadStats()])
  } catch (error) {
    errorMessage.value = error instanceof ApiError ? error.message : '批量删除失败'
  } finally {
    deletingSelection.value = false
  }
}

function markCoverFailed(taskId: string): void {
  if (!coverErrors.value.includes(taskId)) coverErrors.value = [...coverErrors.value, taskId]
}

async function loadArchive(taskId: string): Promise<void> {
  if (taskDetails.value[taskId] || archiveLoadingIds.value.includes(taskId)) return

  archiveLoadingIds.value = [...archiveLoadingIds.value, taskId]
  const nextErrors = { ...archiveErrors.value }
  delete nextErrors[taskId]
  archiveErrors.value = nextErrors
  try {
    const detail = await tasksApi.get(taskId)
    taskDetails.value = { ...taskDetails.value, [taskId]: detail }
  } catch (error) {
    archiveErrors.value = {
      ...archiveErrors.value,
      [taskId]: error instanceof ApiError ? error.message : '生成档案加载失败',
    }
  } finally {
    archiveLoadingIds.value = archiveLoadingIds.value.filter((id) => id !== taskId)
  }
}

async function toggleArchive(taskId: string): Promise<void> {
  if (expandedTaskId.value === taskId) {
    expandedTaskId.value = null
    return
  }
  expandedTaskId.value = taskId
  await loadArchive(taskId)
}

async function retryArchive(taskId: string): Promise<void> {
  await loadArchive(taskId)
}

async function duplicateTask(task: TaskSummary): Promise<void> {
  if (duplicatingTaskIds.value.includes(task.id)) return
  if (!window.confirm(`基于“${task.topic}”再次创作？将沿用时长、比例与音色创建一个新任务。`)) return
  duplicatingTaskIds.value = [...duplicatingTaskIds.value, task.id]
  errorMessage.value = ''
  try {
    const created = await tasksApi.duplicate(task.id, crypto.randomUUID())
    await router.push(`/tasks/${created.id}`)
  } catch (error) {
    errorMessage.value = error instanceof ApiError ? error.message : '再次创作失败'
  } finally {
    duplicatingTaskIds.value = duplicatingTaskIds.value.filter((id) => id !== task.id)
  }
}

onMounted(async () => {
  await Promise.all([load(), loadStats()])
  await nextTick()
  if (!('IntersectionObserver' in window)) return
  observer = new IntersectionObserver((entries) => {
    if (entries.some((entry) => entry.isIntersecting)) void loadMore()
  }, { rootMargin: '240px' })
  if (loadMoreTarget.value) observer.observe(loadMoreTarget.value)
})

watch([statusFilter, searchQuery], () => {
  if (observer && loadMoreTarget.value) {
    observer.disconnect()
    observer.observe(loadMoreTarget.value)
  }
})

onBeforeUnmount(() => {
  observer?.disconnect()
  if (debounceTimer) clearTimeout(debounceTimer)
})
</script>

<template>
  <div class="page">
    <div class="page-heading">
      <div><p class="eyebrow">Your productions</p><h1>视频任务</h1><p>所有流程都可以离开后恢复。</p></div>
      <RouterLink class="button primary" to="/tasks/new">＋ 新建视频</RouterLink>
    </div>

    <section v-if="stats" class="stats-grid" aria-label="创作统计">
      <div class="stat-card"><span>总任务</span><strong>{{ stats.total }}</strong></div>
      <div class="stat-card"><span>已完成</span><strong>{{ stats.completed }}</strong></div>
      <div class="stat-card"><span>待你处理</span><strong>{{ stats.awaiting_review }}</strong></div>
      <div class="stat-card"><span>进行中</span><strong>{{ stats.in_progress }}</strong></div>
      <div class="stat-card"><span>累计成片</span><strong>{{ formatDuration(stats.total_duration_seconds) }}</strong></div>
    </section>
    <AdSlot slot="history" />

    <div class="history-toolbar">
      <input
        v-model="searchQuery"
        class="history-search"
        type="search"
        placeholder="搜索任务主题…"
        aria-label="搜索任务主题"
        @input="onSearchInput"
      />
      <div class="history-tabs" role="tablist" aria-label="任务状态筛选">
        <button
          v-for="tab in statusTabs"
          :key="tab.value"
          type="button"
          :class="{ active: statusFilter === tab.value }"
          @click="changeStatus(tab.value)"
        >{{ tab.label }}</button>
      </div>
    </div>

    <div v-if="stats?.total" class="bulk-actions" aria-label="批量管理生成记录">
      <label class="select-all-records">
        <input type="checkbox" :checked="selectAllRecords" :disabled="deletingSelection" @change="toggleAllRecords" />
        <span>全选全部 {{ stats.total }} 条生成记录</span>
      </label>
      <span v-if="selectedCount" class="muted">已选 {{ selectedCount }} 条</span>
      <button class="button danger" type="button" :disabled="!selectedCount || deletingSelection" @click="deleteSelection">
        {{ deletingSelection ? '正在删除…' : '删除选中记录' }}
      </button>
    </div>

    <div v-if="loading" class="state-card" aria-live="polite">
      <span class="spinner"></span><p>正在加载你的任务…</p>
    </div>
    <div v-else-if="errorMessage" class="state-card error-state" role="alert">
      <h2>暂时无法加载</h2><p>{{ errorMessage }}</p>
      <button class="button secondary" type="button" @click="load()">重试</button>
    </div>
    <div v-else-if="tasks?.items.length === 0" class="state-card empty-state">
      <span class="empty-glyph" aria-hidden="true">✦</span>
      <h2>{{ searchQuery || statusFilter !== 'all' ? '没有符合条件的任务' : '第一条视频，从一个主题开始' }}</h2>
      <p v-if="!searchQuery && statusFilter === 'all'">系统会在剧本、分镜和 BGM 三个决定点等待你。</p>
      <p v-else>试试调整搜索词或筛选条件。</p>
      <RouterLink v-if="!searchQuery && statusFilter === 'all'" class="button primary" to="/tasks/new">创建视频</RouterLink>
    </div>
    <section v-else class="task-grid" aria-label="视频任务列表">
      <article v-for="task in tasks?.items" :key="task.id" class="task-card" :class="{ selected: selectAllRecords || selectedTaskIds.includes(task.id) }">
        <label class="task-select" :aria-label="`选择任务：${task.topic}`">
          <input
            type="checkbox"
            :checked="selectAllRecords || selectedTaskIds.includes(task.id)"
            :disabled="deletingSelection"
            @change="toggleTaskSelection(task.id)"
          />
        </label>
        <RouterLink class="task-card-main" :to="`/tasks/${task.id}`">
          <div class="task-card-top">
            <StatusBadge :status="task.status" />
            <time class="task-updated-at" :datetime="task.updated_at">{{ formatDate(task.updated_at) }}</time>
          </div>
          <div
            class="task-thumbnail"
            :class="[
              task.aspect_ratio === '9:16' ? 'portrait-thumb' : 'landscape-thumb',
              { 'has-cover': task.cover_url && !coverErrors.includes(task.id) },
            ]"
          >
            <img
              v-if="task.cover_url && !coverErrors.includes(task.id)"
              :src="tasksApi.coverUrl(task.cover_url)"
              alt="视频第一帧封面"
              loading="lazy"
              @error="markCoverFailed(task.id)"
            />
            <span>{{ task.aspect_ratio }}</span>
            <i :style="{ width: `${(task.progress.completed_steps / task.progress.total_steps) * 100}%` }"></i>
          </div>
          <h2>{{ task.topic }}</h2>
          <div class="task-meta">
            <span>{{ formatDuration(task.target_duration_seconds) }}</span>
            <span>{{ task.progress.current_step }}</span>
          </div>
          <p v-if="task.error" class="card-error">{{ task.error.message }}</p>
        </RouterLink>
        <button
          class="archive-toggle"
          type="button"
          :aria-expanded="expandedTaskId === task.id"
          :aria-controls="`archive-${task.id}`"
          @click="toggleArchive(task.id)"
        >
          {{ expandedTaskId === task.id ? '收起生成档案' : '查看剧本与分镜规划' }}
          <span aria-hidden="true">{{ expandedTaskId === task.id ? '−' : '+' }}</span>
        </button>
        <div v-if="task.status === 'completed'" class="card-shortcuts">
          <RouterLink class="publish-shortcut" :to="{ path: '/community', query: { taskId: task.id } }">发布到社区</RouterLink>
          <button
            class="publish-shortcut"
            type="button"
            :disabled="duplicatingTaskIds.includes(task.id)"
            @click="duplicateTask(task)"
          >{{ duplicatingTaskIds.includes(task.id) ? '创建中…' : '↻ 再次创作' }}</button>
        </div>
        <div v-if="expandedTaskId === task.id" :id="`archive-${task.id}`" class="task-archive">
          <div v-if="archiveLoadingIds.includes(task.id)" class="archive-state" aria-live="polite">
            <span class="spinner"></span><span>正在加载生成档案…</span>
          </div>
          <div v-else-if="archiveErrors[task.id]" class="archive-state archive-error" role="alert">
            <span>{{ archiveErrors[task.id] }}</span>
            <button class="text-button" type="button" @click="retryArchive(task.id)">重试</button>
          </div>
          <GenerationArchive v-else-if="taskDetails[task.id]" :task="taskDetails[task.id]" />
        </div>
      </article>
    </section>
    <div v-if="tasks?.items.length" ref="loadMoreTarget" class="infinite-scroll-status" aria-live="polite">
      <template v-if="loadingMore"><span class="spinner"></span><span>正在加载更多记录…</span></template>
      <span v-else-if="tasks.page >= tasks.pages">已加载全部 {{ tasks.total }} 条记录</span>
      <button v-else class="text-button" type="button" @click="loadMore">加载更多</button>
    </div>
  </div>
</template>
