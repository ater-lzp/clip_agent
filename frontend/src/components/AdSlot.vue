<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { adsApi } from '../api'
import type { AdCreative, AdSlotName } from '../types/domain'

const props = defineProps<{ slot: AdSlotName }>()
const ad = ref<AdCreative | null>(null)
const loading = ref(true)

function dismissedKey(adId: string): string {
  return `clip:dismissed-ad:${adId}`
}

async function load(): Promise<void> {
  try {
    const selection = await adsApi.select(props.slot)
    if (selection.item && sessionStorage.getItem(dismissedKey(selection.item.id)) !== '1') {
      ad.value = selection.item
      void adsApi.record(selection.item.id, 'impression').catch(() => undefined)
    }
  } catch {
    ad.value = null
  } finally {
    loading.value = false
  }
}

function dismiss(): void {
  if (!ad.value) return
  sessionStorage.setItem(dismissedKey(ad.value.id), '1')
  ad.value = null
}

function recordClick(): void {
  if (ad.value) void adsApi.record(ad.value.id, 'click').catch(() => undefined)
}

onMounted(load)
</script>

<template>
  <aside v-if="ad" class="ad-slot" :class="`ad-slot-${slot}`" aria-label="推广内容">
    <a
      class="ad-link"
      :href="ad.link_url"
      target="_blank"
      rel="noopener noreferrer sponsored"
      @click="recordClick"
    >
      <img :src="adsApi.imageUrl(ad.image_url)" :alt="ad.title" />
      <span class="ad-caption"><small>广告</small><strong>{{ ad.title }}</strong><span>了解详情 ↗</span></span>
    </a>
    <button class="ad-close" type="button" aria-label="关闭广告" title="关闭广告" @click="dismiss">×</button>
  </aside>
  <span v-else-if="loading" class="ad-loading" aria-hidden="true"></span>
</template>
