import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { communityApi } from '../src/api'
import type { CommunityPost, PublicUserProfile } from '../src/types/domain'
import UserProfileView from '../src/views/UserProfileView.vue'

vi.mock('../src/api', () => ({
  communityApi: {
    getUser: vi.fn(),
    listByUser: vi.fn(),
    follow: vi.fn(),
    mediaUrl: vi.fn((path: string) => path),
  },
}))

vi.mock('../src/composables/useSession', () => ({
  useSession: () => ({ user: { value: null } }),
}))

vi.mock('vue-router', () => ({
  useRoute: () => ({ params: { userId: 'user-01' } }),
}))

const profile: PublicUserProfile = {
  id: 'user-01',
  nickname: '海洋创作者',
  avatar_url: null,
  created_at: '2026-08-01T00:00:00Z',
  follower_count: 3,
  following_count: 2,
  post_count: 1,
  is_following: false,
  is_self: false,
}

const post: CommunityPost = {
  id: 'post-01',
  task_id: 'task-01',
  title: '海洋的礼物',
  description: '一段关于海洋的短片',
  author: { id: 'user-01', name: '海洋创作者', avatar_url: null },
  aspect_ratio: '16:9',
  duration_seconds: 60,
  prompt_public: false,
  generation_prompt: null,
  tags: ['海洋'],
  created_at: '2026-08-02T00:00:00Z',
  comment_count: 1,
  share_count: 0,
  favorite_count: 2,
  like_count: 5,
  favorited: false,
  liked: false,
  owned_by_me: false,
  video_url: '/api/v1/community/posts/post-01/video',
  cover_url: '/api/v1/community/posts/post-01/cover',
}

const mountOptions = {
  global: {
    stubs: { RouterLink: { template: '<a><slot /></a>' } },
  },
}

describe('UserProfileView', () => {
  beforeEach(() => {
    vi.mocked(communityApi.getUser).mockResolvedValue(profile)
    vi.mocked(communityApi.listByUser).mockResolvedValue({
      items: [post],
      page: 1,
      page_size: 20,
      total: 1,
      pages: 1,
    })
    vi.mocked(communityApi.follow).mockResolvedValue({ following: true })
  })

  it('renders profile info and the user works', async () => {
    const wrapper = mount(UserProfileView, mountOptions)
    await flushPromises()

    expect(communityApi.getUser).toHaveBeenCalledWith('user-01')
    expect(communityApi.listByUser).toHaveBeenCalledWith('user-01')
    expect(wrapper.text()).toContain('海洋创作者')
    expect(wrapper.text()).toContain('TA 的作品')
    expect(wrapper.text()).toContain('海洋的礼物')
    expect(wrapper.text()).toContain('＋ 关注')
  })

  it('toggles follow state', async () => {
    const wrapper = mount(UserProfileView, mountOptions)
    await flushPromises()

    const followButton = wrapper.findAll('button').find((button) => button.text().includes('关注'))
    expect(followButton).toBeTruthy()
    await followButton!.trigger('click')
    await flushPromises()

    expect(communityApi.follow).toHaveBeenCalledWith('user-01')
    expect(wrapper.text()).toContain('已关注')
  })
})
