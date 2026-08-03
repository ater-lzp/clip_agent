<script setup lang="ts">
import type { TaskProgress } from '../types/domain'

defineProps<{ progress: TaskProgress; failed?: boolean }>()
</script>

<template>
  <div class="progress-block" aria-live="polite">
    <div class="progress-copy">
      <strong>{{ progress.current_step }}</strong>
      <span>{{ progress.completed_steps }} / {{ progress.total_steps }} 阶段</span>
    </div>
    <div
      class="progress-track"
      role="progressbar"
      :aria-valuenow="progress.completed_steps"
      aria-valuemin="0"
      :aria-valuemax="progress.total_steps"
      :aria-label="progress.current_step"
    >
      <span
        :class="{ failed }"
        :style="{ width: `${(progress.completed_steps / progress.total_steps) * 100}%` }"
      ></span>
    </div>
  </div>
</template>

