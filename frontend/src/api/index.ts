import { absoluteApiUrl, apiRequest } from './client'
import { parseCapabilities, parseSettings, parseTaskDetail, parseTaskPage, parseUser } from './validators'
import type {
  BgmAction,
  MimoVoiceId,
  ReviewAction,
  TaskStatus,
  UserSettings,
} from '../types/domain'

export const authApi = {
  register: (email: string, password: string) =>
    apiRequest<unknown>('/api/v1/auth/register', { method: 'POST', body: { email, password } }).then(parseUser),
  login: (email: string, password: string) =>
    apiRequest<unknown>('/api/v1/auth/login', { method: 'POST', body: { email, password } }).then(parseUser),
  me: () => apiRequest<unknown>('/api/v1/auth/me').then(parseUser),
  logout: () => apiRequest<void>('/api/v1/auth/session', { method: 'DELETE' }),
}

export const settingsApi = {
  get: () => apiRequest<unknown>('/api/v1/settings').then(parseSettings),
  update: (settings: UserSettings) =>
    apiRequest<unknown>('/api/v1/settings', { method: 'PUT', body: settings }).then(parseSettings),
}

export const capabilitiesApi = {
  get: () => apiRequest<unknown>('/api/v1/capabilities').then(parseCapabilities),
}

export const tasksApi = {
  create: (
    input: {
      topic: string
      target_duration_seconds: number
      aspect_ratio: '16:9' | '9:16'
      voice_id: MimoVoiceId
    },
    idempotencyKey: string,
  ) =>
    apiRequest<unknown>('/api/v1/tasks', {
      method: 'POST',
      headers: { 'Idempotency-Key': idempotencyKey },
      body: input,
    }).then(parseTaskDetail),
  list: (page = 1, status?: TaskStatus) => {
    const query = new URLSearchParams({ page: String(page), page_size: '20' })
    if (status) query.set('status', status)
    return apiRequest<unknown>(`/api/v1/tasks?${query}`).then(parseTaskPage)
  },
  get: (taskId: string) => apiRequest<unknown>(`/api/v1/tasks/${taskId}`).then(parseTaskDetail),
  review: (
    taskId: string,
    kind: 'script' | 'storyboard',
    body: { version: number; action: ReviewAction; feedback: string | null },
  ) =>
    apiRequest<unknown>(`/api/v1/tasks/${taskId}/reviews/${kind}`, {
      method: 'POST',
      body,
    }).then(parseTaskDetail),
  decideBgm: (
    taskId: string,
    body: { version: number; action: BgmAction; volume: number | null },
  ) =>
    apiRequest<unknown>(`/api/v1/tasks/${taskId}/bgm-decision`, {
      method: 'POST',
      body,
    }).then(parseTaskDetail),
  retry: (taskId: string) =>
    apiRequest<unknown>(`/api/v1/tasks/${taskId}/retry`, { method: 'POST' }).then(parseTaskDetail),
  delete: (taskId: string) => apiRequest<void>(`/api/v1/tasks/${taskId}`, { method: 'DELETE' }),
  previewUrl: (path: string) => absoluteApiUrl(path),
  async download(path: string, fallbackName: string): Promise<void> {
    const response = await fetch(absoluteApiUrl(path), { credentials: 'include' })
    if (!response.ok) throw new Error('下载失败，请稍后重试')
    const blob = await response.blob()
    const objectUrl = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = objectUrl
    link.download = fallbackName.replace(/[^a-zA-Z0-9._-]/g, '-')
    link.click()
    URL.revokeObjectURL(objectUrl)
  },
}
