// @Author: RebeccaZhou
// @Description: Chat state store (Pinia)
//              问答状态管理（Pinia）
import { defineStore } from 'pinia'
import { postSSE, fetchModels, type ModelOption } from '@/api/client'

export interface Fragment {
  id: string
  title: string
  content: unknown
}

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  fragments?: Fragment[]
  streaming?: boolean
}

export interface TerminalLog {
  id: number
  time: string
  step: string
  message: string
  data?: unknown
}

let seq = 0
const nextId = () => `m${Date.now()}_${seq++}`

function nowTime() {
  return new Date().toLocaleTimeString('zh-CN', { hour12: false })
}

interface ChatState {
  messages: ChatMessage[]
  logs: TerminalLog[]
  models: ModelOption[]
  selectedModel: string
  loading: boolean
}

export const useChatStore = defineStore('chat', {
  state: (): ChatState => ({
    messages: [],
    logs: [],
    models: [],
    selectedModel: 'qwen',
    loading: false,
  }),

  actions: {
    async loadModels() {
      try {
        const res = await fetchModels()
        this.models = res.models
        // 默认第一项；保留用户已选手动选择
        if (!this.models.some((m) => m.id === this.selectedModel)) {
          this.selectedModel = res.default || this.models[0]?.id || 'qwen'
        }
      } catch {
        this.models = [
          { id: 'qwen', name: 'Qwen-Plus', provider: 'qwen' },
          { id: 'deepseek', name: 'DeepSeek-Chat', provider: 'deepseek' },
          { id: 'azure_openai', name: 'Azure GPT-4o-mini', provider: 'azure_openai' },
        ]
      }
    },

    pushLog(step: string, message: string, data?: unknown) {
      this.logs.push({ id: this.logs.length + 1, time: nowTime(), step, message, data })
    },

    clearConversation() {
      this.messages = []
      this.logs = []
    },

    refreshMetrics() {
      // 刷新模型/服务指标（健康状态）
      return this.loadModels()
    },

    async ask(question: string) {
      const q = question.trim()
      if (!q || this.loading) return

      this.messages.push({ id: nextId(), role: 'user', content: q })
      this.messages.push({
        id: nextId(),
        role: 'assistant',
        content: '',
        fragments: [],
        streaming: true,
      })
      // 从响应式数组取回代理引用，确保后续修改触发视图更新
      const assistant = this.messages[this.messages.length - 1]
      this.loading = true
      this.pushLog('pipeline', `收到问题：${q}`)

      try {
        await postSSE('/chat', { question: q, model: this.selectedModel }, {
          onEvent: (event, data) => {
            if (event === 'step') {
              this.pushLog(data.step, data.message, data.data)
            } else if (event === 'fragments') {
              assistant.fragments = data.fragments || []
              this.pushLog('graph_context', `收到 ${assistant.fragments?.length ?? 0} 条引用片段`)
            } else if (event === 'token') {
              assistant.content += data.text || ''
            } else if (event === 'done') {
              assistant.content = data.answer || assistant.content
              assistant.streaming = false
              this.pushLog('pipeline', '回答完成')
            }
          },
        })
      } catch (e) {
        assistant.content = `请求失败：${(e as Error).message}`
        this.pushLog('error', (e as Error).message)
      } finally {
        assistant.streaming = false
        this.loading = false
      }
    },
  },
})
