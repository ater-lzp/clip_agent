import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import ReviewPanel from '../src/components/ReviewPanel.vue'
import type { PendingReview } from '../src/types/domain'

const review: Extract<PendingReview, { kind: 'script' }> = {
  kind: 'script',
  version: 1,
  allowed_actions: ['approve', 'reject'],
  script: {
    version: 1,
    title: '测试剧本',
    platform: '抖音',
    aspect_ratio: '9:16',
    total_duration_seconds: 5,
    hook: '开场',
    closing: '结尾',
    bgm_query: '轻快',
    segments: [
      {
        id: 'segment-01',
        order: 1,
        location: '演播室 / 内 / 日间',
        narration: '第一段口播',
        narration_char_count: 6,
        visual_intent: '第一段画面',
        emotion: '自然清晰',
        audio_cue: '无环境音',
        speed_tier: '中速',
        speed_value: 4.5,
        estimated_duration_seconds: 5,
      },
    ],
  },
}

const storyboardReview: Extract<PendingReview, { kind: 'storyboard' }> = {
  kind: 'storyboard',
  version: 1,
  allowed_actions: ['approve', 'reject'],
  storyboard: {
    version: 1,
    total_duration_seconds: 5,
    total_shots: 1,
    shots: [
      {
        id: 'shot-01',
        segment_id: 'segment-01',
        order: 1,
        narration: '第一段口播',
        visual_description: '海浪拍向礁石，镜头缓慢推进',
        material_query: 'ocean waves rocks',
        keywords_en: ['ocean', 'waves', 'rocks'],
        keywords_cn: ['海洋', '海浪', '礁石'],
        shot_type: 'wide',
        mood: '开阔',
        transition_in: 'fade',
        audio_note: '保留海浪声',
        orientation: '9:16',
        estimated_duration_seconds: 5,
      },
    ],
  },
}

describe('ReviewPanel', () => {
  it('shows every script scene narration and emotion instruction explicitly', () => {
    const wrapper = mount(ReviewPanel, { props: { review, busy: false } })
    expect(wrapper.text()).toContain('口播稿')
    expect(wrapper.text()).toContain('第一段口播')
    expect(wrapper.text()).toContain('情绪指令')
    expect(wrapper.text()).toContain('自然清晰')
  })

  it('shows the Pexels query and both keyword sets for every storyboard shot', () => {
    const wrapper = mount(ReviewPanel, { props: { review: storyboardReview, busy: false } })
    expect(wrapper.text()).toContain('Pexels 检索短语')
    expect(wrapper.text()).toContain('ocean waves rocks')
    expect(wrapper.text()).toContain('英文关键词')
    expect(wrapper.text()).toContain('ocean')
    expect(wrapper.text()).toContain('中文关键词')
    expect(wrapper.text()).toContain('礁石')
  })

  it('requires feedback for rejection and emits explicit actions', async () => {
    const wrapper = mount(ReviewPanel, { props: { review, busy: false } })
    const buttons = wrapper.findAll('button')
    await buttons[0].trigger('click')
    expect(wrapper.text()).toContain('退回时请说明')
    expect(wrapper.emitted('submit')).toBeUndefined()

    await wrapper.get('textarea').setValue('缩短开场')
    await buttons[0].trigger('click')
    expect(wrapper.emitted('submit')?.[0]).toEqual([{ action: 'reject', feedback: '缩短开场' }])

    await buttons[1].trigger('click')
    expect(wrapper.emitted('submit')?.[1]).toEqual([{ action: 'approve', feedback: null }])
  })

  it('disables every submit control while a request is in flight', () => {
    const wrapper = mount(ReviewPanel, { props: { review, busy: true } })
    expect(wrapper.findAll('button').every((button) => button.attributes('disabled') !== undefined)).toBe(true)
    expect(wrapper.get('textarea').attributes('disabled')).not.toBeUndefined()
  })
})
