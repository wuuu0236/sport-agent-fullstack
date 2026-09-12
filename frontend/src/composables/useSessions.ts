// 会话与消息状态（从原 Chat.vue 的 setup 中抽离）
// 职责：多会话管理 + 消息本地持久化；UI 只消费这里的响应式状态。
import { ref, watch } from 'vue'
import type { Msg } from '../types'
import {
  listSessions,
  getCurrentSessionId,
  setCurrentSessionId,
  createSession,
  deleteSession,
  renameSession,
  touchSession,
  loadMessages,
  saveMessages,
  migrateLegacyHistory,
  type SessionMeta,
} from '../utils/session'

export function useSessions() {
  const sessions = ref<SessionMeta[]>(listSessions())
  const currentId = ref<string | null>(getCurrentSessionId())
  const messages = ref<Msg[]>([])

  // 消息变化即落盘；同时就地更新会话元信息（条数/时间），
  // 避免每敲一次键盘都重读一遍 localStorage。
  watch(
    messages,
    (v) => {
      if (!currentId.value) return
      saveMessages(currentId.value, v)
      touchSession(currentId.value, v.length)
      const meta = sessions.value.find((s) => s.id === currentId.value)
      if (meta) {
        meta.messageCount = v.length
        meta.updatedAt = Date.now()
      }
    },
    { deep: true },
  )

  function refresh() {
    sessions.value = listSessions()
  }

  /** 首次进入：迁移旧版单会话历史；否则确保当前会话有效 */
  function ensure() {
    const migrated = migrateLegacyHistory()
    if (migrated) {
      currentId.value = migrated
      messages.value = loadMessages(migrated)
      refresh()
      return
    }
    const exists = currentId.value && listSessions().some((s) => s.id === currentId.value)
    if (!exists) {
      const meta = createSession()
      currentId.value = meta.id
      messages.value = []
      refresh()
    } else {
      messages.value = loadMessages(currentId.value as string)
    }
  }

  function createNew() {
    if (currentId.value) saveMessages(currentId.value, messages.value)
    const meta = createSession()
    currentId.value = meta.id
    messages.value = []
    refresh()
  }

  function select(id: string) {
    if (id === currentId.value) return
    if (currentId.value) saveMessages(currentId.value, messages.value)
    setCurrentSessionId(id)
    currentId.value = id
    messages.value = loadMessages(id)
  }

  function remove(id: string) {
    deleteSession(id)
    refresh()
    if (currentId.value !== id) return
    const next = listSessions()[0]
    if (next) {
      setCurrentSessionId(next.id)
      currentId.value = next.id
      messages.value = loadMessages(next.id)
    } else {
      const meta = createSession()
      currentId.value = meta.id
      messages.value = []
      refresh()
    }
  }

  function renameCurrent(title: string) {
    if (!currentId.value) return
    renameSession(currentId.value, title)
    refresh()
  }

  return {
    sessions,
    currentId,
    messages,
    refresh,
    ensure,
    createNew,
    select,
    remove,
    renameCurrent,
  }
}
