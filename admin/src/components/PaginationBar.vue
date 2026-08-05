<script setup lang="ts">
defineProps<{ page: number; pages: number; total: number; busy?: boolean }>()
defineEmits<{ change: [page: number] }>()
</script>

<template>
  <div class="pagination" aria-label="分页">
    <span>共 {{ total }} 条</span>
    <div>
      <button class="secondary small" type="button" :disabled="busy || page <= 1" @click="$emit('change', page - 1)">上一页</button>
      <span>第 {{ page }} / {{ Math.max(pages, 1) }} 页</span>
      <button class="secondary small" type="button" :disabled="busy || page >= pages" @click="$emit('change', page + 1)">下一页</button>
    </div>
  </div>
</template>
