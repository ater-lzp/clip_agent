import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { request } from '../src/api'
import { yuanToCents } from '../src/utils'
import CdksView from '../src/views/CdksView.vue'

vi.mock('../src/api', () => ({ request: vi.fn() }))

describe('CDK management', () => {
  beforeEach(() => {
    vi.mocked(request).mockReset()
    vi.mocked(request)
      .mockResolvedValueOnce({ items: [], page: 1, page_size: 30, total: 0, pages: 0 })
      .mockResolvedValueOnce({ items: [{ code: 'CLIP-TEST-TEST-TEST-TEST', amount_cents: 1234 }] })
      .mockResolvedValueOnce({ items: [], page: 1, page_size: 30, total: 0, pages: 0 })
  })

  it('converts yuan input to integer cents before creating codes', async () => {
    const wrapper = mount(CdksView)
    await flushPromises()
    await wrapper.get('[data-testid="cdk-amount-yuan"]').setValue('12.34')
    await wrapper.get('[data-testid="cdk-form"]').trigger('submit')
    await flushPromises()

    expect(request).toHaveBeenNthCalledWith(2, '/api/v1/admin/cdks', {
      method: 'POST', body: { amount_cents: 1234, count: 1 },
    })
    expect(wrapper.text()).toContain('¥12.34')
  })

  it('rejects invalid yuan denominations', () => {
    expect(yuanToCents(0.01)).toBe(1)
    expect(yuanToCents(10000)).toBe(1_000_000)
    expect(() => yuanToCents(0)).toThrow('面额')
  })
})
