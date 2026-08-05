<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { tasksApi } from '../api'
import { ApiError } from '../api/client'
import type { BgmTrack, PendingReview } from '../types/domain'
import { formatDuration } from '../utils/format'

type BgmReview = Extract<PendingReview, { kind: 'bgm' }>
const props = defineProps<{ taskId: string; review: BgmReview; busy: boolean }>()
const emit = defineEmits<{
  decide: [payload: { action: 'no_add' | 'add'; volume: number | null; track_id: string | null }]
}>()
const volume = ref(props.review.default_volume)
const tracks = ref<BgmTrack[]>([])
const uploadedTrack = ref<BgmTrack | null>(props.review.uploaded_track)
const selectedId = ref(props.review.uploaded_track?.id ?? '')
const loadingTracks = ref(false)
const tracksLoaded = ref(false)
const uploading = ref(false)
const errorMessage = ref('')
const libraryOpen = ref(false)
const dialog = ref<HTMLElement | null>(null)
const selectedTrack = computed(() =>
  [uploadedTrack.value, ...tracks.value].find((track) => track?.id === selectedId.value) ?? null,
)

watch(
  () => props.review.version,
  () => {
    volume.value = props.review.default_volume
    uploadedTrack.value = props.review.uploaded_track
    selectedId.value = uploadedTrack.value?.id ?? tracks.value[0]?.id ?? ''
    libraryOpen.value = false
  },
)

async function loadTracks(): Promise<void> {
  loadingTracks.value = true
  errorMessage.value = ''
  try {
    tracks.value = (await tasksApi.listBgms()).items
    tracksLoaded.value = true
    if (!selectedId.value) selectedId.value = tracks.value[0]?.id ?? ''
  } catch (error) {
    errorMessage.value = error instanceof ApiError ? error.message : '背景音乐列表加载失败'
  } finally {
    loadingTracks.value = false
  }
}

async function openLibrary(): Promise<void> {
  libraryOpen.value = true
  await nextTick()
  dialog.value?.focus()
  if (!tracksLoaded.value) await loadTracks()
}

function closeLibrary(): void {
  if (!props.busy && !uploading.value) libraryOpen.value = false
}

function handleDialogKeydown(event: KeyboardEvent): void {
  if (event.key === 'Escape') closeLibrary()
}

async function upload(event: Event): Promise<void> {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file) return
  if (file.size > 25 * 1024 * 1024) {
    errorMessage.value = '背景音乐不能超过 25MB'
    return
  }
  if (!/\.(mp3|wav|m4a)$/i.test(file.name)) {
    errorMessage.value = '只支持 MP3、WAV 或 M4A'
    return
  }
  uploading.value = true
  errorMessage.value = ''
  try {
    const uploaded = await tasksApi.uploadBgm(props.taskId, file)
    uploadedTrack.value = uploaded
    selectedId.value = uploaded.id
  } catch (error) {
    errorMessage.value = error instanceof ApiError ? error.message : '背景音乐上传失败'
  } finally {
    uploading.value = false
  }
}

function addBgm(): void {
  if (!selectedId.value) {
    errorMessage.value = '请先选择一首背景音乐'
    return
  }
  emit('decide', { action: 'add', volume: volume.value, track_id: selectedId.value })
  libraryOpen.value = false
}
</script>

<template>
  <section class="panel bgm-panel" aria-labelledby="bgm-heading">
    <div class="section-heading"><div><p class="eyebrow">最后一步 · 流程已暂停</p><h2 id="bgm-heading">是否添加背景音乐？</h2></div></div>
    <p>剧本建议：<span class="query-chip">{{ review.suggested_query }}</span></p>
    <p class="field-hint">选择添加后，将在弹窗中试听项目曲库、上传本地音乐并调整混音音量。</p>
    <div class="review-actions">
      <button class="button secondary" data-testid="skip-bgm" type="button" :disabled="busy" @click="emit('decide', { action: 'no_add', volume: null, track_id: null })">不添加，直接完成</button>
      <button class="button primary" data-testid="open-bgm-library" type="button" :disabled="busy" @click="openLibrary">添加背景音乐</button>
    </div>
  </section>

  <div v-if="libraryOpen" class="modal-backdrop" @mousedown.self="closeLibrary">
    <section ref="dialog" class="modal-card bgm-library-dialog" role="dialog" aria-modal="true" aria-labelledby="bgm-library-title" tabindex="-1" @keydown="handleDialogKeydown">
      <div class="section-heading"><div><p class="eyebrow">BGM library</p><h2 id="bgm-library-title">选择背景音乐</h2></div><button class="modal-close" type="button" :disabled="busy || uploading" aria-label="关闭曲库" @click="closeLibrary">×</button></div>
      <div class="bgm-source-heading"><h3>项目曲库</h3><label class="button secondary upload-button">{{ uploading ? '正在验证…' : '从本地上传' }}<input type="file" accept=".mp3,.wav,.m4a,audio/mpeg,audio/wav,audio/mp4" :disabled="busy || uploading" @change="upload" /></label></div>
      <p v-if="loadingTracks" class="muted" aria-live="polite">正在读取背景音乐曲库…</p>
      <div v-else-if="!tracks.length && !uploadedTrack" class="bgm-empty">项目曲库暂时为空，你可以从本地上传一首音乐。</div>
      <div v-else class="bgm-track-grid modal-track-grid" role="radiogroup" aria-label="背景音乐">
        <label v-if="uploadedTrack" class="bgm-track" :class="{ selected: selectedId === uploadedTrack.id }"><input v-model="selectedId" type="radio" :value="uploadedTrack.id" :disabled="busy" /><span><strong>{{ uploadedTrack.name }}</strong><small>本地上传 · {{ formatDuration(uploadedTrack.duration_seconds) }}</small></span><audio controls preload="metadata" :src="tasksApi.previewUrl(uploadedTrack.preview_url)"></audio></label>
        <label v-for="track in tracks" :key="track.id" class="bgm-track" :class="{ selected: selectedId === track.id }"><input v-model="selectedId" type="radio" :value="track.id" :disabled="busy" /><span><strong>{{ track.name }}</strong><small>项目曲库 · {{ formatDuration(track.duration_seconds) }}</small></span><audio controls preload="metadata" :src="tasksApi.previewUrl(track.preview_url)"></audio></label>
      </div>
      <p v-if="errorMessage" class="field-error" role="alert">{{ errorMessage }}</p><p v-if="selectedTrack" class="field-hint">已选择：{{ selectedTrack.name }}</p>
      <label for="bgm-volume">BGM 音量 <strong>{{ Math.round(volume * 100) }}%</strong></label><input id="bgm-volume" v-model.number="volume" type="range" min="0" max="1" step="0.01" :disabled="busy" />
      <p class="field-hint">确认后会按成片时长循环裁剪并混入预览；处理完成后播放器将自动切换到含 BGM 的视频。</p>
      <div class="modal-actions"><button class="button secondary" type="button" :disabled="busy || uploading" @click="closeLibrary">取消</button><button class="button primary" data-testid="confirm-bgm" type="button" :disabled="busy || uploading || loadingTracks || !selectedId" @click="addBgm">{{ busy ? '正在混音…' : '确认添加并混音' }}</button></div>
    </section>
  </div>
</template>
