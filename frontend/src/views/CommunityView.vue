<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { communityApi, tasksApi } from '../api'
import { ApiError } from '../api/client'
import type { CommunityPost, TaskSummary } from '../types/domain'
import { formatDate, formatDuration } from '../utils/format'
import AdSlot from '../components/AdSlot.vue'

type Scope = 'all' | 'mine' | 'favorites' | 'shared' | 'following'
const route = useRoute()
const router = useRouter()
const posts = ref<CommunityPost[]>([])
const completedTasks = ref<TaskSummary[]>([])
const scope = ref<Scope>('all')
const loading = ref(true)
const busy = ref(false)
const likingIds = ref<string[]>([])
const showPublisher = ref(Boolean(route.query.taskId))
const errorMessage = ref('')
const taskId = ref(typeof route.query.taskId === 'string' ? route.query.taskId : '')
const title = ref('')
const description = ref('')
const promptPublic = ref(false)
const tagText = ref('')

async function load(): Promise<void> {
  loading.value = true
  try {
    const [page, tasks] = await Promise.all([
      communityApi.list(scope.value),
      tasksApi.list(1, 'completed', 100),
    ])
    posts.value = page.items
    completedTasks.value = tasks.items
  } catch (error) {
    errorMessage.value = error instanceof ApiError ? error.message : '社区加载失败'
  } finally {
    loading.value = false
  }
}

async function changeScope(value: Scope): Promise<void> {
  scope.value = value
  await load()
}

async function publish(): Promise<void> {
  if (busy.value) return
  busy.value = true
  errorMessage.value = ''
  try {
    const post = await communityApi.publish({
      task_id: taskId.value,
      title: title.value,
      description: description.value,
      prompt_public: promptPublic.value,
      tags: tagText.value.split(/[,，\s]+/).filter(Boolean).slice(0, 3),
    })
    await router.push(`/community/posts/${post.id}`)
  } catch (error) {
    errorMessage.value = error instanceof ApiError ? error.message : '发布失败'
  } finally {
    busy.value = false
  }
}

async function like(post: CommunityPost): Promise<void> {
  if (likingIds.value.includes(post.id)) return
  likingIds.value = [...likingIds.value, post.id]
  errorMessage.value = ''
  try {
    const result = await communityApi.like(post.id)
    post.liked = result.liked
    post.like_count = Math.max(0, post.like_count + (result.liked ? 1 : -1))
  } catch (error) {
    errorMessage.value = error instanceof ApiError ? error.message : '点赞操作失败'
  } finally {
    likingIds.value = likingIds.value.filter((id) => id !== post.id)
  }
}

async function favorite(post: CommunityPost): Promise<void> {
  const result = await communityApi.favorite(post.id)
  post.favorited = result.favorited
  post.favorite_count += result.favorited ? 1 : -1
}

async function remove(post: CommunityPost): Promise<void> {
  if (!window.confirm(`确认从社区删除“${post.title}”？`)) return
  await communityApi.delete(post.id)
  posts.value = posts.value.filter((item) => item.id !== post.id)
}

onMounted(load)
</script>

<template>
  <div class="page">
    <div class="page-heading">
      <div><p class="eyebrow">Community</p><h1>创作者社区</h1><p>发现、交流并收藏由 Clip Agent 创作的作品。</p></div>
      <button class="button primary" type="button" @click="showPublisher = !showPublisher">＋ 发布作品</button>
    </div>

    <form v-if="showPublisher" class="panel publish-form" @submit.prevent="publish">
      <div class="section-heading"><div><p class="eyebrow">Publish</p><h2>发布已完成的视频</h2></div></div>
      <label for="publish-task">关联视频</label>
      <select id="publish-task" v-model="taskId" required><option value="" disabled>选择一条已完成视频</option><option v-for="task in completedTasks" :key="task.id" :value="task.id">{{ task.topic }}</option></select>
      <label for="publish-title">作品标题</label><input id="publish-title" v-model="title" required maxlength="50" />
      <label for="publish-description">作品描述</label><textarea id="publish-description" v-model="description" maxlength="500" rows="3"></textarea>
      <label for="publish-tags">标签（最多 3 个，以逗号分隔）</label><input id="publish-tags" v-model="tagText" maxlength="65" placeholder="AI, 科普" />
      <label class="inline-check"><input v-model="promptPublic" type="checkbox" />允许其他用户查看生成提示词</label>
      <button class="button primary" type="submit" :disabled="busy || !completedTasks.length">{{ busy ? '发布中…' : '确认发布' }}</button>
    </form>

    <div class="community-tabs" role="tablist" aria-label="作品范围">
      <button v-for="item in ([['all','最新作品'],['following','关注动态'],['mine','我的作品'],['favorites','我的收藏'],['shared','转发给我']] as const)" :key="item[0]" type="button" :class="{ active: scope === item[0] }" @click="changeScope(item[0])">{{ item[1] }}</button>
    </div>
    <AdSlot slot="community" />
    <p v-if="errorMessage" class="form-error" role="alert">{{ errorMessage }}</p>
    <div v-if="loading" class="state-card"><span class="spinner"></span><p>正在加载社区作品…</p></div>
    <div v-else-if="!posts.length" class="state-card empty-state"><span class="empty-glyph">✦</span><h2>这里还没有作品</h2><p>完成一条视频后，把它发布到社区吧。</p></div>
    <section v-else class="community-grid">
      <article v-for="post in posts" :key="post.id" class="community-card">
        <RouterLink :to="`/community/posts/${post.id}`" class="community-cover"><img :src="communityApi.mediaUrl(post.cover_url)" alt="作品首帧封面" loading="lazy" /></RouterLink>
        <div class="community-card-body">
          <div class="community-author"><RouterLink :to="`/users/${post.author.id}`" class="author-link">{{ scope === 'shared' ? `转发自 @${post.author.name}` : post.author.name }}</RouterLink><time>{{ formatDate(post.created_at) }}</time></div>
          <RouterLink :to="`/community/posts/${post.id}`"><h2>{{ post.title }}</h2></RouterLink>
          <p>{{ post.description || '作者没有填写作品描述。' }}</p>
          <div class="tag-row"><span v-for="tag in post.tags" :key="tag">#{{ tag }}</span></div>
          <div class="community-stats"><span>{{ formatDuration(post.duration_seconds) }}</span><span>评论 {{ post.comment_count }}</span><span>转发 {{ post.share_count }}</span></div>
          <div class="community-actions"><button class="text-button" type="button" :disabled="likingIds.includes(post.id)" @click="like(post)">{{ post.liked ? '♥ 已赞' : '♡ 点赞' }} {{ post.like_count }}</button><button class="text-button" type="button" @click="favorite(post)">{{ post.favorited ? '★ 已收藏' : '☆ 收藏' }} {{ post.favorite_count }}</button><button v-if="post.owned_by_me" class="text-button danger-text" type="button" @click="remove(post)">删除</button></div>
        </div>
      </article>
    </section>
  </div>
</template>
