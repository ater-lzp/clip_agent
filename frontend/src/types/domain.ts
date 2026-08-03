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

export interface User {
  id: string
  email: string
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

export interface ApiErrorPayload {
  error: {
    code: string
    message: string
    request_id: string
    fields?: Array<{ field: string; message: string }>
    retryable: boolean
  }
}
