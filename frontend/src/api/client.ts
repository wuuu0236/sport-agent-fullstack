import axios from 'axios'

const http = axios.create({ baseURL: '/api' })

export interface ChatResp {
  agent?: string
  output?: string
  reply?: string
}

export interface OrchestrateEvent {
  type:
    | 'start'
    | 'plan'
    | 'agent_start'
    | 'agent_done'
    | 'agent_error'
    | 'complete'
    | 'pending_commit'
    | 'error'
  agent?: string
  step?: number
  total?: number
  output?: string
  final?: boolean
  status?: string
  message?: string
  steps?: string[]
  count?: number
  records?: any[]
}

// 发一条消息给后端（Spring Boot /api/chat），后端透传到 Python agent-service
export async function sendChat(message: string): Promise<ChatResp> {
  const { data } = await http.post('/chat', { message })
  return data
}

// 健康检查：前端连接状态灯用
export async function checkHealth(): Promise<{ status: string }> {
  const { data } = await http.get('/health')
  return data
}

// 上传训练截图：multipart 发给 /api/import-image，后端转 base64 透传到 Python 做本地 OCR 落库
export async function importImage(file: File): Promise<any> {
  const form = new FormData()
  form.append('file', file)
  const { data } = await http.post('/import-image', form, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
  return data
}

// 最近训练记录：经 Vite 代理 /agent 直连 Python agent-service 的 /sessions（只读展示）
export async function getSessions(limit = 12): Promise<{ sessions: any[] }> {
  const resp = await fetch(`/agent/sessions?limit=${limit}`)
  if (!resp.ok) throw new Error('sessions fetch failed')
  return await resp.json()
}

// 长期记忆：USER（关于用户）/ MEMORY（助理笔记），工作台「记忆」模块用
export async function getMemory(): Promise<{ user: string[]; memory: string[]; snapshot: string }> {
  const resp = await fetch(`/agent/memory`)
  if (!resp.ok) throw new Error('memory fetch failed')
  return await resp.json()
}

// 确认暂存记录入库（主 Agent 编排后用户点「确认」→ 后端 /commit 落库）
export async function commitRecords(records?: any[]): Promise<{ ok: boolean; msg?: string }> {
  const { data } = await http.post('/commit', records ? { records } : {})
  return data
}

// 多 Agent 编排流水线（SSE）：用 EventSource(GET) 订阅后端 /api/orchestrate 推送的状态事件。
// 每个事件通过 onEvent 回调实时传回，用于前端 Agent 协作链路看板。
export function orchestrate(message: string, onEvent: (e: OrchestrateEvent) => void): void {
  const url = `/api/orchestrate?message=${encodeURIComponent(message)}`
  const es = new EventSource(url)
  es.onmessage = (ev) => {
    let data: OrchestrateEvent
    try {
      data = JSON.parse(ev.data) as OrchestrateEvent
    } catch {
      return
    }
    onEvent(data)
    if (data.type === 'complete' || data.type === 'error') es.close()
  }
  es.onerror = () => {
    onEvent({ type: 'error', message: '编排连接中断' })
    es.close()
  }
}
