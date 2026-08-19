// 会话管理存储层（localStorage）：
//  - sport-sessions:      会话元数据列表 [{id, title, updatedAt, messageCount}]
//  - sport-current-session: 当前会话 id
//  - sport-chat-<id>:      每个会话的消息数组
// 旧版单会话数据（sport-chat-history）首次启动时自动迁移到默认会话。
import type { Msg } from '../types'

export interface SessionMeta {
  id: string
  title: string
  updatedAt: number
  messageCount: number
}

const SESSIONS_KEY = 'sport-sessions'
const CURRENT_KEY = 'sport-current-session'
const LEGACY_KEY = 'sport-chat-history'

function read<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(key)
    return raw ? (JSON.parse(raw) as T) : fallback
  } catch {
    return fallback
  }
}

function write(key: string, value: unknown): void {
  try {
    localStorage.setItem(key, JSON.stringify(value))
  } catch {
    /* localStorage 已满/隐私模式等场景忽略 */
  }
}

function genId(): string {
  return Date.now().toString(36) + Math.random().toString(36).slice(2, 8)
}

export function listSessions(): SessionMeta[] {
  return read<SessionMeta[]>(SESSIONS_KEY, [])
}

function saveSessions(list: SessionMeta[]): void {
  write(SESSIONS_KEY, list)
}

export function getCurrentSessionId(): string | null {
  return read<string | null>(CURRENT_KEY, null)
}

export function setCurrentSessionId(id: string): void {
  write(CURRENT_KEY, id)
}

export function createSession(title = '新会话'): SessionMeta {
  const meta: SessionMeta = { id: genId(), title, updatedAt: Date.now(), messageCount: 0 }
  const list = listSessions()
  list.unshift(meta)
  saveSessions(list)
  setCurrentSessionId(meta.id)
  return meta
}

export function deleteSession(id: string): void {
  const list = listSessions().filter((s) => s.id !== id)
  saveSessions(list)
  try {
    localStorage.removeItem(msgKey(id))
  } catch {
    /* ignore */
  }
  if (getCurrentSessionId() === id) setCurrentSessionId(list[0]?.id ?? '')
}

export function renameSession(id: string, title: string): void {
  const list = listSessions()
  const s = list.find((x) => x.id === id)
  if (s) {
    s.title = title.slice(0, 30)
    saveSessions(list)
  }
}

export function touchSession(id: string, messageCount: number): void {
  const list = listSessions()
  const s = list.find((x) => x.id === id)
  if (s) {
    s.updatedAt = Date.now()
    s.messageCount = messageCount
    saveSessions(list)
  }
}

export function msgKey(id: string): string {
  return `sport-chat-${id}`
}

export function loadMessages(id: string): Msg[] {
  return read<Msg[]>(msgKey(id), [])
}

export function saveMessages(id: string, msgs: Msg[]): void {
  write(msgKey(id), msgs)
}

// 旧版单会话数据迁移：把 sport-chat-history 迁到「默认会话」
export function migrateLegacyHistory(): string | null {
  const legacy = read<Msg[] | null>(LEGACY_KEY, null)
  if (!legacy || !legacy.length) return null
  // 只在没有任何会话时迁移一次
  if (listSessions().length) return null
  const meta = createSession('历史对话')
  saveMessages(meta.id, legacy)
  try {
    localStorage.removeItem(LEGACY_KEY)
  } catch {
    /* ignore */
  }
  return meta.id
}
