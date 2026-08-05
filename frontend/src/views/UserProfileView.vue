<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { communityApi } from '../api'
import { ApiError, absoluteApiUrl } from '../api/client'
import type { CommunityPost, PublicUserProfile } from '../types/domain'
import { formatDate, formatDuration } from '../utils/format'

const route = useRoute()
const userId = computed(() => String(route.params.userId ?? ''))
const profile = ref<PublicUserProfile | null>(null)
const posts = ref<CommunityPost[]>([])
const loading = ref(true)
const busy = ref(false)
const errorMessage = ref('')

async function load(): Promise<void> {
  loading.value = true
  errorMessage.value = ''
  try {
    const [loadedProfile, page] = await Promise.all([
      communityApi.getUser(userId.value),
      communityApi.listByUser(userId.value),
    ])
    profile.value = loadedProfile
    posts.value = page.items
  } catch (error) {
    errorMessage.value = error instanceof ApiError ? error.message : '用户主页加载失败'
  } finally {
    loading.value = false
  }
}

async function toggleFollow(): Promise<void> {
  if (busy.value || !profile.value) return
  busy.value = true
  try {
    const result = await communityApi.follow(profile.value.id)
    profile.value.is_following = result.following
    profile.value.follower_count = Math.max(0, profile.value.follower_count + (result.following ? 1 : -1))
  } catch (error) {
    errorMessage.value = error instanceof ApiError ? error.message : '操作失败'
  } finally {
    busy.value = false
  }
}

onMounted(load)
watch(userId, load)
</script>

<template>
  <div class="page narrow-page">
    <div v-if="loading" class="state-card"><span class="spinner"></span><p>正在加载用户主页…</p></div>
    <div v-else-if="!profile" class="state-card error-state"><h2>无法打开用户主页</h2><p>{{ errorMessage }}</p></div>
    <template v-else>
      <RouterLink class="back-link" to="/community">← 返回社区</RouterLink>
      <section class="panel profile-card">
        <div class="profile-header">
          <img v-if="profile.avatar_url" class="profile-avatar" :src="absoluteApiUrl(profile.avatar_url)" alt="用户头像" />
          <span v-else class="profile-avatar avatar-placeholder" aria-hidden="true">{{ (profile.nickname || 'U').slice(0, 1).toUpperCase() }}</span>
          <div class="profile-copy">
            <h1>{{ profile.nickname || '未设置昵称' }}</h1>
            <p>加入于 {{ formatDate(profile.created_at) }}</p>
          </div>
          <button
            v-if="!profile.is_self"
            class="button"
            :class="profile.is_following ? 'secondary' : 'primary'"
            type="button"
            :disabled="busy"
            @click="toggleFollow"
          >{{ profile.is_following ? '已关注' : '＋ 关注' }}</button>
        </div>
        <div class="profile-stats">
          <div><strong>{{ profile.post_count }}</strong><span>作品</span></div>
          <div><strong>{{ profile.follower_count }}</strong><span>粉丝</span></div>
          <div><strong>{{ profile.following_count }}</strong><span>关注</span></div>
        </div>
      </section>

      <div class="section-heading"><div><p class="eyebrow">Works</p><h2>TA 的作品</h2></div></div>
      <p v-if="errorMessage" class="form-error" role="alert">{{ errorMessage }}</p>
      <div v-if="!posts.length" class="state-card empty-state">
        <span class="empty-glyph">✦</span><h2>还没有作品</h2><p>这个用户还没有发布任何视频。</p>
      </div>
      <section v-else class="community-grid">
        <article v-for="post in posts" :key="post.id" class="community-card">
          <RouterLink :to="`/community/posts/${post.id}`" class="community-cover"><img :src="communityApi.mediaUrl(post.cover_url)" alt="作品首帧封面" loading="lazy" /></RouterLink>
          <div class="community-card-body">
            <div class="community-author"><RouterLink :to="`/users/${post.author.id}`" class="author-link">{{ post.author.name }}</RouterLink><time>{{ formatDate(post.created_at) }}</time></div>
            <RouterLink :to="`/community/posts/${post.id}`"><h2>{{ post.title }}</h2></RouterLink>
            <p>{{ post.description || '作者没有填写作品描述。' }}</p>
            <div class="tag-row"><span v-for="tag in post.tags" :key="tag">#{{ tag }}</span></div>
            <div class="community-stats"><span>{{ formatDuration(post.duration_seconds) }}</span><span>评论 {{ post.comment_count }}</span><span>点赞 {{ post.like_count }}</span></div>
          </div>
        </article>
      </section>
    </template>
  </div>
</template>
