<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { capabilitiesApi, profileApi, settingsApi } from '../api'
import { absoluteApiUrl } from '../api/client'
import { ApiError } from '../api/client'
import { useSession } from '../composables/useSession'
import type { ProviderMode, UserSettings, VoiceOption } from '../types/domain'

const router = useRouter()
const session = useSession()
const settings = ref<UserSettings>({
  default_aspect_ratio: '16:9',
  default_duration_seconds: 60,
  default_bgm_volume: 0.2,
  preferred_voice: 'mimo_default',
})
const voiceOptions = ref<VoiceOption[]>([])
const providerMode = ref<ProviderMode>('real')
const nickname = ref('')
const avatarFile = ref<File | null>(null)
const currentPassword = ref('')
const newPassword = ref('')
const confirmPassword = ref('')
const loading = ref(true)
const preferencesBusy = ref(false)
const profileBusy = ref(false)
const passwordBusy = ref(false)
const message = ref('')
const errorMessage = ref('')

onMounted(async () => {
  nickname.value = session.user.value?.nickname ?? ''
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

function resetMessages(): void {
  message.value = ''
  errorMessage.value = ''
}

async function savePreferences(): Promise<void> {
  preferencesBusy.value = true
  resetMessages()
  try {
    settings.value = await settingsApi.update(settings.value)
    message.value = '创作偏好已保存'
  } catch (error) {
    errorMessage.value = error instanceof ApiError ? error.message : '保存失败，请重试'
  } finally {
    preferencesBusy.value = false
  }
}

function selectAvatar(event: Event): void {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0] ?? null
  if (file && (!['image/jpeg', 'image/png'].includes(file.type) || file.size > 2 * 1024 * 1024)) {
    avatarFile.value = null
    errorMessage.value = '头像必须是 2MB 以内的 JPG 或 PNG'
    input.value = ''
    return
  }
  avatarFile.value = file
}

async function saveProfile(): Promise<void> {
  if (profileBusy.value) return
  profileBusy.value = true
  resetMessages()
  try {
    let updated = await profileApi.update(nickname.value)
    if (avatarFile.value) updated = await profileApi.uploadAvatar(avatarFile.value)
    session.setUser(updated)
    nickname.value = updated.nickname ?? ''
    avatarFile.value = null
    message.value = '账户资料已更新'
  } catch (error) {
    errorMessage.value = error instanceof ApiError ? error.message : '账户资料更新失败'
  } finally {
    profileBusy.value = false
  }
}

async function changePassword(): Promise<void> {
  if (passwordBusy.value) return
  passwordBusy.value = true
  resetMessages()
  try {
    await profileApi.changePassword({
      current_password: currentPassword.value,
      new_password: newPassword.value,
      confirm_password: confirmPassword.value,
    })
    session.clear()
    await router.push({ name: 'login', query: { passwordChanged: '1' } })
  } catch (error) {
    errorMessage.value = error instanceof ApiError ? error.message : '密码修改失败'
  } finally {
    passwordBusy.value = false
  }
}
</script>

<template>
  <div class="page narrow-page">
    <div class="page-heading">
      <div><p class="eyebrow">Account & preferences</p><h1>账户与设置</h1></div>
    </div>
    <div v-if="loading" class="state-card"><span class="spinner"></span><p>正在加载设置…</p></div>
    <template v-else>
      <form class="panel settings-form" @submit.prevent="saveProfile">
        <div class="section-heading"><div><p class="eyebrow">Profile</p><h2>账户资料</h2></div></div>
        <div class="settings-row">
          <div><label for="nickname">昵称</label><p>2–12 个中文、字母或数字，且不能与其他用户重复。</p></div>
          <input id="nickname" v-model="nickname" required minlength="2" maxlength="12" pattern="[\u4e00-\u9fffA-Za-z0-9]+" autocomplete="nickname" />
        </div>
        <div class="settings-row">
          <div class="avatar-setting-copy">
            <img v-if="session.user.value?.avatar_url" class="settings-avatar" :src="absoluteApiUrl(session.user.value.avatar_url)" alt="当前头像" />
            <span v-else class="settings-avatar avatar-placeholder" aria-hidden="true">{{ (nickname || session.user.value?.email || 'C').slice(0, 1).toUpperCase() }}</span>
            <div><label for="avatar">头像</label><p>JPG/PNG，不超过 2MB；服务端自动裁剪为 200×200。</p></div>
          </div>
          <div class="avatar-upload-control">
            <label class="button secondary avatar-upload-button" for="avatar">
              <span aria-hidden="true">↑</span>
              {{ avatarFile ? '重新选择头像' : '选择头像' }}
              <input id="avatar" type="file" accept="image/jpeg,image/png" @change="selectAvatar" />
            </label>
          </div>
        </div>
        <div class="form-footer"><p>{{ avatarFile ? `已选择：${avatarFile.name}` : '头像与昵称仅作为账户公开资料。' }}</p><button class="button primary" type="submit" :disabled="profileBusy">{{ profileBusy ? '更新中…' : '更新账户资料' }}</button></div>
      </form>

      <form class="panel settings-form" @submit.prevent="savePreferences">
        <div class="section-heading settings-section-heading"><div><p class="eyebrow">Preferences</p><h2>创作偏好</h2></div></div>
        <div class="settings-row">
          <div><label for="default-duration">默认目标时长</label><p>新任务仍可单独调整。</p></div>
          <input id="default-duration" v-model.number="settings.default_duration_seconds" type="number" min="10" max="180" />
        </div>
        <div class="settings-row">
          <div><label for="default-ratio">默认画面比例</label><p>横屏适合知识内容，竖屏适合移动端。</p></div>
          <select id="default-ratio" v-model="settings.default_aspect_ratio"><option value="16:9">16:9 横屏</option><option value="9:16">9:16 竖屏</option></select>
        </div>
        <div class="settings-row">
          <div><label for="voice">偏好声音</label><p>具体供应商配置只由服务端管理。</p></div>
          <select id="voice" v-model="settings.preferred_voice">
            <option v-for="voice in voiceOptions" :key="voice.id" :value="voice.id">{{ voice.name }} · {{ voice.language }} · {{ voice.gender }}</option>
          </select>
        </div>
        <p v-if="providerMode === 'fake'" class="form-error settings-message" role="alert">当前是 fake 测试模式，音色会被记录但不会调用 MiMo。</p>
        <div class="settings-row">
          <div><label for="default-volume">默认 BGM 音量</label><p>线性增益 0–100%，最终决定时可修改。</p></div>
          <div class="volume-inline"><input id="default-volume" v-model.number="settings.default_bgm_volume" type="range" min="0" max="1" step="0.01" /><output>{{ Math.round(settings.default_bgm_volume * 100) }}%</output></div>
        </div>
        <div class="form-footer"><p>本页面不会显示或修改服务端密钥与端点。</p><button class="button primary" type="submit" :disabled="preferencesBusy">{{ preferencesBusy ? '保存中…' : '保存创作偏好' }}</button></div>
      </form>

      <form class="panel settings-form" @submit.prevent="changePassword">
        <div class="section-heading settings-section-heading"><div><p class="eyebrow">Security</p><h2>修改密码</h2></div></div>
        <div class="settings-row"><label for="current-password">当前密码</label><input id="current-password" v-model="currentPassword" type="password" required maxlength="128" autocomplete="current-password" /></div>
        <div class="settings-row"><div><label for="new-password">新密码</label><p>至少 8 位，包含大小写字母和数字。</p></div><input id="new-password" v-model="newPassword" type="password" required minlength="8" maxlength="128" autocomplete="new-password" /></div>
        <div class="settings-row"><label for="confirm-password">确认新密码</label><input id="confirm-password" v-model="confirmPassword" type="password" required minlength="8" maxlength="128" autocomplete="new-password" /></div>
        <div class="form-footer"><p>修改成功后，所有设备都需要重新登录。</p><button class="button secondary" type="submit" :disabled="passwordBusy">{{ passwordBusy ? '修改中…' : '修改密码并退出' }}</button></div>
      </form>

      <p v-if="message" class="success-message settings-global-message" role="status">{{ message }}</p>
      <p v-if="errorMessage" class="form-error settings-global-message" role="alert">{{ errorMessage }}</p>
    </template>
  </div>
</template>
