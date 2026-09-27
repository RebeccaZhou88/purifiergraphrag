// @Author: RebeccaZhou
// @Description: Evaluation state store (Pinia)
//              评估状态管理（Pinia）
import { defineStore } from 'pinia'
import { postSSE, fetchModels, fetchEvalCases, type ModelOption } from '@/api/client'

export interface CaseResult {
  case_id: string
  scenario: string
  question: string
  expected_keywords: string[]
  answer: string
  passed: boolean
  latency_ms: number
  rank: number
}

export interface SummaryMetrics {
  total: number
  passed: number
  accuracy: number
  p95_ms: number
  target_accuracy: number
  target_p95_ms: number
}

interface EvalState {
  models: ModelOption[]
  selectedModel: string
  scenario: string
  running: boolean
  caseTotal: number
  scenarioCount: number
  results: CaseResult[]
  summary: SummaryMetrics | null
}

export const useEvalStore = defineStore('eval', {
  state: (): EvalState => ({
    models: [],
    selectedModel: 'qwen',
    scenario: '',
    running: false,
    caseTotal: 0,
    scenarioCount: 0,
    results: [],
    summary: null,
  }),

  getters: {
    // 按最新排名(rank)升序排列
    rankedResults(state): CaseResult[] {
      return [...state.results].sort((a, b) => a.rank - b.rank)
    },
  },

  actions: {
    async loadModels() {
      try {
        const res = await fetchModels()
        this.models = res.models
        if (!this.models.some((m) => m.id === this.selectedModel)) {
          this.selectedModel = res.default || this.models[0]?.id || 'qwen'
        }
      } catch {
        this.models = [{ id: 'qwen', name: 'Qwen-Plus', provider: 'qwen' }]
      }
    },

    async loadCases() {
      try {
        const res = await fetchEvalCases()
        this.caseTotal = res.total
        this.scenarioCount = Object.keys(res.by_scenario).length
      } catch {
        // 后端不可用时保持 0，不阻塞面板
      }
    },

    async run() {
      if (this.running) return
      this.running = true
      this.results = []
      this.summary = null
      await postSSE(
        '/eval',
        { model: this.selectedModel, scenario: this.scenario || null },
        {
          onEvent: (event, data) => {
            if (event === 'case') {
              this.results.push(data.case)
            } else if (event === 'summary') {
              this.summary = data.metrics
              this.results = data.ranked
            }
          },
        },
      ).finally(() => {
        this.running = false
      })
    },
  },
})
