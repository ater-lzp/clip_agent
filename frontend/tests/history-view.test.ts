import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { tasksApi } from '../src/api'
import type { TaskDetail, TaskPage } from '../src/types/domain'
import HistoryView from '../src/views/HistoryView.vue'

vi.mock('../src/api', () => ({
  tasksApi: {
    list: vi.fn(),
    get: vi.fn(),
  },
}))

const detail: TaskDetail = {
  id: 'task-01',
  thread_id: 'thread-01',
  topic: '海洋为什么重要',
  target_duration_seconds: 60,
  aspect_ratio: '9:16',
  voice_id: '冰糖',
  provider_mode: 'real',
  status: 'completed',
  progress: { current_step: '已完成', completed_steps: 12, total_steps: 12 },
  created_at: '2026-08-03T01:00:00Z',
  updated_at: '2026-08-03T02:00:00Z',
  preview_ready: true,
  export_ready: true,
  error: null,
  pending_review: null,
  preview_url: '/api/v1/tasks/task-01/preview',
  export_url: '/api/v1/tasks/task-01/export',
  final_duration_seconds: 60.2,
  bgm_added: false,
  script: {
    version: 1,
    title: '海洋的价值',
    platform: '抖音',
    aspect_ratio: '9:16',
    total_duration_seconds: 60,
    hook: '开场口播',
    closing: '结尾口播',
    bgm_query: 'calm ocean',
    segments: [
      {
        id: 'segment-01',
        order: 1,
        location: '海边 / 外 / 日间',
        narration: '海洋维系着地球生命。',
        narration_char_count: 10,
        visual_intent: '海面与鱼群',
        emotion: '沉稳清晰，语速自然',
        audio_cue: '海浪声',
        speed_tier: '中速',
        speed_value: 4.2,
        estimated_duration_seconds: 3,
      },
    ],
  },
  storyboard: {
    version: 1,
    total_duration_seconds: 60,
    total_shots: 1,
    shots: [
      {
        id: 'shot-01',
        segment_id: 'segment-01',
        order: 1,
        narration: '海洋维系着地球生命。',
        visual_description: '航拍海面与游动鱼群',
        material_query: 'ocean fish aerial',
        keywords_en: ['ocean', 'fish', 'aerial'],
        keywords_cn: ['海洋', '鱼群', '航拍'],
        shot_type: 'wide',
        mood: '开阔',
        transition_in: 'fade',
        audio_note: '海浪声',
        orientation: '9:16',
        estimated_duration_seconds: 3,
      },
    ],
  },
}

const page: TaskPage = {
  items: [detail],
  page: 1,
  page_size: 20,
  total: 1,
  pages: 1,
}

describe('HistoryView', () => {
  beforeEach(() => {
    vi.mocked(tasksApi.list).mockResolvedValue(page)
    vi.mocked(tasksApi.get).mockResolvedValue(detail)
  })

  it('loads and expands the script and storyboard archive for a history record', async () => {
    const wrapper = mount(HistoryView, {
      global: {
        stubs: { RouterLink: { template: '<a><slot /></a>' } },
      },
    })
    await flushPromises()

    expect(wrapper.text()).toContain('查看剧本与分镜规划')
    expect(wrapper.text()).not.toContain('沉稳清晰，语速自然')

    await wrapper.get('.archive-toggle').trigger('click')
    await flushPromises()

    expect(tasksApi.get).toHaveBeenCalledWith('task-01')
    expect(wrapper.text()).toContain('剧本')
    expect(wrapper.text()).toContain('海洋维系着地球生命。')
    expect(wrapper.text()).toContain('沉稳清晰，语速自然')
    expect(wrapper.text()).toContain('分镜规划')
    expect(wrapper.text()).toContain('ocean fish aerial')
    expect(wrapper.text()).toContain('航拍')
  })
})
