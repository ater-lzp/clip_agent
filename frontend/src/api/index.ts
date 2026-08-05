import { absoluteApiUrl, apiRequest } from './client'
import {
  parseCapabilities,
  parseBgmTrack,
  parseBgmTrackPage,
  parseCommunityComments,
  parseCommunityPost,
  parseCommunityPostPage,
  parsePublicUserProfile,
  parseSettings,
  parseTaskDetail,
  parseTaskPage,
  parseTaskStats,
  parseUser,
  parseAccount,
  parseAccountSummary,
  parseAdSelection,
} from './validators'
import type {
  BgmAction,
  MimoVoiceId,
  ReviewAction,
  TaskListStatus,
  UserSettings,
  LedgerEntry,
  AdSlotName,
} from '../types/domain'

export const adsApi = {
  select: (slot: AdSlotName) =>
    apiRequest<unknown>(`/api/v1/ads?slot=${encodeURIComponent(slot)}`).then(parseAdSelection),
  record: (adId: string, event: 'impression' | 'click') =>
    apiRequest<void>(`/api/v1/ads/${encodeURIComponent(adId)}/events`, {
      method: 'POST',
      body: { event },
    }),
  imageUrl: absoluteApiUrl,
}

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

export const profileApi = {
  update: (nickname: string) =>
    apiRequest<unknown>('/api/v1/profile', { method: 'PUT', body: { nickname } }).then(parseUser),
  uploadAvatar: (file: File) => {
    const form = new FormData()
    form.append('file', file)
    return apiRequest<unknown>('/api/v1/profile/avatar', {
      method: 'POST',
      body: form,
      timeoutMs: 30_000,
    }).then(parseUser)
  },
  changePassword: (body: {
    current_password: string
    new_password: string
    confirm_password: string
  }) => apiRequest<void>('/api/v1/profile/password', { method: 'POST', body }),
}

export const capabilitiesApi = {
  get: () => apiRequest<unknown>('/api/v1/capabilities').then(parseCapabilities),
}

export const accountApi = {
  get: () => apiRequest<unknown>('/api/v1/account').then(parseAccount),
  setPaymentPassword: (body: {
    account_password: string
    payment_password: string
    confirm_password: string
  }) => apiRequest<void>('/api/v1/account/payment-password', { method: 'POST', body }),
  redeemCdk: (code: string) =>
    apiRequest<unknown>('/api/v1/account/redeem-cdk', { method: 'POST', body: { code } }).then(parseAccountSummary),
  purchase: (tier: 'vip' | 'svip', paymentPassword: string, idempotencyKey: string) =>
    apiRequest<{ order: { id: string }; account: unknown }>('/api/v1/account/memberships', {
      method: 'POST',
      headers: { 'Idempotency-Key': idempotencyKey },
      body: { tier, payment_password: paymentPassword },
    }).then((value) => ({ ...value, account: parseAccountSummary(value.account) })),
  ledger: () =>
    apiRequest<{ items: LedgerEntry[] }>('/api/v1/account/ledger?page=1&page_size=50'),
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
  list: (page = 1, status?: TaskListStatus, pageSize = 20, query = '') => {
    const params = new URLSearchParams({ page: String(page), page_size: String(pageSize) })
    if (status === 'in_progress') params.set('status_group', status)
    else if (status) params.set('status', status)
    if (query) params.set('q', query)
    return apiRequest<unknown>(`/api/v1/tasks?${params}`).then(parseTaskPage)
  },
  stats: () => apiRequest<unknown>('/api/v1/tasks/stats').then(parseTaskStats),
  get: (taskId: string) => apiRequest<unknown>(`/api/v1/tasks/${taskId}`).then(parseTaskDetail),
  duplicate: (
    taskId: string,
    idempotencyKey: string,
  ) =>
    apiRequest<unknown>(`/api/v1/tasks/${taskId}/duplicate`, {
      method: 'POST',
      headers: { 'Idempotency-Key': idempotencyKey },
      body: {},
    }).then(parseTaskDetail),
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
    body: { version: number; action: BgmAction; volume: number | null; track_id: string | null },
  ) =>
    apiRequest<unknown>(`/api/v1/tasks/${taskId}/bgm-decision`, {
      method: 'POST',
      body,
    }).then(parseTaskDetail),
  listBgms: () => apiRequest<unknown>('/api/v1/bgms').then(parseBgmTrackPage),
  uploadBgm: (taskId: string, file: File) => {
    const form = new FormData()
    form.append('file', file)
    return apiRequest<unknown>(`/api/v1/tasks/${taskId}/bgm-upload`, {
      method: 'POST',
      body: form,
      timeoutMs: 150_000,
    }).then(parseBgmTrack)
  },
  retry: (taskId: string) =>
    apiRequest<unknown>(`/api/v1/tasks/${taskId}/retry`, { method: 'POST' }).then(parseTaskDetail),
  delete: (taskId: string) => apiRequest<void>(`/api/v1/tasks/${taskId}`, { method: 'DELETE' }),
  bulkDelete: (body: { mode: 'all' | 'selected'; task_ids: string[] }) =>
    apiRequest<{ deleted_count: number }>('/api/v1/tasks/bulk-delete', { method: 'POST', body }),
  previewUrl: (path: string) => absoluteApiUrl(path),
  coverUrl: (path: string) => absoluteApiUrl(path),
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

export const communityApi = {
  list: (scope: 'all' | 'mine' | 'favorites' | 'shared' | 'following' = 'all', page = 1, tag = '') => {
    const query = new URLSearchParams({ scope, page: String(page), page_size: '20' })
    if (tag) query.set('tag', tag)
    return apiRequest<unknown>(`/api/v1/community/posts?${query}`).then(parseCommunityPostPage)
  },
  get: (postId: string) =>
    apiRequest<unknown>(`/api/v1/community/posts/${postId}`).then(parseCommunityPost),
  publish: (body: {
    task_id: string
    title: string
    description: string
    prompt_public: boolean
    tags: string[]
  }) => apiRequest<unknown>('/api/v1/community/posts', { method: 'POST', body }).then(parseCommunityPost),
  delete: (postId: string) => apiRequest<void>(`/api/v1/community/posts/${postId}`, { method: 'DELETE' }),
  comments: (postId: string, sort: 'latest' | 'hot') =>
    apiRequest<unknown>(`/api/v1/community/posts/${postId}/comments?sort=${sort}`).then(parseCommunityComments),
  comment: (postId: string, content: string, parentId: string | null) =>
    apiRequest<{ id: string }>(`/api/v1/community/posts/${postId}/comments`, {
      method: 'POST',
      body: { content, parent_id: parentId },
    }),
  deleteComment: (commentId: string) =>
    apiRequest<void>(`/api/v1/community/comments/${commentId}`, { method: 'DELETE' }),
  likeComment: (commentId: string) =>
    apiRequest<{ liked: boolean }>(`/api/v1/community/comments/${commentId}/like`, { method: 'PUT' }),
  like: (postId: string) =>
    apiRequest<{ liked: boolean }>(`/api/v1/community/posts/${postId}/like`, { method: 'PUT' }),
  favorite: (postId: string) =>
    apiRequest<{ favorited: boolean }>(`/api/v1/community/posts/${postId}/favorite`, { method: 'PUT' }),
  getUser: (userId: string) =>
    apiRequest<unknown>(`/api/v1/users/${userId}`).then(parsePublicUserProfile),
  follow: (userId: string) =>
    apiRequest<{ following: boolean }>(`/api/v1/users/${userId}/follow`, { method: 'PUT' }),
  listByUser: (userId: string, page = 1) => {
    const query = new URLSearchParams({ scope: 'all', owner_id: userId, page: String(page), page_size: '20' })
    return apiRequest<unknown>(`/api/v1/community/posts?${query}`).then(parseCommunityPostPage)
  },
  searchUsers: (query: string) =>
    apiRequest<{ items: Array<{ id: string; name: string; avatar_url: string | null }> }>(
      `/api/v1/community/users/search?q=${encodeURIComponent(query)}`,
    ),
  share: (postId: string, recipientId: string) =>
    apiRequest<{ shared: boolean }>(`/api/v1/community/posts/${postId}/shares`, {
      method: 'POST',
      body: { recipient_id: recipientId },
    }),
  mediaUrl: (path: string) => absoluteApiUrl(path),
}
