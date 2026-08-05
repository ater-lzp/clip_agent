export type AspectRatio = '16:9' | '9:16'
export type ReviewAction = 'approve' | 'reject'
export type BgmAction = 'no_add' | 'add'
export type ProviderMode = 'real' | 'fake'
export type MimoVoiceId =
  | 'mimo_default'
  | '冰糖'
  | '茉莉'
  | '苏打'
  | '白桦'
  | 'Mia'
  | 'Chloe'
  | 'Milo'
  | 'Dean'
export type TaskStatus =
  | 'queued'
  | 'generating_script'
  | 'awaiting_script_review'
  | 'generating_storyboard'
  | 'awaiting_storyboard_review'
  | 'synthesizing_audio'
  | 'building_timeline'
  | 'fetching_assets'
  | 'aligning_timeline'
  | 'rendering_preview'
  | 'awaiting_bgm_decision'
  | 'processing_bgm'
  | 'completed'
  | 'failed'
export type TaskListStatus = TaskStatus | 'in_progress'

export interface BgmTrack {
  id: string
  name: string
  source: 'library' | 'upload'
  duration_seconds: number
  preview_url: string
}

export interface User {
  id: string
  email: string
  nickname: string | null
  avatar_url: string | null
  role: 'user' | 'admin'
  created_at: string
}

export type MembershipTier = 'free' | 'vip' | 'svip'

export interface AccountSummary {
  membership_tier: MembershipTier
  membership_expires_at: string | null
  balance_cents: number
  generation_quota: number
  generations_used: number
  generations_remaining: number
  has_payment_password: boolean
}

export interface MembershipPlan {
  tier: 'vip' | 'svip'
  name: string
  price_cents: number
  duration_days: number
  generation_credits: number
}

export interface AccountData {
  account: AccountSummary
  plans: MembershipPlan[]
}

export interface LedgerEntry {
  id: string
  kind: 'cdk_recharge' | 'membership_payment'
  amount_cents: number
  balance_after_cents: number
  reference_type: string
  created_at: string
}

export interface UserSettings {
  default_aspect_ratio: AspectRatio
  default_duration_seconds: number
  default_bgm_volume: number
  preferred_voice: MimoVoiceId
}

export interface VoiceOption {
  id: MimoVoiceId
  name: string
  language: '中文' | '英文' | '因部署集群而异'
  gender: '女性' | '男性' | '因部署集群而异'
}

export interface Capabilities {
  provider_mode: ProviderMode
  external_requests_enabled: boolean
  voices: VoiceOption[]
}

export interface ScriptSegment {
  id: string
  order: number
  location: string
  narration: string
  narration_char_count: number
  visual_intent: string
  emotion: string
  audio_cue: string
  speed_tier: '慢速' | '中速' | '快速' | null
  speed_value: number | null
  estimated_duration_seconds: number
}

export interface ScriptArtifact {
  version: number
  title: string
  platform: string
  aspect_ratio: AspectRatio
  total_duration_seconds: number
  hook: string
  segments: ScriptSegment[]
  closing: string
  bgm_query: string
}

export interface StoryboardShot {
  id: string
  segment_id: string
  order: number
  narration: string
  visual_description: string
  material_query: string
  keywords_en: string[]
  keywords_cn: string[]
  shot_type: 'wide' | 'medium' | 'close-up'
  mood: string
  transition_in: 'cut' | 'dissolve' | 'fade' | 'wipe'
  audio_note: string
  orientation: AspectRatio
  estimated_duration_seconds: number
}

export interface StoryboardArtifact {
  version: number
  total_duration_seconds: number
  total_shots: number
  shots: StoryboardShot[]
}

export interface TaskProgress {
  current_step: string
  completed_steps: number
  total_steps: 12
}

export interface SafeTaskError {
  code: string
  message: string
  retryable: boolean
  failed_stage: string
}

export interface TaskSummary {
  id: string
  topic: string
  target_duration_seconds: number
  aspect_ratio: AspectRatio
  voice_id: MimoVoiceId
  provider_mode: ProviderMode
  status: TaskStatus
  progress: TaskProgress
  created_at: string
  updated_at: string
  preview_ready: boolean
  export_ready: boolean
  cover_url: string | null
  error: SafeTaskError | null
}

export type PendingReview =
  | {
      kind: 'script'
      version: number
      allowed_actions: ReviewAction[]
      script: ScriptArtifact
    }
  | {
      kind: 'storyboard'
      version: number
      allowed_actions: ReviewAction[]
      storyboard: StoryboardArtifact
    }
  | {
      kind: 'bgm'
      version: number
      allowed_actions: BgmAction[]
      suggested_query: string
      default_volume: number
      uploaded_track: BgmTrack | null
    }

export interface TaskDetail extends TaskSummary {
  thread_id: string
  script: ScriptArtifact | null
  storyboard: StoryboardArtifact | null
  pending_review: PendingReview | null
  preview_url: string | null
  export_url: string | null
  final_duration_seconds: number | null
  bgm_added: boolean | null
}

export interface TaskPage {
  items: TaskSummary[]
  page: number
  page_size: number
  total: number
  pages: number
}

export interface CommunityAuthor {
  id: string
  name: string
  avatar_url: string | null
}

export interface CommunityPost {
  id: string
  task_id: string
  title: string
  description: string
  author: CommunityAuthor
  aspect_ratio: AspectRatio
  duration_seconds: number
  prompt_public: boolean
  generation_prompt: string | null
  tags: string[]
  created_at: string
  comment_count: number
  share_count: number
  favorite_count: number
  like_count: number
  favorited: boolean
  liked: boolean
  owned_by_me: boolean
  video_url: string
  cover_url: string
}

export interface TaskStats {
  total: number
  completed: number
  failed: number
  in_progress: number
  awaiting_review: number
  total_duration_seconds: number
}

export interface PublicUserProfile {
  id: string
  nickname: string | null
  avatar_url: string | null
  created_at: string
  follower_count: number
  following_count: number
  post_count: number
  is_following: boolean
  is_self: boolean
}

export interface CommunityComment {
  id: string
  parent_id: string | null
  content: string
  author: CommunityAuthor
  created_at: string
  like_count: number
  liked: boolean
  can_delete: boolean
}

export interface CommunityPostPage {
  items: CommunityPost[]
  page: number
  page_size: number
  total: number
  pages: number
}

export interface ApiErrorPayload {
  error: {
    code: string
    message: string
    request_id: string
    fields?: Array<{ field: string; message: string }>
    retryable: boolean
  }
}

export type AdSlotName = 'history' | 'community' | 'new_task' | 'task_detail'
export type AdPlacement = 'auto' | AdSlotName

export interface AdCreative {
  id: string
  title: string
  link_url: string
  placement: AdPlacement
  image_url: string
  image_media_type: 'image/jpeg' | 'image/png' | 'image/gif'
}
