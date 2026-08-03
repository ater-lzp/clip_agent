<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { PendingReview } from '../types/domain'
import { formatDuration } from '../utils/format'

type ContentReview = Extract<PendingReview, { kind: 'script' | 'storyboard' }>

const props = defineProps<{ review: ContentReview; busy: boolean }>()
const emit = defineEmits<{
  submit: [payload: { action: 'approve' | 'reject'; feedback: string | null }]
}>()

const feedback = ref('')
const feedbackError = ref('')
const heading = computed(() => (props.review.kind === 'script' ? '审核剧本' : '审核分镜'))

watch(
  () => `${props.review.kind}:${props.review.version}`,
  () => {
    feedback.value = ''
    feedbackError.value = ''
  },
)

function reject(): void {
  const normalized = feedback.value.trim()
  if (!normalized) {
    feedbackError.value = '退回时请说明需要修改的内容'
    return
  }
  feedbackError.value = ''
  emit('submit', { action: 'reject', feedback: normalized })
}
</script>

<template>
  <section class="panel review-panel" aria-labelledby="review-heading">
    <div class="section-heading">
      <div>
        <p class="eyebrow">需要你的决定 · 版本 {{ review.version }}</p>
        <h2 id="review-heading">{{ heading }}</h2>
      </div>
      <span class="review-flag">流程已暂停</span>
    </div>

    <template v-if="review.kind === 'script'">
      <div class="artifact-intro">
        <h3>{{ review.script.title }}</h3>
        <p>{{ review.script.hook }}</p>
      </div>
      <ol class="artifact-list">
        <li v-for="segment in review.script.segments" :key="segment.id">
          <div class="item-index">{{ String(segment.order).padStart(2, '0') }}</div>
          <div>
            <p class="artifact-label">口播稿</p>
            <p class="narration">{{ segment.narration }}</p>
            <p class="muted">场景：{{ segment.location }}</p>
            <p class="muted">画面：{{ segment.visual_intent }}</p>
            <p class="artifact-label emotion-label">情绪指令</p>
            <p class="emotion-instruction">{{ segment.emotion }}</p>
            <p class="muted">
              {{ segment.narration_char_count }} 字 ·
              {{ segment.speed_tier ?? '自动语速' }}
              <template v-if="segment.speed_value"> · {{ segment.speed_value }} 字/秒</template>
            </p>
          </div>
          <time>{{ formatDuration(segment.estimated_duration_seconds) }}</time>
        </li>
      </ol>
      <p class="closing-copy">{{ review.script.closing }}</p>
    </template>

    <ol v-else class="artifact-list shot-list">
      <li v-for="shot in review.storyboard.shots" :key="shot.id">
        <div class="item-index">{{ String(shot.order).padStart(2, '0') }}</div>
        <div>
          <p class="narration">{{ shot.visual_description }}</p>
          <p class="muted">口播：{{ shot.narration }}</p>
          <p class="artifact-label">Pexels 检索短语</p>
          <span class="query-chip query-primary">{{ shot.material_query }}</span>
          <p class="artifact-label keyword-label">英文关键词</p>
          <div class="query-chip-row">
            <span v-for="keyword in shot.keywords_en" :key="`en-${shot.id}-${keyword}`" class="query-chip">{{ keyword }}</span>
          </div>
          <p class="artifact-label keyword-label">中文关键词</p>
          <div class="query-chip-row">
            <span v-for="keyword in shot.keywords_cn" :key="`cn-${shot.id}-${keyword}`" class="query-chip">{{ keyword }}</span>
          </div>
          <p class="muted shot-meta">{{ shot.shot_type }} · {{ shot.transition_in }} · {{ shot.mood }}</p>
        </div>
        <time>{{ formatDuration(shot.estimated_duration_seconds) }}</time>
      </li>
    </ol>

    <div class="feedback-field">
      <label for="review-feedback">修改反馈 <span>（仅退回时必填）</span></label>
      <textarea
        id="review-feedback"
        v-model="feedback"
        :disabled="busy"
        maxlength="2000"
        rows="3"
        placeholder="例如：开场更快进入主题，第二个镜头改成近景……"
        :aria-invalid="Boolean(feedbackError)"
        :aria-describedby="feedbackError ? 'review-feedback-error' : undefined"
      ></textarea>
      <p v-if="feedbackError" id="review-feedback-error" class="field-error">{{ feedbackError }}</p>
    </div>
    <div class="review-actions">
      <button class="button secondary danger-text" type="button" :disabled="busy" @click="reject">
        退回重写
      </button>
      <button
        class="button primary"
        type="button"
        :disabled="busy"
        @click="emit('submit', { action: 'approve', feedback: null })"
      >
        {{ busy ? '正在提交…' : '批准并继续' }}
      </button>
    </div>
  </section>
</template>
