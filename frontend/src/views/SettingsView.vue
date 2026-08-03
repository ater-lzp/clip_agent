<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { capabilitiesApi, settingsApi } from '../api'
import { ApiError } from '../api/client'
import type { ProviderMode, UserSettings, VoiceOption } from '../types/domain'

const settings = ref<UserSettings>({
  default_aspect_ratio: '16:9',
  default_duration_seconds: 60,
  default_bgm_volume: 0.2,
  preferred_voice: 'mimo_default',
})
const voiceOptions = ref<VoiceOption[]>([])
const providerMode = ref<ProviderMode>('real')
const loading = ref(true)
const busy = ref(false)
const message = ref('')
const errorMessage = ref('')

onMounted(async () => {
  try {
    const [loadedSettings, capabilities] = await Promise.all([
      settingsApi.get(),
      capabilitiesApi.get(),
    ])
    settings.value = loadedSettings
    voiceOptions.value = capabilities.voices
    providerMode.value = capabilities.provider_mode
  } catch (error) {
    errorMessage.value = error instanceof ApiError ? error.message : '设置加载失败'
  } finally {
    loading.value = false
  }
})

async function save(): Promise<void> {
  busy.value = true
  message.value = ''
  errorMessage.value = ''
  try {
    settings.value = await settingsApi.update(settings.value)
    message.value = '偏好已保存'
  } catch (error) {
    errorMessage.value = error instanceof ApiError ? error.message : '保存失败，请重试'
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="page narrow-page">
    <div class="page-heading"><div><p class="eyebrow">Preferences</p><h1>创作偏好</h1></div></div>
    <div v-if="loading" class="state-card"><span class="spinner"></span><p>正在加载设置…</p></div>
    <form v-else class="panel settings-form" @submit.prevent="save">
      <div class="settings-row">
        <div><label for="default-duration">默认目标时长</label><p>新任务仍可单独调整。</p></div>
        <input id="default-duration" v-model.number="settings.default_duration_seconds" type="number" min="10" max="180" />
      </div>
      <div class="settings-row">
        <div><label for="default-ratio">默认画面比例</label><p>横屏适合知识内容，竖屏适合移动端。</p></div>
        <select id="default-ratio" v-model="settings.default_aspect_ratio"><option value="16:9">16:9 横屏</option><option value="9:16">9:16 竖屏</option></select>
      </div>
      <div class="settings-row">
        <div><label for="voice">偏好声音</label><p>仅是非敏感偏好；具体供应商配置由服务端管理。</p></div>
        <select id="voice" v-model="settings.preferred_voice">
          <option v-for="voice in voiceOptions" :key="voice.id" :value="voice.id">
            {{ voice.name }} · {{ voice.language }} · {{ voice.gender }}
          </option>
        </select>
      </div>
      <p v-if="providerMode === 'fake'" class="form-error" role="alert">当前是 fake 测试模式，音色会被记录但不会调用 MiMo。</p>
      <div class="settings-row">
        <div><label for="default-volume">默认 BGM 音量</label><p>线性增益 0–100%，最终决定时可修改。</p></div>
        <div class="volume-inline"><input id="default-volume" v-model.number="settings.default_bgm_volume" type="range" min="0" max="1" step="0.01" /><output>{{ Math.round(settings.default_bgm_volume * 100) }}%</output></div>
      </div>
      <p v-if="message" class="success-message" role="status">{{ message }}</p>
      <p v-if="errorMessage" class="form-error" role="alert">{{ errorMessage }}</p>
      <div class="form-footer"><p>本页面不会显示或修改服务端密钥与端点。</p><button class="button primary" type="submit" :disabled="busy">{{ busy ? '保存中…' : '保存偏好' }}</button></div>
    </form>
  </div>
</template>
