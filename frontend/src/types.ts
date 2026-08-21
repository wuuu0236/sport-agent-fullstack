// 共享类型
export interface ThinkingStep {
  name: string
  label: string
  status: 'idle' | 'running' | 'done' | 'failed'
  output?: string
}

export interface Msg {
  role: 'user' | 'assistant' | 'thinking'
  text?: string
  agent?: string
  thinking?: {
    steps: ThinkingStep[]
    status: 'running' | 'done'
  }
}
