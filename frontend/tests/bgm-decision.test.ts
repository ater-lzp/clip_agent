import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import BgmDecisionPanel from '../src/components/BgmDecisionPanel.vue'
import type { PendingReview } from '../src/types/domain'

const review: Extract<PendingReview, { kind: 'bgm' }> = {
  kind: 'bgm',
  version: 2,
  allowed_actions: ['no_add', 'add'],
  suggested_query: '轻快 科技',
  default_volume: 0.2,
}

describe('BgmDecisionPanel', () => {
  it('emits both documented branches with the correct volume unit', async () => {
    const wrapper = mount(BgmDecisionPanel, { props: { review, busy: false } })
    await wrapper.findAll('button')[0].trigger('click')
    expect(wrapper.emitted('decide')?.[0]).toEqual([{ action: 'no_add', volume: null }])

    await wrapper.get('input[type="range"]').setValue('0.35')
    await wrapper.findAll('button')[1].trigger('click')
    expect(wrapper.emitted('decide')?.[1]).toEqual([{ action: 'add', volume: 0.35 }])
  })

  it('prevents duplicate submission while busy', () => {
    const wrapper = mount(BgmDecisionPanel, { props: { review, busy: true } })
    expect(wrapper.findAll('button').every((button) => button.attributes('disabled') !== undefined)).toBe(true)
  })
})
