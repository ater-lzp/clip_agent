import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { adsApi } from '../src/api'
import AdSlot from '../src/components/AdSlot.vue'

vi.mock('../src/api', () => ({
  adsApi: {
    select: vi.fn(),
    record: vi.fn(),
    imageUrl: vi.fn((path: string) => path),
  },
}))

const creative = {
  id: '019fc39a-7785-7f10-b92b-a89da9ae4039',
  title: '免费用户推广',
  link_url: 'https://example.com/landing',
  placement: 'auto' as const,
  image_url: '/api/v1/ads/019fc39a-7785-7f10-b92b-a89da9ae4039/image',
  image_media_type: 'image/gif' as const,
}

describe('AdSlot', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    sessionStorage.clear()
    vi.mocked(adsApi.record).mockResolvedValue(undefined)
  })

  it('shows a free-user ad, records events and supports closing it', async () => {
    vi.mocked(adsApi.select).mockResolvedValue({ item: creative })
    const wrapper = mount(AdSlot, { props: { slot: 'history' } })
    await flushPromises()
    expect(wrapper.get('img').attributes('src')).toBe(creative.image_url)
    expect(wrapper.get('a').attributes('rel')).toContain('sponsored')
    expect(adsApi.record).toHaveBeenCalledWith(creative.id, 'impression')
    await wrapper.get('a').trigger('click')
    expect(adsApi.record).toHaveBeenCalledWith(creative.id, 'click')
    await wrapper.get('button[aria-label="关闭广告"]').trigger('click')
    expect(wrapper.find('.ad-slot').exists()).toBe(false)
    expect(sessionStorage.getItem(`clip:dismissed-ad:${creative.id}`)).toBe('1')
  })

  it('renders nothing when the service returns no ad', async () => {
    vi.mocked(adsApi.select).mockResolvedValue({ item: null })
    const wrapper = mount(AdSlot, { props: { slot: 'community' } })
    await flushPromises()
    expect(wrapper.find('.ad-slot').exists()).toBe(false)
  })
})
