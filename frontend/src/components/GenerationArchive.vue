<script setup lang="ts">
import type { TaskDetail } from '../types/domain'
import { formatDuration } from '../utils/format'

defineProps<{ task: TaskDetail }>()
</script>

<template>
  <div class="generation-archive">
    <section class="archive-section" aria-labelledby="archive-script-heading">
      <div class="archive-heading">
        <div>
          <p class="eyebrow">Script</p>
          <h3 id="archive-script-heading">剧本</h3>
        </div>
        <span v-if="task.script">版本 {{ task.script.version }} · {{ formatDuration(task.script.total_duration_seconds) }}</span>
      </div>
      <p v-if="!task.script" class="archive-empty">尚未生成剧本。</p>
      <template v-else>
        <p class="archive-title">{{ task.script.title }}</p>
        <ol class="archive-list">
          <li v-for="segment in task.script.segments" :key="segment.id">
            <span class="item-index">{{ String(segment.order).padStart(2, '0') }}</span>
            <div>
              <p class="archive-location">{{ segment.location }}</p>
              <p class="archive-label">口播稿</p>
              <p class="narration">{{ segment.narration }}</p>
              <p class="archive-label">情绪指令</p>
              <p class="emotion-instruction">{{ segment.emotion }}</p>
            </div>
            <time>{{ formatDuration(segment.estimated_duration_seconds) }}</time>
          </li>
        </ol>
      </template>
    </section>

    <section class="archive-section" aria-labelledby="archive-storyboard-heading">
      <div class="archive-heading">
        <div>
          <p class="eyebrow">Storyboard</p>
          <h3 id="archive-storyboard-heading">分镜规划</h3>
        </div>
        <span v-if="task.storyboard">版本 {{ task.storyboard.version }} · {{ task.storyboard.total_shots }} 个镜头</span>
      </div>
      <p v-if="!task.storyboard" class="archive-empty">尚未生成分镜规划。</p>
      <ol v-else class="archive-list">
        <li v-for="shot in task.storyboard.shots" :key="shot.id">
          <span class="item-index">{{ String(shot.order).padStart(2, '0') }}</span>
          <div>
            <p class="narration">{{ shot.visual_description }}</p>
            <p class="archive-label">对应口播</p>
            <p class="archive-copy">{{ shot.narration }}</p>
            <p class="archive-label">Pexels 检索短语</p>
            <span class="query-chip query-primary">{{ shot.material_query }}</span>
            <p class="archive-label keyword-label">英文关键词</p>
            <div class="query-chip-row">
              <span v-for="keyword in shot.keywords_en" :key="`en-${shot.id}-${keyword}`" class="query-chip">{{ keyword }}</span>
            </div>
            <p class="archive-label keyword-label">中文关键词</p>
            <div class="query-chip-row">
              <span v-for="keyword in shot.keywords_cn" :key="`cn-${shot.id}-${keyword}`" class="query-chip">{{ keyword }}</span>
            </div>
          </div>
          <time>{{ formatDuration(shot.estimated_duration_seconds) }}</time>
        </li>
      </ol>
    </section>
  </div>
</template>
