import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import SettingsView from '../src/views/SettingsView.vue'

const mocks = vi.hoisted(() => ({
  user: {
    value: {
      id: 'user-01',
      email: 'creator@example.com',
      nickname: '创作者',
      avatar_url: '/api/v1/users/user-01/avatar',
      role: 'user' as const,
      created_at: '2026-08-05T00:00:00Z',
    },
  },
  setUser: vi.fn(),
  profileUpdate: vi.fn(),
  uploadAvatar: vi.fn(),
}))

vi.mock('vue-router', () => ({
  useRouter: () => ({ push: vi.fn() }),
}))

vi.mock('../src/composables/useSession', () => ({
  useSession: () => ({
    user: mocks.user,
    setUser: mocks.setUser,
    clear: vi.fn(),
  }),
}))

vi.mock('../src/api', () => ({
  capabilitiesApi: {
    get: vi.fn().mockResolvedValue({ provider_mode: 'fake', voices: [] }),
  },
  settingsApi: {
    get: vi.fn().mockResolvedValue({
      default_aspect_ratio: '16:9',
      default_duration_seconds: 60,
      default_bgm_volume: 0.2,
      preferred_voice: 'mimo_default',
    }),
    update: vi.fn(),
  },
  profileApi: {
    update: mocks.profileUpdate,
    uploadAvatar: mocks.uploadAvatar,
    changePassword: vi.fn(),
  },
}))

const stableUser = {
  id: 'user-01',
  email: 'creator@example.com',
  nickname: '创作者',
  avatar_url: '/api/v1/users/user-01/avatar',
  role: 'user' as const,
  created_at: '2026-08-05T00:00:00Z',
}

describe('SettingsView avatar upload', () => {
  beforeEach(() => {
    mocks.user.value = { ...stableUser }
    mocks.setUser.mockReset()
    mocks.setUser.mockImplementation((user) => {
      mocks.user.value = user
    })
    mocks.profileUpdate.mockReset().mockResolvedValue({ ...stableUser })
    mocks.uploadAvatar.mockReset().mockResolvedValue({ ...stableUser })
  })

  it('clears the native input and cache-busts every replacement avatar', async () => {
    const wrapper = mount(SettingsView)
    await flushPromises()

    const input = wrapper.get<HTMLInputElement>('#avatar')
    const file = new File(['avatar'], 'avatar.png', { type: 'image/png' })

    Object.defineProperty(input.element, 'files', { configurable: true, value: [file] })
    await input.trigger('change')
    await wrapper.get('form.settings-form').trigger('submit')
    await flushPromises()

    expect(mocks.uploadAvatar).toHaveBeenCalledTimes(1)
    const firstUpdatedUser = mocks.setUser.mock.calls[mocks.setUser.mock.calls.length - 1][0]
    expect(firstUpdatedUser.avatar_url).toMatch(
      /^\/api\/v1\/users\/user-01\/avatar\?v=\d+-\d+$/,
    )
    expect(input.element.value).toBe('')

    Object.defineProperty(input.element, 'value', {
      configurable: true,
      writable: true,
      value: 'C:\\fakepath\\avatar.png',
    })
    await input.trigger('click')
    expect(input.element.value).toBe('')

    Object.defineProperty(input.element, 'files', { configurable: true, value: [file] })
    await input.trigger('change')
    await wrapper.get('form.settings-form').trigger('submit')
    await flushPromises()

    expect(mocks.uploadAvatar).toHaveBeenCalledTimes(2)
    const secondUpdatedUser = mocks.setUser.mock.calls[mocks.setUser.mock.calls.length - 1][0]
    expect(secondUpdatedUser.avatar_url).toMatch(
      /^\/api\/v1\/users\/user-01\/avatar\?v=\d+-\d+$/,
    )
    expect(secondUpdatedUser.avatar_url).not.toBe(firstUpdatedUser.avatar_url)
  })
})
