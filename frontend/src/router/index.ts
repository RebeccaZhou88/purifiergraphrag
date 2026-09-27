// @Author: RebeccaZhou
// @Description: Frontend router configuration
//              前端路由配置
import { createRouter, createWebHistory } from 'vue-router'

const routes = [
  { path: '/', redirect: '/chat' },
  { path: '/chat', name: 'chat', component: () => import('@/views/ChatView.vue'), meta: { title: '智能问答' } },
  { path: '/graph', name: 'graph', component: () => import('@/views/GraphView.vue'), meta: { title: '知识图谱' } },
  { path: '/eval', name: 'eval', component: () => import('@/views/EvalView.vue'), meta: { title: '评估面板' } },
]

export default createRouter({
  history: createWebHistory(),
  routes,
})
