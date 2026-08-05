import type {
  Capabilities,
  BgmTrack,
  CommunityComment,
  CommunityPost,
  CommunityPostPage,
  MimoVoiceId,
  PublicUserProfile,
  TaskDetail,
  TaskPage,
  TaskStats,
  TaskStatus,
  User,
  UserSettings,
  AccountData,
  AccountSummary,
  AdCreative,
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

export function parseAdSelection(value: unknown): { item: AdCreative | null } {
  const response = record(value, '广告')
  if (response.item === null) return { item: null }
  const item = record(response.item, '广告创意')
  if (!['auto', 'history', 'community', 'new_task', 'task_detail'].includes(String(item.placement))) {
    throw new Error('广告位置响应格式无效')
  }
  if (!['image/jpeg', 'image/png', 'image/gif'].includes(String(item.image_media_type))) {
    throw new Error('广告图片格式响应无效')
  }
  const linkUrl = requiredString(item.link_url, '广告链接')
  const imageUrl = requiredString(item.image_url, '广告图片地址')
  let parsedLink: URL
  try {
    parsedLink = new URL(linkUrl)
  } catch {
    throw new Error('广告链接响应格式无效')
  }
  if (!['http:', 'https:'].includes(parsedLink.protocol) || parsedLink.username || parsedLink.password) {
    throw new Error('广告链接响应格式无效')
  }
  if (!/^\/api\/v1\/ads\/[0-9a-f-]+\/image$/.test(imageUrl)) {
    throw new Error('广告图片地址响应格式无效')
  }
  return {
    item: {
      id: requiredString(item.id, '广告 ID'),
      title: requiredString(item.title, '广告标题'),
      link_url: linkUrl,
      placement: item.placement as AdCreative['placement'],
      image_url: imageUrl,
      image_media_type: item.image_media_type as AdCreative['image_media_type'],
    },
  }
}

export function parseUser(value: unknown): User {
  const data = record(value, '用户')
  if (data.nickname !== null && typeof data.nickname !== 'string') throw new Error('用户昵称响应格式无效')
  if (data.avatar_url !== null && typeof data.avatar_url !== 'string') throw new Error('用户头像响应格式无效')
  if (!['user', 'admin'].includes(String(data.role))) throw new Error('用户角色响应格式无效')
  return {
    id: requiredString(data.id, '用户 ID'),
    email: requiredString(data.email, '邮箱'),
    nickname: data.nickname,
    avatar_url: data.avatar_url,
    role: data.role as 'user' | 'admin',
    created_at: requiredString(data.created_at, '创建时间'),
  }
}

export function parseAccountSummary(value: unknown): AccountSummary {
  const data = record(value, '账户')
  if (!['free', 'vip', 'svip'].includes(String(data.membership_tier))) throw new Error('会员类型响应格式无效')
  if (data.membership_expires_at !== null && typeof data.membership_expires_at !== 'string') {
    throw new Error('会员到期时间响应格式无效')
  }
  for (const key of ['balance_cents', 'generation_quota', 'generations_used', 'generations_remaining']) {
    if (typeof data[key] !== 'number') throw new Error('账户数值响应格式无效')
  }
  if (typeof data.has_payment_password !== 'boolean') throw new Error('支付密码状态响应格式无效')
  return data as unknown as AccountSummary
}

export function parseAccount(value: unknown): AccountData {
  const data = record(value, '账户信息')
  parseAccountSummary(data.account)
  if (!Array.isArray(data.plans)) throw new Error('会员套餐响应格式无效')
  for (const raw of data.plans) {
    const plan = record(raw, '会员套餐')
    if (!['vip', 'svip'].includes(String(plan.tier))) throw new Error('会员套餐响应格式无效')
    requiredString(plan.name, '套餐名称')
    for (const key of ['price_cents', 'duration_days', 'generation_credits']) {
      if (typeof plan[key] !== 'number') throw new Error('会员套餐数值响应格式无效')
    }
  }
  return data as unknown as AccountData
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
  if (data.cover_url !== null && typeof data.cover_url !== 'string') throw new Error('任务封面响应格式无效')
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
    if (pending.kind === 'bgm' && pending.uploaded_track !== null) validateBgmTrack(pending.uploaded_track)
  }
  return data as unknown as TaskDetail
}

function validateBgmTrack(value: unknown): Record<string, unknown> {
  const data = record(value, '背景音乐')
  requiredString(data.id, '背景音乐 ID')
  requiredString(data.name, '背景音乐名称')
  requiredString(data.preview_url, '背景音乐试听地址')
  if (!['library', 'upload'].includes(String(data.source)) || typeof data.duration_seconds !== 'number') {
    throw new Error('背景音乐响应格式无效')
  }
  return data
}

export function parseBgmTrackPage(value: unknown): { items: BgmTrack[] } {
  const data = record(value, '背景音乐列表')
  if (!Array.isArray(data.items)) throw new Error('背景音乐列表响应格式无效')
  data.items.forEach(validateBgmTrack)
  return data as unknown as { items: BgmTrack[] }
}

export function parseBgmTrack(value: unknown): BgmTrack {
  return validateBgmTrack(value) as unknown as BgmTrack
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

export function parseCommunityPost(value: unknown): CommunityPost {
  const data = record(value, '社区作品')
  requiredString(data.id, '作品 ID')
  requiredString(data.title, '作品标题')
  requiredString(data.video_url, '作品视频')
  requiredString(data.cover_url, '作品封面')
  const author = record(data.author, '作品作者')
  requiredString(author.id, '作者 ID')
  requiredString(author.name, '作者名称')
  if (author.avatar_url !== null && typeof author.avatar_url !== 'string') {
    throw new Error('作品作者头像响应格式无效')
  }
  if (
    !Array.isArray(data.tags) ||
    typeof data.favorited !== 'boolean' ||
    typeof data.liked !== 'boolean' ||
    typeof data.like_count !== 'number' ||
    typeof data.favorite_count !== 'number' ||
    typeof data.comment_count !== 'number' ||
    typeof data.share_count !== 'number'
  ) {
    throw new Error('社区作品响应格式无效')
  }
  return data as unknown as CommunityPost
}

export function parseTaskStats(value: unknown): TaskStats {
  const data = record(value, '任务统计')
  for (const key of ['total', 'completed', 'failed', 'in_progress', 'awaiting_review', 'total_duration_seconds']) {
    if (typeof data[key] !== 'number') throw new Error('任务统计响应格式无效')
  }
  return data as unknown as TaskStats
}

export function parsePublicUserProfile(value: unknown): PublicUserProfile {
  const data = record(value, '用户主页')
  requiredString(data.id, '用户 ID')
  requiredString(data.created_at, '用户创建时间')
  if (data.nickname !== null && typeof data.nickname !== 'string') throw new Error('用户主页昵称响应格式无效')
  if (data.avatar_url !== null && typeof data.avatar_url !== 'string') throw new Error('用户主页头像响应格式无效')
  for (const key of ['follower_count', 'following_count', 'post_count']) {
    if (typeof data[key] !== 'number') throw new Error('用户主页统计响应格式无效')
  }
  if (typeof data.is_following !== 'boolean' || typeof data.is_self !== 'boolean') {
    throw new Error('用户主页状态响应格式无效')
  }
  return data as unknown as PublicUserProfile
}

export function parseCommunityPostPage(value: unknown): CommunityPostPage {
  const data = record(value, '社区列表')
  if (!Array.isArray(data.items)) throw new Error('社区列表响应格式无效')
  data.items.forEach(parseCommunityPost)
  for (const key of ['page', 'page_size', 'total', 'pages']) {
    if (typeof data[key] !== 'number') throw new Error('社区分页响应格式无效')
  }
  return data as unknown as CommunityPostPage
}

export function parseCommunityComments(value: unknown): { items: CommunityComment[] } {
  const data = record(value, '评论列表')
  if (!Array.isArray(data.items)) throw new Error('评论列表响应格式无效')
  for (const value of data.items) {
    const comment = record(value, '评论')
    requiredString(comment.id, '评论 ID')
    requiredString(comment.content, '评论内容')
    record(comment.author, '评论作者')
  }
  return data as unknown as { items: CommunityComment[] }
}
