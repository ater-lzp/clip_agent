<script setup lang="ts">
import { useTheme } from '../composables/useTheme'

const theme = useTheme()
</script>

<template>
  <button
    class="theme-toggle"
    type="button"
    :aria-label="theme.theme.value === 'dark' ? '切换到亮色主题' : '切换到暗色主题'"
    :title="theme.theme.value === 'dark' ? '亮色主题' : '暗色主题'"
    @click="theme.toggle"
  >
    <span aria-hidden="true">{{ theme.theme.value === 'dark' ? '☀' : '☾' }}</span>
  </button>
</template>
