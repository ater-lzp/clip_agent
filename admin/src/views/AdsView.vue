<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { absoluteUrl, request, type AdPlacement, type AdminAd, type Page } from '../api'
import PaginationBar from '../components/PaginationBar.vue'
import { formatDate } from '../utils'

const placementLabels: Record<AdPlacement, string> = {
  auto: '自动投放', history: '历史记录', community: '社区', new_task: '新建任务', task_detail: '任务详情',
}
const ads = ref<AdminAd[]>([])
const page = ref(1)
const pages = ref(0)
const total = ref(0)
const activeFilter = ref<'' | 'true' | 'false'>('')
const placementFilter = ref<'' | AdPlacement>('')
const loading = ref(true)
const busy = ref(false)
const error = ref('')
const notice = ref('')
const title = ref('')
const linkUrl = ref('')
const placement = ref<AdPlacement>('auto')
const isActive = ref(true)
const imageFile = ref<File | null>(null)
const localPreview = ref('')
const editing = ref<AdminAd | null>(null)
const editTitle = ref('')
const editLinkUrl = ref('')
const editPlacement = ref<AdPlacement>('auto')

async function load(reset = false): Promise<void> {
  if (reset) page.value = 1
  loading.value = true
  error.value = ''
  const params = new URLSearchParams({ page: String(page.value), page_size: '20' })
  if (activeFilter.value) params.set('active', activeFilter.value)
  if (placementFilter.value) params.set('placement', placementFilter.value)
  try {
    const result = await request<Page<AdminAd>>(`/api/v1/admin/ads?${params}`)
    ads.value = result.items
    pages.value = result.pages
    total.value = result.total
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '广告加载失败'
  } finally {
    loading.value = false
  }
}

function selectImage(event: Event): void {
  const file = (event.target as HTMLInputElement).files?.[0] ?? null
  if (localPreview.value) URL.revokeObjectURL(localPreview.value)
  imageFile.value = file
  localPreview.value = file ? URL.createObjectURL(file) : ''
}

async function createAd(): Promise<void> {
  if (!imageFile.value || busy.value) return
  busy.value = true
  error.value = ''
  notice.value = ''
  const form = new FormData()
  form.append('file', imageFile.value)
  form.append('title', title.value)
  form.append('link_url', linkUrl.value)
  form.append('placement', placement.value)
  form.append('is_active', String(isActive.value))
  try {
    await request<AdminAd>('/api/v1/admin/ads', { method: 'POST', body: form })
    title.value = ''
    linkUrl.value = ''
    placement.value = 'auto'
    isActive.value = true
    imageFile.value = null
    if (localPreview.value) URL.revokeObjectURL(localPreview.value)
    localPreview.value = ''
    notice.value = '广告已添加并可按投放状态展示'
    await load(true)
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '广告创建失败'
  } finally {
    busy.value = false
  }
}

async function toggle(ad: AdminAd): Promise<void> {
  if (busy.value) return
  busy.value = true
  error.value = ''
  try {
    const updated = await request<AdminAd>(`/api/v1/admin/ads/${ad.id}`, {
      method: 'PATCH', body: { is_active: !ad.is_active },
    })
    ads.value = ads.value.map((item) => item.id === ad.id ? updated : item)
    notice.value = updated.is_active ? '广告已启用' : '广告已停用'
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '广告状态更新失败'
  } finally {
    busy.value = false
  }
}

function openEdit(ad: AdminAd): void {
  editing.value = ad
  editTitle.value = ad.title
  editLinkUrl.value = ad.link_url
  editPlacement.value = ad.placement
}

async function saveEdit(): Promise<void> {
  if (!editing.value || busy.value) return
  busy.value = true
  error.value = ''
  try {
    const updated = await request<AdminAd>(`/api/v1/admin/ads/${editing.value.id}`, {
      method: 'PATCH',
      body: { title: editTitle.value, link_url: editLinkUrl.value, placement: editPlacement.value },
    })
    ads.value = ads.value.map((item) => item.id === updated.id ? updated : item)
    editing.value = null
    notice.value = '广告信息已更新'
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '广告更新失败'
  } finally {
    busy.value = false
  }
}

async function remove(ad: AdminAd): Promise<void> {
  if (!window.confirm(`确认删除广告“${ad.title}”？图片文件也会一并删除。`)) return
  busy.value = true
  error.value = ''
  try {
    await request<void>(`/api/v1/admin/ads/${ad.id}`, { method: 'DELETE' })
    notice.value = '广告已删除'
    await load(ads.value.length === 1 && page.value > 1)
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '广告删除失败'
  } finally {
    busy.value = false
  }
}

async function changePage(value: number): Promise<void> { page.value = value; await load() }
onMounted(load)
onBeforeUnmount(() => { if (localPreview.value) URL.revokeObjectURL(localPreview.value) })
</script>

<template>
  <section class="content">
    <div class="heading"><div><p class="eyebrow">Advertising</p><h1>广告管理</h1><p>上传静态图片或 GIF 动图，仅向免费用户投放。</p></div></div>
    <p v-if="notice" class="notice" role="status">{{ notice }}</p><p v-if="error" class="error" role="alert">{{ error }}</p>

    <form class="ad-create-form" @submit.prevent="createAd">
      <div class="ad-upload-preview">
        <img v-if="localPreview" :src="localPreview" alt="待上传广告预览" />
        <div v-else><strong>广告图片 / 动图</strong><small>JPG、PNG、GIF，最大 5MB</small></div>
        <label class="upload-picker">选择文件<input type="file" accept="image/jpeg,image/png,image/gif" required @change="selectImage" /></label>
      </div>
      <div class="ad-create-fields">
        <label>广告标题<input v-model="title" maxlength="80" required placeholder="用于展示和后台识别" /></label>
        <label>跳转链接<input v-model="linkUrl" type="url" maxlength="2048" required placeholder="https://example.com/landing" /></label>
        <label>投放位置<select v-model="placement"><option v-for="(label, value) in placementLabels" :key="value" :value="value">{{ label }}</option></select></label>
        <label class="toggle-field"><input v-model="isActive" type="checkbox" />创建后立即启用</label>
        <button type="submit" :disabled="busy || !imageFile">{{ busy ? '正在保存…' : '添加广告' }}</button>
      </div>
    </form>

    <div class="filters ad-filters">
      <label>状态<select v-model="activeFilter" @change="load(true)"><option value="">全部</option><option value="true">启用</option><option value="false">停用</option></select></label>
      <label>位置<select v-model="placementFilter" @change="load(true)"><option value="">全部</option><option v-for="(label, value) in placementLabels" :key="value" :value="value">{{ label }}</option></select></label>
      <span>共 {{ total }} 条广告</span>
    </div>
    <p v-if="loading">广告加载中…</p>
    <div v-else-if="!ads.length" class="empty surface-card">当前筛选下暂无广告</div>
    <section v-else class="admin-ad-grid">
      <article v-for="ad in ads" :key="ad.id" class="admin-ad-card">
        <a :href="ad.link_url" target="_blank" rel="noopener noreferrer"><img :src="absoluteUrl(ad.image_url)" :alt="ad.title" /></a>
        <div class="admin-ad-copy">
          <div class="card-heading"><span :class="ad.is_active ? 'ok' : 'stopped'">{{ ad.is_active ? '投放中' : '已停用' }}</span><small>{{ placementLabels[ad.placement] }}</small></div>
          <h2>{{ ad.title }}</h2><a class="ad-target" :href="ad.link_url" target="_blank" rel="noopener noreferrer">{{ ad.link_url }}</a>
          <dl><div><dt>曝光</dt><dd>{{ ad.impressions }}</dd></div><div><dt>点击</dt><dd>{{ ad.clicks }}</dd></div><div><dt>创建</dt><dd>{{ formatDate(ad.created_at) }}</dd></div></dl>
          <div class="row-actions"><button class="secondary small" type="button" :disabled="busy" @click="openEdit(ad)">编辑</button><button class="secondary small" type="button" :disabled="busy" @click="toggle(ad)">{{ ad.is_active ? '停用' : '启用' }}</button><button class="danger small" type="button" :disabled="busy" @click="remove(ad)">删除</button></div>
        </div>
      </article>
    </section>
    <PaginationBar :page="page" :pages="pages" :total="total" :busy="loading" @change="changePage" />

    <div v-if="editing" class="admin-modal-backdrop" @click.self="editing = null">
      <section class="admin-modal" role="dialog" aria-modal="true" aria-labelledby="edit-ad-title">
        <div class="card-heading"><h2 id="edit-ad-title">编辑广告</h2><button class="close" type="button" aria-label="关闭" @click="editing = null">×</button></div>
        <form @submit.prevent="saveEdit"><label>标题<input v-model="editTitle" maxlength="80" required /></label><label>跳转链接<input v-model="editLinkUrl" type="url" maxlength="2048" required /></label><label>投放位置<select v-model="editPlacement"><option v-for="(label, value) in placementLabels" :key="value" :value="value">{{ label }}</option></select></label><div class="modal-actions"><button class="secondary" type="button" @click="editing = null">取消</button><button type="submit" :disabled="busy">保存修改</button></div></form>
      </section>
    </div>
  </section>
</template>
