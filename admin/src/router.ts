import { createRouter, createWebHistory } from 'vue-router'
import { useAdminSession } from './session'
import LoginView from './views/LoginView.vue'
import OverviewView from './views/OverviewView.vue'
import UsersView from './views/UsersView.vue'
import CdksView from './views/CdksView.vue'
import TasksView from './views/TasksView.vue'
import AuditLogsView from './views/AuditLogsView.vue'
import AdsView from './views/AdsView.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/login', name: 'login', component: LoginView, meta: { public: true } },
    { path: '/', name: 'overview', component: OverviewView },
    { path: '/users', name: 'users', component: UsersView },
    { path: '/tasks', name: 'tasks', component: TasksView },
    { path: '/cdks', name: 'cdks', component: CdksView },
    { path: '/audit-logs', name: 'audit-logs', component: AuditLogsView },
    { path: '/ads', name: 'ads', component: AdsView },
    { path: '/:pathMatch(.*)*', redirect: '/' },
  ],
})

router.beforeEach(async (to) => {
  const session = useAdminSession()
  await session.restore()
  if (!to.meta.public && !session.authenticated.value) return { name: 'login' }
  if (to.meta.public && session.authenticated.value) return { name: 'overview' }
  return true
})

export default router
