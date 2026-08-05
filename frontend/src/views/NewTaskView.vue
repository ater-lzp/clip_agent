<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { accountApi, capabilitiesApi, settingsApi, tasksApi } from '../api'
import { ApiError } from '../api/client'
import type { AccountSummary, AspectRatio, MimoVoiceId, ProviderMode, VoiceOption } from '../types/domain'
import AdSlot from '../components/AdSlot.vue'

const topic = ref('')
const duration = ref(60)
const aspectRatio = ref<AspectRatio>('16:9')
const voiceId = ref<MimoVoiceId>('mimo_default')
const voiceOptions = ref<VoiceOption[]>([])
const providerMode = ref<ProviderMode>('real')
const busy = ref(false)
const loadingDefaults = ref(true)
const errorMessage = ref('')
const account = ref<AccountSummary | null>(null)
const router = useRouter()

const templates = [
  { title: '冷知识科普', prompt: '用简洁有力的方式科普一个反直觉的冷知识，并给出令人印象深刻的生活场景类比。' },
  { title: '产品种草', prompt: '面向年轻消费者，用轻松种草的语气介绍一款产品的 3 个核心卖点，并说明它解决了什么痛点。' },
  { title: '历史人物', prompt: '用讲故事的方式介绍一位历史人物的关键人生节点，突出一个值得学习的品质。' },
  { title: '旅行攻略', prompt: '面向第一次去某座城市旅行的人，按时间线给出一天的高效游玩路线和拍照打卡建议。' },
  { title: '读书分享', prompt: '分享一本值得读的书：核心观点、最打动人的片段，以及它为什么适合现在的读者。' },
  { title: 'AI 前沿', prompt: '用通俗语言介绍一个最近的 AI 技术趋势，说明它对普通人生活的影响。' },
]

function applyTemplate(prompt: string): void {
  topic.value = prompt
}

onMounted(async () => {
  try {
    const [settings, capabilities, accountData] = await Promise.all([settingsApi.get(), capabilitiesApi.get(), accountApi.get()])
    duration.value = settings.default_duration_seconds
    aspectRatio.value = settings.default_aspect_ratio
    voiceId.value = settings.preferred_voice
    voiceOptions.value = capabilities.voices
    providerMode.value = capabilities.provider_mode
    account.value = accountData.account
  } catch {
    errorMessage.value = '未能加载偏好，已使用安全默认值'
  } finally {
    loadingDefaults.value = false
  }
})

async function createTask(): Promise<void> {
  const normalized = topic.value.trim()
  if (normalized.length < 3) {
    errorMessage.value = '请至少用 3 个字符描述主题'
    return
  }
  busy.value = true
  errorMessage.value = ''
  const idempotencyKey = crypto.randomUUID()
  try {
    const task = await tasksApi.create(
      {
        topic: normalized,
        target_duration_seconds: duration.value,
        aspect_ratio: aspectRatio.value,
        voice_id: voiceId.value,
      },
      idempotencyKey,
    )
    await router.push(`/tasks/${task.id}`)
  } catch (error) {
    errorMessage.value = error instanceof ApiError ? error.message : '创建失败，请重试'
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="page narrow-page">
    <div class="page-heading">
      <div><p class="eyebrow">New production</p><h1>创建一条短视频</h1></div>
      <RouterLink class="text-link" to="/tasks">返回历史</RouterLink>
    </div>
    <AdSlot slot="new_task" />
    <form class="panel creation-form" @submit.prevent="createTask">
      <div class="form-section">
        <span class="step-number">01</span>
        <div>
          <label for="topic">你想讲什么？</label>
          <p class="field-hint">给出主题、目标受众或希望强调的角度。内容只在服务端受控流程中使用。</p>
          <div class="template-strip" aria-label="灵感模板">
            <button v-for="template in templates" :key="template.title" type="button" @click="applyTemplate(template.prompt)">{{ template.title }}</button>
          </div>
          <textarea
            id="topic"
            v-model="topic"
            rows="6"
            maxlength="1000"
            required
            placeholder="例如：面向第一次养猫的人，用轻松但可靠的语气解释幼猫到家第一周的准备工作。"
          ></textarea>
          <span class="character-count">{{ topic.length }} / 1000</span>
        </div>
      </div>
      <div class="form-section split-section">
        <span class="step-number">02</span>
        <div>
          <label for="duration">目标时长</label>
          <div class="duration-control">
            <input id="duration" v-model.number="duration" type="range" min="10" max="180" step="5" />
            <output for="duration">{{ duration }} 秒</output>
          </div>
        </div>
        <div>
          <fieldset>
            <legend>画面比例</legend>
            <div class="ratio-options">
              <label :class="{ selected: aspectRatio === '16:9' }">
                <input v-model="aspectRatio" type="radio" value="16:9" />
                <span class="ratio-icon landscape"></span><strong>16:9</strong><small>横屏</small>
              </label>
              <label :class="{ selected: aspectRatio === '9:16' }">
                <input v-model="aspectRatio" type="radio" value="9:16" />
                <span class="ratio-icon portrait"></span><strong>9:16</strong><small>竖屏</small>
              </label>
            </div>
          </fieldset>
        </div>
      </div>
      <div class="form-section">
        <span class="step-number">03</span>
        <div>
          <label for="voice-id">MiMo 配音音色</label>
          <p class="field-hint">此选择会固化到当前任务，并用于每一段真实 TTS 请求。</p>
          <select id="voice-id" v-model="voiceId" :disabled="loadingDefaults" required>
            <option v-for="voice in voiceOptions" :key="voice.id" :value="voice.id">
              {{ voice.name }} · {{ voice.language }} · {{ voice.gender }}
            </option>
          </select>
        </div>
      </div>
      <p v-if="providerMode === 'fake'" class="form-error" role="alert">
        当前服务处于 fake 测试模式：不会请求 LLM、MiMo 或 Pexels。请在服务端启用 real 后再创建正式任务。
      </p>
      <p v-if="account" class="field-hint">剩余生成次数：<strong>{{ account.generations_remaining }}</strong>。<RouterLink to="/account">充值或开通会员</RouterLink></p>
      <p v-if="errorMessage" class="form-error" role="alert">{{ errorMessage }}</p>
      <div class="form-footer">
        <p>创建后会先生成剧本，并在需要你审核时暂停。</p>
        <button class="button primary" type="submit" :disabled="busy || loadingDefaults || voiceOptions.length === 0 || account?.generations_remaining === 0">
          {{ busy ? '正在创建…' : '开始生成' }}
        </button>
      </div>
    </form>
  </div>
</template>
