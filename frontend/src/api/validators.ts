import type {
  Capabilities,
  MimoVoiceId,
  TaskDetail,
  TaskPage,
  TaskStatus,
  User,
  UserSettings,
} from '../types/domain'

const mimoVoiceIds = new Set<MimoVoiceId>([
  'mimo_default',
  '冰糖',
  '茉莉',
  '苏打',
  '白桦',
  'Mia',
  'Chloe',
  'Milo',
  'Dean',
])

const taskStatuses = new Set<TaskStatus>([
  'queued',
  'generating_script',
  'awaiting_script_review',
  'generating_storyboard',
  'awaiting_storyboard_review',
  'synthesizing_audio',
  'building_timeline',
  'fetching_assets',
  'aligning_timeline',
  'rendering_preview',
  'awaiting_bgm_decision',
  'processing_bgm',
  'completed',
  'failed',
])

function record(value: unknown, label: string): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new Error(`${label} 响应格式无效`)
  }
  return value as Record<string, unknown>
}

function requiredString(value: unknown, label: string): string {
  if (typeof value !== 'string' || !value) throw new Error(`${label} 响应格式无效`)
  return value
}

export function parseUser(value: unknown): User {
  const data = record(value, '用户')
  return {
    id: requiredString(data.id, '用户 ID'),
    email: requiredString(data.email, '邮箱'),
    created_at: requiredString(data.created_at, '创建时间'),
  }
}

export function parseSettings(value: unknown): UserSettings {
  const data = record(value, '设置')
  if (!['16:9', '9:16'].includes(String(data.default_aspect_ratio))) throw new Error('默认比例响应格式无效')
  if (!mimoVoiceIds.has(data.preferred_voice as MimoVoiceId)) throw new Error('声音偏好响应格式无效')
  if (typeof data.default_duration_seconds !== 'number' || typeof data.default_bgm_volume !== 'number') {
    throw new Error('设置数值响应格式无效')
  }
  return data as unknown as UserSettings
}

export function parseCapabilities(value: unknown): Capabilities {
  const data = record(value, '服务能力')
  if (!['real', 'fake'].includes(String(data.provider_mode))) throw new Error('供应商模式响应格式无效')
  if (typeof data.external_requests_enabled !== 'boolean' || !Array.isArray(data.voices)) {
    throw new Error('服务能力响应格式无效')
  }
  for (const rawVoice of data.voices) {
    const voice = record(rawVoice, '音色')
    if (!mimoVoiceIds.has(voice.id as MimoVoiceId)) throw new Error('音色 ID 响应格式无效')
    requiredString(voice.name, '音色名称')
    requiredString(voice.language, '音色语言')
    requiredString(voice.gender, '音色性别')
  }
  return data as unknown as Capabilities
}

function validateTaskSummary(value: unknown): Record<string, unknown> {
  const data = record(value, '任务')
  requiredString(data.id, '任务 ID')
  requiredString(data.topic, '任务主题')
  requiredString(data.created_at, '任务创建时间')
  requiredString(data.updated_at, '任务更新时间')
  if (!taskStatuses.has(data.status as TaskStatus)) throw new Error('任务状态响应格式无效')
  if (!['16:9', '9:16'].includes(String(data.aspect_ratio))) throw new Error('任务比例响应格式无效')
  if (!mimoVoiceIds.has(data.voice_id as MimoVoiceId)) throw new Error('任务音色响应格式无效')
  if (!['real', 'fake'].includes(String(data.provider_mode))) throw new Error('任务供应商模式响应格式无效')
  const progress = record(data.progress, '任务进度')
  if (typeof progress.completed_steps !== 'number' || progress.total_steps !== 12) {
    throw new Error('任务进度响应格式无效')
  }
  return data
}

export function parseTaskDetail(value: unknown): TaskDetail {
  const data = validateTaskSummary(value)
  requiredString(data.thread_id, '工作流 ID')
  if (data.pending_review !== null) {
    const pending = record(data.pending_review, '待审核内容')
    if (!['script', 'storyboard', 'bgm'].includes(String(pending.kind)) || typeof pending.version !== 'number') {
      throw new Error('待审核内容响应格式无效')
    }
  }
  return data as unknown as TaskDetail
}

export function parseTaskPage(value: unknown): TaskPage {
  const data = record(value, '任务列表')
  if (!Array.isArray(data.items)) throw new Error('任务列表响应格式无效')
  data.items.forEach(validateTaskSummary)
  for (const key of ['page', 'page_size', 'total', 'pages']) {
    if (typeof data[key] !== 'number') throw new Error('任务分页响应格式无效')
  }
  return data as unknown as TaskPage
}
