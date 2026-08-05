import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { request } from '../src/api'
import AdsView from '../src/views/AdsView.vue'

vi.mock('../src/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../src/api')>()
  return { ...actual, request: vi.fn(), absoluteUrl: (path: string) => path }
})

vi.mock('../src/components/PaginationBar.vue', () => ({ default: { template: '<div />' } }))

describe('AdsView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.stubGlobal('URL', { ...URL, createObjectURL: vi.fn(() => 'blob:preview'), revokeObjectURL: vi.fn() })
    vi.mocked(request).mockResolvedValue({ items: [], page: 1, page_size: 20, total: 0, pages: 0 })
  })

  it('uploads an ad as multipart form data', async () => {
    const wrapper = mount(AdsView)
    await flushPromises()
    await wrapper.get('input[placeholder="用于展示和后台识别"]').setValue('测试广告')
    await wrapper.get('input[placeholder="https://example.com/landing"]').setValue('https://example.com')
    const file = new File(['GIF89a'], 'creative.gif', { type: 'image/gif' })
    Object.defineProperty(wrapper.get('input[type="file"]').element, 'files', { value: [file] })
    await wrapper.get('input[type="file"]').trigger('change')
    vi.mocked(request).mockResolvedValueOnce({ id: 'ad-1' })
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    const upload = vi.mocked(request).mock.calls.find((call) => call[0] === '/api/v1/admin/ads')
    expect(upload?.[1]?.method).toBe('POST')
    expect(upload?.[1]?.body).toBeInstanceOf(FormData)
    expect((upload?.[1]?.body as FormData).get('placement')).toBe('auto')
  })
})
