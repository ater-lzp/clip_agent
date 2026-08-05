import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { request } from '../src/api'
import UsersView from '../src/views/UsersView.vue'

vi.mock('../src/api', () => ({ request: vi.fn() }))

describe('UsersView', () => {
  beforeEach(() => {
    vi.mocked(request).mockReset()
    vi.mocked(request).mockResolvedValueOnce({
      items: [{
        id: 'user-1', email: 'member@example.com', role: 'user', is_active: true,
        membership_tier: 'free', balance_cents: 0, generation_quota: 5,
        generations_used: 0, generations_remaining: 5, created_at: '2026-08-04T00:00:00Z',
      }],
    })
  })

  it('allows an administrator to reset a user password', async () => {
    vi.mocked(request).mockResolvedValueOnce(undefined)
    const wrapper = mount(UsersView)
    await flushPromises()

    await wrapper.get('[data-testid="reset-password-user-1"]').trigger('click')
    const passwordInputs = wrapper.findAll('input[autocomplete="new-password"]')
    await passwordInputs[0].setValue('NewPassword1')
    await passwordInputs[1].setValue('NewPassword1')
    await wrapper.get('[data-testid="password-reset-form"]').trigger('submit')
    await flushPromises()

    expect(request).toHaveBeenLastCalledWith('/api/v1/admin/users/user-1/password', {
      method: 'POST',
      body: { new_password: 'NewPassword1', confirm_password: 'NewPassword1' },
    })
    expect(wrapper.text()).toContain('原会话已失效')
  })
})
