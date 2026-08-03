<script setup lang="ts">
import { computed } from 'vue'
import type { TaskStatus } from '../types/domain'

const props = defineProps<{ status: TaskStatus }>()

const labels: Record<TaskStatus, string> = {
  queued: '等待开始',
  generating_script: '生成剧本',
  awaiting_script_review: '待审剧本',
  generating_storyboard: '生成分镜',
  awaiting_storyboard_review: '待审分镜',
  synthesizing_audio: '合成配音',
  building_timeline: '建立时间轴',
  fetching_assets: '获取素材',
  aligning_timeline: '音画对齐',
  rendering_preview: '渲染预览',
  awaiting_bgm_decision: '待选 BGM',
  processing_bgm: '处理 BGM',
  completed: '已完成',
  failed: '失败',
}

const tone = computed(() => {
  if (props.status === 'completed') return 'success'
  if (props.status === 'failed') return 'danger'
  if (props.status.startsWith('awaiting_')) return 'attention'
  return 'active'
})
</script>

<template>
  <span class="status-badge" :class="`status-${tone}`">
    <span class="status-dot" aria-hidden="true"></span>{{ labels[status] }}
  </span>
</template>

