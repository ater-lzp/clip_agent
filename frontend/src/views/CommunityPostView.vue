<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { communityApi } from '../api'
import { ApiError } from '../api/client'
import type { CommunityComment, CommunityPost } from '../types/domain'
import { formatDate } from '../utils/format'

const route = useRoute()
const router = useRouter()
const postId = computed(() => String(route.params.postId ?? ''))
const post = ref<CommunityPost | null>(null)
const comments = ref<CommunityComment[]>([])
const sort = ref<'latest' | 'hot'>('latest')
const content = ref('')
const replyTo = ref<CommunityComment | null>(null)
const shareQuery = ref('')
const shareUsers = ref<Array<{ id: string; name: string; avatar_url: string | null }>>([])
const loading = ref(true)
const busy = ref(false)
const postLikeBusy = ref(false)
const errorMessage = ref('')
const rootComments = computed(() => comments.value.filter((item) => item.parent_id === null))
const replies = (id: string) => comments.value.filter((item) => item.parent_id === id)

async function load(): Promise<void> {
  try {
    const [loadedPost, loadedComments] = await Promise.all([
      communityApi.get(postId.value),
      communityApi.comments(postId.value, sort.value),
    ])
    post.value = loadedPost
    comments.value = loadedComments.items
  } catch (error) {
    errorMessage.value = error instanceof ApiError ? error.message : '作品加载失败'
  } finally {
    loading.value = false
  }
}

async function submitComment(): Promise<void> {
  if (!content.value.trim() || busy.value) return
  busy.value = true
  await communityApi.comment(postId.value, content.value.trim(), replyTo.value?.id ?? null)
  content.value = ''
  replyTo.value = null
  comments.value = (await communityApi.comments(postId.value, sort.value)).items
  busy.value = false
}

async function like(comment: CommunityComment): Promise<void> {
  const result = await communityApi.likeComment(comment.id)
  comment.liked = result.liked
  comment.like_count += result.liked ? 1 : -1
}

async function likePost(): Promise<void> {
  if (!post.value || postLikeBusy.value) return
  postLikeBusy.value = true
  errorMessage.value = ''
  try {
    const result = await communityApi.like(post.value.id)
    post.value.liked = result.liked
    post.value.like_count = Math.max(0, post.value.like_count + (result.liked ? 1 : -1))
  } catch (error) {
    errorMessage.value = error instanceof ApiError ? error.message : '点赞操作失败'
  } finally {
    postLikeBusy.value = false
  }
}

async function removeComment(comment: CommunityComment): Promise<void> {
  await communityApi.deleteComment(comment.id)
  comments.value = comments.value.filter((item) => item.id !== comment.id && item.parent_id !== comment.id)
}

async function searchUsers(): Promise<void> {
  if (!shareQuery.value.trim()) return
  shareUsers.value = (await communityApi.searchUsers(shareQuery.value.trim())).items
}

async function share(recipientId: string): Promise<void> {
  await communityApi.share(postId.value, recipientId)
  shareUsers.value = []
  shareQuery.value = ''
  if (post.value) post.value.share_count += 1
}

async function copyLink(): Promise<void> {
  await navigator.clipboard.writeText(window.location.href)
}

async function removePost(): Promise<void> {
  if (!post.value || !window.confirm(`确认删除“${post.value.title}”？`)) return
  await communityApi.delete(post.value.id)
  await router.push('/community')
}

onMounted(load)
</script>

<template>
  <div class="page narrow-page">
    <div v-if="loading" class="state-card"><span class="spinner"></span><p>正在加载作品…</p></div>
    <div v-else-if="!post" class="state-card error-state"><h2>无法打开作品</h2><p>{{ errorMessage }}</p></div>
    <template v-else>
      <RouterLink class="back-link" to="/community">← 返回社区</RouterLink>
      <section class="panel community-detail">
        <div class="section-heading"><div><p class="eyebrow"><RouterLink :to="`/users/${post.author.id}`" class="author-link">{{ post.author.name }}</RouterLink> · {{ formatDate(post.created_at) }}</p><h1>{{ post.title }}</h1></div><button v-if="post.owned_by_me" class="button ghost danger-text" @click="removePost">删除作品</button></div>
        <p>{{ post.description }}</p>
        <div class="video-stage" :class="post.aspect_ratio === '9:16' ? 'video-portrait' : 'video-landscape'"><video controls :src="communityApi.mediaUrl(post.video_url)"></video></div>
        <div class="tag-row"><span v-for="tag in post.tags" :key="tag">#{{ tag }}</span></div>
        <div class="post-engagement">
          <button class="text-button" type="button" :disabled="postLikeBusy" @click="likePost">{{ post.liked ? '♥ 已赞' : '♡ 点赞' }} {{ post.like_count }}</button>
        </div>
        <div v-if="post.generation_prompt" class="prompt-disclosure"><strong>生成提示词</strong><p>{{ post.generation_prompt }}</p></div>
        <div class="share-panel"><button class="button secondary" type="button" @click="copyLink">复制永久链接</button><input v-model="shareQuery" placeholder="搜索昵称或邮箱进行站内转发" @keyup.enter="searchUsers" /><button class="button secondary" @click="searchUsers">搜索</button></div>
        <div v-if="shareUsers.length" class="share-results"><button v-for="user in shareUsers" :key="user.id" type="button" @click="share(user.id)">转发给 {{ user.name }}</button></div>
      </section>

      <section class="panel comments-panel">
        <div class="section-heading"><h2>评论（{{ post.comment_count }}）</h2><select v-model="sort" class="compact-select" @change="load"><option value="latest">最新</option><option value="hot">最热</option></select></div>
        <form class="comment-form" @submit.prevent="submitComment"><p v-if="replyTo" class="muted">回复 {{ replyTo.author.name }} <button class="text-button" type="button" @click="replyTo = null">取消</button></p><textarea v-model="content" required maxlength="200" rows="3" placeholder="友善交流，最多 200 字"></textarea><button class="button primary" :disabled="busy">发表评论</button></form>
        <ol class="comment-list">
          <li v-for="comment in rootComments" :key="comment.id">
            <div class="comment-meta"><RouterLink :to="`/users/${comment.author.id}`" class="author-link">{{ comment.author.name }}</RouterLink><time>{{ formatDate(comment.created_at) }}</time></div><p>{{ comment.content }}</p>
            <div><button class="text-button" @click="like(comment)">{{ comment.liked ? '已赞' : '点赞' }} {{ comment.like_count }}</button><button class="text-button" @click="replyTo = comment">回复</button><button v-if="comment.can_delete" class="text-button danger-text" @click="removeComment(comment)">删除</button></div>
            <ol class="reply-list"><li v-for="reply in replies(comment.id)" :key="reply.id"><div class="comment-meta"><RouterLink :to="`/users/${reply.author.id}`" class="author-link">{{ reply.author.name }}</RouterLink><time>{{ formatDate(reply.created_at) }}</time></div><p>{{ reply.content }}</p><button class="text-button" @click="like(reply)">{{ reply.liked ? '已赞' : '点赞' }} {{ reply.like_count }}</button><button v-if="reply.can_delete" class="text-button danger-text" @click="removeComment(reply)">删除</button></li></ol>
          </li>
        </ol>
      </section>
    </template>
  </div>
</template>
