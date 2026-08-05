import { createRouter, createWebHistory } from 'vue-router'
import { useSession } from '../composables/useSession'
import AuthView from '../views/AuthView.vue'
import HistoryView from '../views/HistoryView.vue'
import NewTaskView from '../views/NewTaskView.vue'
import SettingsView from '../views/SettingsView.vue'
import TaskDetailView from '../views/TaskDetailView.vue'
import CommunityView from '../views/CommunityView.vue'
import CommunityPostView from '../views/CommunityPostView.vue'
import UserProfileView from '../views/UserProfileView.vue'
import AccountView from '../views/AccountView.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/tasks' },
    { path: '/login', name: 'login', component: AuthView, props: { mode: 'login' }, meta: { public: true } },
    {
      path: '/register',
      name: 'register',
      component: AuthView,
      props: { mode: 'register' },
      meta: { public: true },
    },
    { path: '/tasks', name: 'history', component: HistoryView },
    { path: '/tasks/new', name: 'new-task', component: NewTaskView },
    { path: '/tasks/:taskId', name: 'task-detail', component: TaskDetailView },
    { path: '/community', name: 'community', component: CommunityView },
    { path: '/community/posts/:postId', name: 'community-post', component: CommunityPostView },
    { path: '/users/:userId', name: 'user-profile', component: UserProfileView },
    { path: '/settings', name: 'settings', component: SettingsView },
    { path: '/account', name: 'account', component: AccountView },
    { path: '/:pathMatch(.*)*', redirect: '/tasks' },
  ],
})

router.beforeEach(async (to) => {
  const session = useSession()
  await session.restore()
  if (!to.meta.public && !session.authenticated.value) {
    return { name: 'login', query: { redirect: to.fullPath } }
  }
  if (to.meta.public && session.authenticated.value) return { name: 'history' }
  return true
})

export default router
