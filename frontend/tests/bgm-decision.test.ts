import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { tasksApi } from '../src/api'
import BgmDecisionPanel from '../src/components/BgmDecisionPanel.vue'
import type { PendingReview } from '../src/types/domain'

const review: Extract<PendingReview, { kind: 'bgm' }> = {
  kind: 'bgm',
  version: 2,
  allowed_actions: ['no_add', 'add'],
  suggested_query: '轻快 科技',
  default_volume: 0.2,
  uploaded_track: null,
}

vi.mock('../src/api', () => ({
  tasksApi: {
    listBgms: vi.fn(),
    uploadBgm: vi.fn(),
    previewUrl: vi.fn((path: string) => path),
  },
}))

describe('BgmDecisionPanel', () => {
  beforeEach(() => {
    vi.mocked(tasksApi.listBgms).mockClear()
    vi.mocked(tasksApi.listBgms).mockResolvedValue({
      items: [{
        id: 'library:test-track-0000001',
        name: '轻快',
        source: 'library',
        duration_seconds: 60,
        preview_url: '/audio',
      }],
    })
  })

  it('emits both documented branches with the correct volume unit', async () => {
    const wrapper = mount(BgmDecisionPanel, { props: { taskId: 'task-1', review, busy: false } })
    await wrapper.get('[data-testid="skip-bgm"]').trigger('click')
    expect(wrapper.emitted('decide')?.[0]).toEqual([{ action: 'no_add', volume: null, track_id: null }])

    await wrapper.get('[data-testid="open-bgm-library"]').trigger('click')
    await flushPromises()
    expect(wrapper.get('[role="dialog"]').text()).toContain('项目曲库')
    await wrapper.get('input[type="range"]').setValue('0.35')
    await wrapper.get('[data-testid="confirm-bgm"]').trigger('click')
    expect(wrapper.emitted('decide')?.[1]).toEqual([
      { action: 'add', volume: 0.35, track_id: 'library:test-track-0000001' },
    ])
  })

  it('prevents duplicate submission while busy', () => {
    const wrapper = mount(BgmDecisionPanel, { props: { taskId: 'task-1', review, busy: true } })
    expect(wrapper.findAll('button').every((button) => button.attributes('disabled') !== undefined)).toBe(true)
  })

  it('loads the project library only after opening the modal', async () => {
    const wrapper = mount(BgmDecisionPanel, { props: { taskId: 'task-1', review, busy: false } })
    expect(tasksApi.listBgms).not.toHaveBeenCalled()
    await wrapper.get('[data-testid="open-bgm-library"]').trigger('click')
    await flushPromises()
    expect(tasksApi.listBgms).toHaveBeenCalledOnce()
  })
})
