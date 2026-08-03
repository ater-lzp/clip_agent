<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { tasksApi } from '../api'
import { ApiError } from '../api/client'
import BgmDecisionPanel from '../components/BgmDecisionPanel.vue'
import ReviewPanel from '../components/ReviewPanel.vue'
import StatusBadge from '../components/StatusBadge.vue'
import TaskProgress from '../components/TaskProgress.vue'
import type { PendingReview, TaskDetail } from '../types/domain'
import { formatDate, formatDuration } from '../utils/format'

const route = useRoute()
const router = useRouter()
const task = ref<TaskDetail | null>(null)
const loading = ref(true)
const actionBusy = ref(false)
const errorMessage = ref('')
const notice = ref('')
let pollTimer: number | null = null

const taskId = computed(() => (typeof route.params.taskId === 'string' ? route.params.taskId : ''))
const contentReview = computed(() => {
  const review = task.value?.pending_review
  return review?.kind === 'script' || review?.kind === 'storyboard' ? review : null
})
const bgmReview = computed<Extract<PendingReview, { kind: 'bgm' }> | null>(() => {
  const review = task.value?.pending_review
  return review?.kind === 'bgm' ? review : null
})
const videoClass = computed(() => (task.value?.aspect_ratio === '9:16' ? 'video-portrait' : 'video-landscape'))

function shouldPoll(detail: TaskDetail): boolean {
  return !['completed', 'failed', 'awaiting_script_review', 'awaiting_storyboard_review', 'awaiting_bgm_decision'].includes(detail.status)
}

function managePolling(): void {
  if (pollTimer !== null) window.clearInterval(pollTimer)
  pollTimer = task.value && shouldPoll(task.value) ? window.setInterval(() => load(false), 2000) : null
}

async function load(showLoader = true): Promise<void> {
  if (!taskId.value) return
  if (showLoader) loading.value = true
  try {
    const detail = await tasksApi.get(taskId.value)
    task.value = detail
    errorMessage.value = ''
    managePolling()
  } catch (error) {
    errorMessage.value = error instanceof ApiError ? error.message : '任务加载失败'
    managePolling()
  } finally {
    loading.value = false
  }
}

async function review(payload: { action: 'approve' | 'reject'; feedback: string | null }): Promise<void> {
  if (!contentReview.value || actionBusy.value) return
  actionBusy.value = true
  notice.value = ''
  try {
    task.value = await tasksApi.review(taskId.value, contentReview.value.kind, {
      version: contentReview.value.version,
      action: payload.action,
      feedback: payload.feedback,
    })
    notice.value = payload.action === 'approve' ? '已批准，流程正在继续' : '已退回，正在生成新版本'
    managePolling()
  } catch (error) {
    if (error instanceof ApiError && error.status === 409) await load(false)
    errorMessage.value = error instanceof ApiError ? error.message : '审核提交失败'
  } finally {
    actionBusy.value = false
  }
}

async function decideBgm(payload: { action: 'no_add' | 'add'; volume: number | null }): Promise<void> {
  if (!bgmReview.value || actionBusy.value) return
  actionBusy.value = true
  try {
    task.value = await tasksApi.decideBgm(taskId.value, {
      version: bgmReview.value.version,
      action: payload.action,
      volume: payload.volume,
    })
    notice.value = payload.action === 'add' ? '正在裁剪并混合 BGM' : '已选择保留无 BGM 版本'
    managePolling()
  } catch (error) {
    if (error instanceof ApiError && error.status === 409) await load(false)
    errorMessage.value = error instanceof ApiError ? error.message : 'BGM 决策提交失败'
  } finally {
    actionBusy.value = false
  }
}

async function retryTask(): Promise<void> {
  if (actionBusy.value) return
  actionBusy.value = true
  try {
    task.value = await tasksApi.retry(taskId.value)
    managePolling()
  } catch (error) {
    errorMessage.value = error instanceof ApiError ? error.message : '重试失败'
  } finally {
    actionBusy.value = false
  }
}

async function download(): Promise<void> {
  if (!task.value?.export_url || actionBusy.value) return
  actionBusy.value = true
  try {
    await tasksApi.download(task.value.export_url, `clip-${task.value.id}.mp4`)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '下载失败'
  } finally {
    actionBusy.value = false
  }
}

async function deleteTask(): Promise<void> {
  if (!task.value || actionBusy.value) return
  if (!window.confirm(`确认永久删除“${task.value.topic}”及其媒体文件？此操作不可恢复。`)) return
  actionBusy.value = true
  try {
    await tasksApi.delete(task.value.id)
    await router.push('/tasks')
  } catch (error) {
    errorMessage.value = error instanceof ApiError ? error.message : '删除失败'
  } finally {
    actionBusy.value = false
  }
}

onMounted(() => load())
watch(taskId, () => load())
onBeforeUnmount(() => {
  if (pollTimer !== null) window.clearInterval(pollTimer)
})
</script>

<template>
  <div class="page detail-page">
    <div v-if="loading" class="state-card"><span class="spinner"></span><p>正在恢复任务状态…</p></div>
    <div v-else-if="!task" class="state-card error-state" role="alert">
      <h2>无法打开任务</h2><p>{{ errorMessage }}</p><button class="button secondary" @click="load()">重试</button>
    </div>
    <template v-else>
      <div class="detail-heading">
        <div>
          <RouterLink class="back-link" to="/tasks">← 返回历史</RouterLink>
          <div class="title-line"><h1>{{ task.topic }}</h1><StatusBadge :status="task.status" /></div>
          <p>{{ task.aspect_ratio }} · {{ formatDuration(task.target_duration_seconds) }} · 音色 {{ task.voice_id }} · 更新于 {{ formatDate(task.updated_at) }}</p>
        </div>
        <div class="heading-actions">
          <button v-if="task.export_ready" class="button primary" :disabled="actionBusy" @click="download">导出视频</button>
          <button class="button ghost danger-text" :disabled="actionBusy" @click="deleteTask">删除</button>
        </div>
      </div>

      <TaskProgress :progress="task.progress" :failed="task.status === 'failed'" />
      <p v-if="task.provider_mode === 'fake'" class="form-error floating-error" role="alert">此任务使用 fake 测试适配器，没有发起外部 LLM、MiMo 或 Pexels 请求。</p>
      <p v-if="notice" class="notice" role="status">{{ notice }}</p>
      <p v-if="errorMessage" class="form-error floating-error" role="alert">{{ errorMessage }}</p>

      <section v-if="task.status === 'failed' && task.error" class="panel failure-panel">
        <p class="eyebrow">{{ task.error.code }}</p><h2>任务在“{{ task.error.failed_stage }}”阶段停止</h2><p>{{ task.error.message }}</p>
        <button v-if="task.error.retryable" class="button primary" :disabled="actionBusy" @click="retryTask">从安全检查点重试</button>
      </section>

      <ReviewPanel v-if="contentReview" :review="contentReview" :busy="actionBusy" @submit="review" />

      <section v-if="task.preview_url" class="panel preview-panel">
        <div class="section-heading"><div><p class="eyebrow">Preview</p><h2>{{ task.status === 'completed' ? '视频成片' : '无 BGM 预览' }}</h2></div><span v-if="task.final_duration_seconds">{{ formatDuration(task.final_duration_seconds) }}</span></div>
        <div class="video-stage" :class="videoClass">
          <video controls preload="metadata" :src="tasksApi.previewUrl(task.preview_url)">你的浏览器不支持视频播放。</video>
        </div>
        <p v-if="task.status !== 'completed'" class="preview-note">这是不含背景音乐的预览。口播、画面和字幕已按真实音频时长对齐。</p>
      </section>

      <BgmDecisionPanel v-if="bgmReview" :review="bgmReview" :busy="actionBusy" @decide="decideBgm" />

      <section v-if="!task.pending_review && !task.preview_url && task.status !== 'failed'" class="panel working-panel" aria-live="polite">
        <span class="spinner"></span><div><h2>{{ task.progress.current_step }}</h2><p>任务在服务端运行。你可以安全离开或刷新页面，检查点会保留当前进度。</p></div>
      </section>

      <section v-if="task.status === 'completed'" class="panel completion-panel">
        <span aria-hidden="true">✓</span><div><p class="eyebrow">Production complete</p><h2>视频已完成</h2><p>{{ task.bgm_added ? '已添加并完成 BGM 混音。' : '已按你的决定保留无 BGM 版本。' }}</p></div><button class="button primary" :disabled="actionBusy" @click="download">导出 MP4</button>
      </section>
    </template>
  </div>
</template>
