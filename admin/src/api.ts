const base = (import.meta.env.VITE_API_BASE_URL ?? '').replace(/\/$/, '')

function cookie(name: string): string | null {
  const prefix = `${encodeURIComponent(name)}=`
  const item = document.cookie.split('; ').find((value) => value.startsWith(prefix))
  return item ? decodeURIComponent(item.slice(prefix.length)) : null
}

export async function request<T>(path: string, options: { method?: string; body?: unknown } = {}): Promise<T> {
  const method = options.method ?? 'GET'
  const headers = new Headers({ Accept: 'application/json' })
  const isFormData = options.body instanceof FormData
  if (options.body !== undefined && !isFormData) headers.set('Content-Type', 'application/json')
  if (method !== 'GET') {
    const csrf = cookie('clip_csrf')
    if (csrf) headers.set('X-CSRF-Token', csrf)
  }
  const requestBody: BodyInit | undefined = options.body === undefined
    ? undefined
    : isFormData
      ? options.body as FormData
      : JSON.stringify(options.body)
  const response = await fetch(`${base}${path}`, {
    method,
    headers,
    credentials: 'include',
    body: requestBody,
  })
  if (!response.ok) {
    const value = await response.json().catch(() => null) as { error?: { message?: string } } | null
    throw new Error(value?.error?.message ?? '管理服务请求失败')
  }
  return response.status === 204 ? undefined as T : await response.json() as T
}

export function absoluteUrl(path: string): string { return `${base}${path}` }

export type UserRole = 'user' | 'admin'
export type MembershipTier = 'free' | 'vip' | 'svip'
export type ProviderMode = 'real' | 'fake'
export type TaskStatus =
  | 'queued' | 'generating_script' | 'awaiting_script_review'
  | 'generating_storyboard' | 'awaiting_storyboard_review' | 'synthesizing_audio'
  | 'building_timeline' | 'fetching_assets' | 'aligning_timeline'
  | 'rendering_preview' | 'awaiting_bgm_decision' | 'processing_bgm'
  | 'completed' | 'failed'

export interface Page<T> {
  items: T[]
  page: number
  page_size: number
  total: number
  pages: number
}

export interface Dashboard {
  user_total: number
  active_users: number
  vip_users: number
  svip_users: number
  task_total: number
  completed_tasks: number
  failed_tasks: number
  in_progress_tasks: number
  awaiting_tasks: number
  today_users: number
  membership_revenue_cents: number
  cdk_total: number
  cdk_used: number
}

export interface AdminUser {
  id: string
  email: string
  nickname: string | null
  role: UserRole
  is_active: boolean
  membership_tier: MembershipTier
  membership_expires_at: string | null
  balance_cents: number
  generation_quota: number
  generations_used: number
  generations_remaining: number
  created_at: string
  task_count: number | null
}

export interface LedgerEntry {
  id: string
  kind: 'cdk_recharge' | 'membership_payment'
  amount_cents: number
  balance_after_cents: number
  reference_type: string
  created_at: string
}

export interface AdminUserDetail extends AdminUser {
  task_count: number
  completed_task_count: number
  failed_task_count: number
  recent_ledger: LedgerEntry[]
}

export interface AdminTask {
  id: string
  user_id: string
  user_email: string
  user_nickname: string | null
  topic: string
  status: TaskStatus
  current_stage: string
  provider_mode: ProviderMode
  target_duration_seconds: number
  final_duration_seconds: number | null
  aspect_ratio: '16:9' | '9:16'
  error_code: string | null
  error_message: string | null
  created_at: string
  updated_at: string
}

export interface AuditLog {
  id: string
  actor_id: string | null
  actor_email: string | null
  actor_nickname: string | null
  action: string
  target_type: string | null
  target_id: string | null
  ip_address: string
  created_at: string
}

export interface CdkItem {
  id: string
  code_hint: string
  amount_cents: number
  status: 'unused' | 'used'
  created_at: string
  used_at: string | null
  used_by: string | null
  used_by_email: string | null
  used_by_nickname: string | null
}

export type AdPlacement = 'auto' | 'history' | 'community' | 'new_task' | 'task_detail'

export interface AdminAd {
  id: string
  title: string
  link_url: string
  placement: AdPlacement
  image_url: string
  image_media_type: 'image/jpeg' | 'image/png' | 'image/gif'
  is_active: boolean
  impressions: number
  clicks: number
  created_at: string
  updated_at: string
}
