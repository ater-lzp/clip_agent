<script setup lang="ts">
import { ref, watch } from 'vue'
import type { PendingReview } from '../types/domain'

type BgmReview = Extract<PendingReview, { kind: 'bgm' }>
const props = defineProps<{ review: BgmReview; busy: boolean }>()
const emit = defineEmits<{ decide: [payload: { action: 'no_add' | 'add'; volume: number | null }] }>()
const volume = ref(props.review.default_volume)

watch(
  () => props.review.version,
  () => {
    volume.value = props.review.default_volume
  },
)
</script>

<template>
  <section class="panel bgm-panel" aria-labelledby="bgm-heading">
    <div class="section-heading">
      <div><p class="eyebrow">最后一步 · 流程已暂停</p><h2 id="bgm-heading">是否添加背景音乐？</h2></div>
    </div>
    <p>建议关键词：<span class="query-chip">{{ review.suggested_query }}</span></p>
    <label for="bgm-volume">BGM 音量 <strong>{{ Math.round(volume * 100) }}%</strong></label>
    <input id="bgm-volume" v-model.number="volume" type="range" min="0" max="1" step="0.01" :disabled="busy" />
    <p class="field-hint">使用线性增益，并应用淡入淡出与防削波限制。</p>
    <div class="review-actions">
      <button class="button secondary" type="button" :disabled="busy" @click="emit('decide', { action: 'no_add', volume: null })">不添加，直接完成</button>
      <button class="button primary" type="button" :disabled="busy" @click="emit('decide', { action: 'add', volume })">{{ busy ? '正在提交…' : '添加并混音' }}</button>
    </div>
  </section>
</template>

