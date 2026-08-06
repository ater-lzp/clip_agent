import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { request } from '../src/api'
import OverviewView from '../src/views/OverviewView.vue'

vi.mock('../src/api', async () => {
  const actual = await vi.importActual<typeof import('../src/api')>('../src/api')
  return { ...actual, request: vi.fn() }
})

const dashboard = {
  user_total: 10,
  active_users: 8,
  vip_users: 2,
  svip_users: 1,
  task_total: 20,
  completed_tasks: 12,
  failed_tasks: 2,
  in_progress_tasks: 4,
  awaiting_tasks: 2,
  today_users: 3,
  membership_revenue_cents: 10980,
  cdk_total: 5,
  cdk_used: 2,
}

describe('OverviewView', () => {
  beforeEach(() => {
    vi.mocked(request).mockReset().mockImplementation((path: string) => {
      if (path === '/api/v1/admin/dashboard') return Promise.resolve(dashboard)
      return Promise.resolve({ items: [], page: 1, page_size: 5, total: 0, pages: 0 })
    })
  })

  it('presents operational data as accessible charts', async () => {
    const wrapper = mount(OverviewView, {
      global: {
        stubs: {
          RouterLink: { template: '<a><slot /></a>' },
        },
      },
    })
    await flushPromises()

    expect(wrapper.findAll('.overview-kpis article')).toHaveLength(3)
    expect(wrapper.get('.donut-chart').attributes('style')).toContain('conic-gradient')
    expect(wrapper.get('.donut-chart').attributes('aria-label')).toBe('任务总数 20')
    expect(wrapper.findAll('.bar-row')).toHaveLength(3)
    expect(wrapper.findAll('.mini-ring')).toHaveLength(2)
    expect(wrapper.text()).toContain('用户启用率')
    expect(wrapper.text()).toContain('CDK 兑换率')
  })
})
