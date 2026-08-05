import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { accountApi } from '../src/api'
import AccountView from '../src/views/AccountView.vue'

vi.mock('../src/api', () => ({
  accountApi: {
    get: vi.fn().mockResolvedValue({
      account: { membership_tier: 'free', membership_expires_at: null, balance_cents: 0, generation_quota: 5, generations_used: 0, generations_remaining: 5, has_payment_password: false },
      plans: [{ tier: 'vip', name: 'VIP', price_cents: 2990, duration_days: 30, generation_credits: 30 }],
    }),
    ledger: vi.fn().mockResolvedValue({ items: [] }),
    redeemCdk: vi.fn(), setPaymentPassword: vi.fn(), purchase: vi.fn(),
  },
}))

describe('AccountView', () => {
  beforeEach(() => {
    vi.mocked(accountApi.get).mockClear()
    vi.mocked(accountApi.purchase).mockClear()
  })

  it('shows free quota and safe recharge controls', async () => {
    const wrapper = mount(AccountView)
    await vi.waitFor(() => expect(wrapper.text()).toContain('剩余生成次数'))
    expect(wrapper.text()).toContain('5')
    expect(wrapper.text()).toContain('CDK 充值')
    expect(wrapper.text()).toContain('设置支付密码')
    expect(wrapper.text()).toContain('VIP')
    expect(wrapper.find('#purchase-password').exists()).toBe(false)

    await wrapper.get('[data-testid="purchase-vip"]').trigger('click')
    await flushPromises()
    expect(wrapper.get('[role="dialog"]').text()).toContain('确认购买 VIP')
    expect(wrapper.find('#purchase-password').exists()).toBe(true)
    expect(wrapper.get('[data-testid="confirm-purchase"]').attributes('disabled')).toBeDefined()
  })

  it('submits the balance purchase only from the payment dialog', async () => {
    vi.mocked(accountApi.get).mockResolvedValueOnce({
      account: { membership_tier: 'free', membership_expires_at: null, balance_cents: 5000, generation_quota: 5, generations_used: 0, generations_remaining: 5, has_payment_password: true },
      plans: [{ tier: 'vip', name: 'VIP', price_cents: 2990, duration_days: 30, generation_credits: 30 }],
    })
    const wrapper = mount(AccountView)
    await vi.waitFor(() => expect(wrapper.text()).toContain('立即购买'))
    expect(accountApi.purchase).not.toHaveBeenCalled()

    await wrapper.get('[data-testid="purchase-vip"]').trigger('click')
    await wrapper.get('#purchase-password').setValue('123456')
    await wrapper.get('[role="dialog"] form').trigger('submit')
    await flushPromises()

    expect(accountApi.purchase).toHaveBeenCalledWith('vip', '123456', expect.any(String))
  })
})
