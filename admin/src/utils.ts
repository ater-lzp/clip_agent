export function money(cents: number): string {
  return `¥${(cents / 100).toFixed(2)}`
}

export function yuanToCents(yuan: number): number {
  if (!Number.isFinite(yuan)) throw new Error('请输入有效面额')
  const cents = Math.round((yuan + Number.EPSILON) * 100)
  if (cents < 1 || cents > 1_000_000) throw new Error('面额必须在 0.01 至 10000 元之间')
  return cents
}

export function formatDate(value: string | null): string {
  return value
    ? new Intl.DateTimeFormat('zh-CN', {
        dateStyle: 'medium',
        timeStyle: 'short',
        timeZone: 'Asia/Shanghai',
      }).format(new Date(value))
    : '—'
}

export function formatDuration(seconds: number | null): string {
  if (seconds === null) return '—'
  const rounded = Math.max(0, Math.round(seconds))
  const minutes = Math.floor(rounded / 60)
  return `${minutes}:${String(rounded % 60).padStart(2, '0')}`
}

export function statusLabel(status: string): string {
  const labels: Record<string, string> = {
    queued: '排队中', generating_script: '生成剧本', awaiting_script_review: '待审剧本',
    generating_storyboard: '生成分镜', awaiting_storyboard_review: '待审分镜',
    synthesizing_audio: '合成配音', building_timeline: '建立时间轴',
    fetching_assets: '获取素材', aligning_timeline: '音画对齐', rendering_preview: '渲染预览',
    awaiting_bgm_decision: '待选 BGM', processing_bgm: '处理 BGM', completed: '已完成', failed: '失败',
  }
  return labels[status] ?? status
}
