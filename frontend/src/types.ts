// 共享类型
export interface Msg {
  role: 'user' | 'assistant'
  text: string
  agent?: string
}
