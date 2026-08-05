import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { tasksApi } from '../src/api'
import type { TaskDetail, TaskPage } from '../src/types/domain'
import HistoryView from '../src/views/HistoryView.vue'

const { pushMock } = vi.hoisted(() => ({ pushMock: vi.fn() }))

vi.mock('vue-router', () => ({
  useRouter: () => ({ push: pushMock }),
}))

vi.mock('../src/api', () => ({
  tasksApi: {
    list: vi.fn(),
    stats: vi.fn(),
    get: vi.fn(),
    duplicate: vi.fn(),
    bulkDelete: vi.fn(),
    coverUrl: vi.fn((path: string) => path),
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
  cover_url: '/api/v1/tasks/task-01/cover',
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
    vi.clearAllMocks()
    pushMock.mockReset()
    vi.mocked(tasksApi.list).mockResolvedValue(page)
    vi.mocked(tasksApi.get).mockResolvedValue(detail)
    vi.mocked(tasksApi.stats).mockResolvedValue({
      total: 1,
      completed: 1,
      failed: 0,
      in_progress: 0,
      awaiting_review: 0,
      total_duration_seconds: 60.2,
    })
    vi.mocked(tasksApi.duplicate).mockResolvedValue(detail)
    vi.mocked(tasksApi.bulkDelete).mockResolvedValue({ deleted_count: 1 })
  })

  it('loads stats and expands the script and storyboard archive for a history record', async () => {
    const wrapper = mount(HistoryView, {
      global: {
        stubs: { RouterLink: { template: '<a><slot /></a>' } },
      },
    })
    await flushPromises()

    expect(tasksApi.stats).toHaveBeenCalledTimes(1)
    expect(wrapper.text()).toContain('总任务')
    expect(tasksApi.list).toHaveBeenCalledWith(1, undefined, 40, '')
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

  it('passes the selected status filter and search query to the list API', async () => {
    const wrapper = mount(HistoryView, {
      global: {
        stubs: { RouterLink: { template: '<a><slot /></a>' } },
      },
    })
    await flushPromises()

    const failedTab = wrapper.findAll('.history-tabs button').find((button) => button.text() === '失败')
    expect(failedTab).toBeTruthy()
    await failedTab!.trigger('click')
    await flushPromises()
    expect(tasksApi.list).toHaveBeenLastCalledWith(1, 'failed', 40, '')

    const search = wrapper.get('.history-search')
    await search.setValue('猫咪')
    await new Promise((resolve) => setTimeout(resolve, 450))
    expect(tasksApi.list).toHaveBeenLastCalledWith(1, 'failed', 40, '猫咪')

    const generatingTab = wrapper.findAll('.history-tabs button').find((button) => button.text() === '生成中')
    expect(generatingTab).toBeTruthy()
    await generatingTab!.trigger('click')
    await flushPromises()
    expect(tasksApi.list).toHaveBeenLastCalledWith(1, 'in_progress', 40, '猫咪')
  })

  it('confirms and duplicates a completed task from the history card', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    const wrapper = mount(HistoryView, {
      global: {
        stubs: { RouterLink: { template: '<a><slot /></a>' } },
      },
    })
    await flushPromises()

    const duplicateButton = wrapper.findAll('.card-shortcuts button').find((button) => button.text().includes('再次创作'))
    expect(duplicateButton).toBeTruthy()
    await duplicateButton!.trigger('click')
    await flushPromises()

    expect(tasksApi.duplicate).toHaveBeenCalledTimes(1)
    expect(tasksApi.duplicate).toHaveBeenCalledWith('task-01', expect.any(String))
    expect(pushMock).toHaveBeenCalledWith('/tasks/task-01')
  })

  it('selects all records across pagination and deletes them after confirmation', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    const wrapper = mount(HistoryView, {
      global: { stubs: { RouterLink: { template: '<a><slot /></a>' } } },
    })
    await flushPromises()

    await wrapper.get('.select-all-records input').setValue(true)
    expect(wrapper.text()).toContain('已选 1 条')
    await wrapper.get('.bulk-actions button').trigger('click')
    await flushPromises()

    expect(tasksApi.bulkDelete).toHaveBeenCalledWith({ mode: 'all', task_ids: [] })
    expect(tasksApi.list).toHaveBeenCalledTimes(2)
  })
})
