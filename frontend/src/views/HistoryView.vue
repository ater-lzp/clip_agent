<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { tasksApi } from '../api'
import { ApiError } from '../api/client'
import GenerationArchive from '../components/GenerationArchive.vue'
import StatusBadge from '../components/StatusBadge.vue'
import type { TaskDetail, TaskPage } from '../types/domain'
import { formatDate, formatDuration } from '../utils/format'

const tasks = ref<TaskPage | null>(null)
const loading = ref(true)
const errorMessage = ref('')
const expandedTaskId = ref<string | null>(null)
const taskDetails = ref<Record<string, TaskDetail>>({})
const archiveLoadingIds = ref<string[]>([])
const archiveErrors = ref<Record<string, string>>({})

async function load(page = 1): Promise<void> {
  loading.value = true
  errorMessage.value = ''
  try {
    tasks.value = await tasksApi.list(page)
  } catch (error) {
    errorMessage.value = error instanceof ApiError ? error.message : '历史记录加载失败'
  } finally {
    loading.value = false
  }
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

onMounted(() => load())
</script>

<template>
  <div class="page">
    <div class="page-heading">
      <div><p class="eyebrow">Your productions</p><h1>视频任务</h1><p>所有流程都可以离开后恢复。</p></div>
      <RouterLink class="button primary" to="/tasks/new">＋ 新建视频</RouterLink>
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
      <h2>第一条视频，从一个主题开始</h2>
      <p>系统会在剧本、分镜和 BGM 三个决定点等待你。</p>
      <RouterLink class="button primary" to="/tasks/new">创建视频</RouterLink>
    </div>
    <section v-else class="task-grid" aria-label="视频任务列表">
      <article v-for="task in tasks?.items" :key="task.id" class="task-card">
        <RouterLink class="task-card-main" :to="`/tasks/${task.id}`">
          <div class="task-card-top">
            <StatusBadge :status="task.status" />
            <span>{{ formatDate(task.updated_at) }}</span>
          </div>
          <div class="task-thumbnail" :class="task.aspect_ratio === '9:16' ? 'portrait-thumb' : 'landscape-thumb'">
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
    <nav v-if="tasks && tasks.pages > 1" class="pagination" aria-label="分页">
      <button class="button secondary" :disabled="tasks.page <= 1" @click="load(tasks.page - 1)">上一页</button>
      <span>第 {{ tasks.page }} / {{ tasks.pages }} 页</span>
      <button class="button secondary" :disabled="tasks.page >= tasks.pages" @click="load(tasks.page + 1)">下一页</button>
    </nav>
  </div>
</template>
