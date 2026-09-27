// @Author: RebeccaZhou
// @Description: Frontend API request client
//              前端 API 请求客户端
import axios from 'axios'

export const http = axios.create({
  baseURL: '/api',
  timeout: 30000,
})

export interface ModelOption {
  id: string
  name: string
  provider: string
}

export async function fetchModels(): Promise<{ models: ModelOption[]; default: string }> {
  const { data } = await http.get('/models')
  return data
}

export interface EvalCaseInfo {
  case_id: string
  scenario: string
  question: string
}

export async function fetchEvalCases(): Promise<{
  total: number
  by_scenario: Record<string, number>
  cases: EvalCaseInfo[]
}> {
  const { data } = await http.get('/eval/cases')
  return data
}

export interface GraphNodeDTO {
  id: string
  label: string
  title: string
  properties: Record<string, unknown>
}

export interface GraphEdgeDTO {
  source: string
  target: string
  type: string
}

export async function fetchGraph(label?: string): Promise<{ nodes: GraphNodeDTO[]; edges: GraphEdgeDTO[] }> {
  const { data } = await http.get('/graph', { params: label ? { label } : {} })
  return data
}

export async function fetchSchema(): Promise<{
  nodes: string[]
  relationships: { source: string; type: string; target: string; desc: string }[]
}> {
  const { data } = await http.get('/graph/schema')
  return data
}

export interface SSEHandlers {
  onEvent: (event: string, data: any) => void
}

/**
 * 以 POST 发起 SSE 请求并解析 text/event-stream。
 * sse-starlette 输出形如：event: <name>\ndata: <json>\n\n
 */
export async function postSSE(
  url: string,
  body: unknown,
  handlers: SSEHandlers,
): Promise<void> {
  const resp = await fetch(`/api${url}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
    body: JSON.stringify(body),
  })

  if (!resp.body) throw new Error('响应不含可读流')
  const reader = resp.body.getReader()
  const decoder = new TextDecoder('utf-8')
  let buffer = ''

  const dispatch = (block: string) => {
    let event = 'message'
    const dataLines: string[] = []
    for (const line of block.split('\n')) {
      if (line.startsWith('event:')) event = line.slice(6).trim()
      else if (line.startsWith('data:')) dataLines.push(line.slice(5).trim())
    }
    if (dataLines.length === 0) return
    try {
      const parsed = JSON.parse(dataLines.join('\n'))
      handlers.onEvent(event, parsed)
    } catch {
      handlers.onEvent(event, { raw: dataLines.join('\n') })
    }
  }

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    let idx: number
    // SSE 事件以空行分隔（兼容 \n\n 与 \r\n\r\n）
    while ((idx = buffer.search(/\r?\n\r?\n/)) !== -1) {
      const block = buffer.slice(0, idx)
      buffer = buffer.slice(idx).replace(/^\r?\n\r?\n/, '')
      if (block.trim()) dispatch(block)
    }
  }
  if (buffer.trim()) dispatch(buffer)
}
