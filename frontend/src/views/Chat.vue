<template>
  <div class="chat-module">
    <!-- 左侧会话栏 -->
    <SessionSidebar
      :sessions="sessions"
      :currentId="currentSessionId"
      @new="newSession"
      @select="selectSession"
      @delete="removeSession"
    />

    <!-- 主聊天区 -->
    <main class="chat-page">
      <div class="chat">
        <HeaderBar :conn="conn" :connText="connText" />

        <MessageList
          :messages="messages"
          :pendingCommit="pendingCommit"
          @commit="doCommit"
          @dismissCommit="pendingCommit = null"
        />

        <!-- 图片拖拽/点击/粘贴上传 -->
        <Dropzone :uploading="uploading" @pick="pickFile" @dropFile="handleImage" />

        <ChatInput
          :busy="busy"
          :orchestrating="orchestrating"
          @send="send"
          @orchestrate="triggerOrchestrate"
          @pasteImage="handleImage"
        />

        <input ref="fileInput" type="file" accept="image/*" hidden @change="onFileChange" />
      </div>
    </main>

    <!-- 右侧：仅用户画像。多 Agent 协作链路已内联到对话流的「思考过程」卡片 -->
    <div class="right-rail">
      <UserProfileSidebar :entries="userMemory" />
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, watch } from 'vue'
import HeaderBar from '../components/HeaderBar.vue'
import MessageList from '../components/MessageList.vue'
import ChatInput from '../components/ChatInput.vue'
import Dropzone from '../components/Dropzone.vue'
import SessionSidebar from '../components/SessionSidebar.vue'
import UserProfileSidebar from '../components/UserProfileSidebar.vue'
import type { Msg } from '../types'
import type { SessionMeta } from '../utils/session'
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
} from '../utils/session'
import { sendChat, checkHealth, importImage, orchestrate, commitRecords, getMemory } from '../api/client'
import type { OrchestrateEvent } from '../api/client'

// ---- 会话管理 ----
const sessions = ref<SessionMeta[]>(listSessions())
const currentSessionId = ref<string | null>(getCurrentSessionId())

// 当前会话消息：切换会话时保存旧会话、加载新会话
const messages = ref<Msg[]>([])
watch(
  messages,
  (v) => {
    if (!currentSessionId.value) return
    saveMessages(currentSessionId.value, v)
    touchSession(currentSessionId.value, v.length)
  },
  { deep: true },
)

function refreshSessions() {
  sessions.value = listSessions()
}

function ensureSession() {
  // 首次启动：迁移旧单会话历史；仍无会话则新建
  const migrated = migrateLegacyHistory()
  if (migrated) {
    currentSessionId.value = migrated
    messages.value = loadMessages(migrated)
    refreshSessions()
    return
  }
  if (!currentSessionId.value || !listSessions().some((s) => s.id === currentSessionId.value)) {
    const meta = createSession()
    currentSessionId.value = meta.id
    refreshSessions()
  } else {
    messages.value = loadMessages(currentSessionId.value)
  }
}

function newSession() {
  if (currentSessionId.value) saveMessages(currentSessionId.value, messages.value)
  const meta = createSession()
  currentSessionId.value = meta.id
  messages.value = []
  refreshSessions()
}

function selectSession(id: string) {
  if (id === currentSessionId.value) return
  if (currentSessionId.value) saveMessages(currentSessionId.value, messages.value)
  setCurrentSessionId(id)
  currentSessionId.value = id
  messages.value = loadMessages(id)
}

function removeSession(id: string) {
  deleteSession(id)
  refreshSessions()
  if (currentSessionId.value !== id) return
  const next = listSessions()[0]
  if (next) {
    setCurrentSessionId(next.id)
    currentSessionId.value = next.id
    messages.value = loadMessages(next.id)
  } else {
    const meta = createSession()
    currentSessionId.value = meta.id
    messages.value = []
    refreshSessions()
  }
}

const busy = ref(false)
const uploading = ref(false)
const conn = ref<'checking' | 'ok' | 'err'>('checking')
const connText = ref('连接检测中')
const fileInput = ref<HTMLInputElement | null>(null)

// ---- 右侧用户画像：USER 长期记忆（关于你的身份/偏好/训练基线）----
const userMemory = ref<string[]>([])
async function loadUserMemory() {
  try {
    const d = await getMemory()
    userMemory.value = d.user || []
  } catch {
    userMemory.value = []
  }
}

// ---- 多 Agent 编排：内联「思考过程」消息（不再单独面板）----
const orchestrating = ref(false)
const pendingCommit = ref<{ count: number; records?: any[] } | null>(null)

// 子 Agent 中文标签（协作链路内联展示用）
const nodeLabel: Record<string, string> = {
  recorder: 'recorder · 记录',
  analyst: 'analyst · 分析',
  searcher: 'searcher · 搜索',
  clinician: 'clinician · 康复排查',
  expert: 'expert · 运动科学',
  planner: 'planner · 计划编排',
  reviewer: 'reviewer · 内容评审',
  memory: 'memory · 记忆',
  scheduler: 'scheduler · 日程',
  writer: 'writer · 润色',
  general: 'general · 通用',
  supervisor: 'supervisor · 主Agent',
}

async function doCommit() {
  const recs = pendingCommit.value?.records
  try {
    const r = await commitRecords(recs?.length ? recs : undefined)
    messages.value.push({ role: 'assistant', text: r.msg || '已处理', agent: 'supervisor' })
  } catch (e) {
    messages.value.push({ role: 'assistant', text: '确认失败：' + String(e), agent: 'supervisor' })
  }
  pendingCommit.value = null
}

async function refreshConn() {
  try {
    await checkHealth()
    conn.value = 'ok'
    connText.value = '已连接'
  } catch {
    conn.value = 'err'
    connText.value = '无法连接后端'
  }
}

async function send(text: string) {
  if (!text || busy.value) return
  messages.value.push({ role: 'user', text })
  // 首条消息：把「新会话」重命名为用户问题
  if (messages.value.length === 1 && currentSessionId.value) {
    renameSession(currentSessionId.value, text)
    refreshSessions()
  }
  busy.value = true
  try {
    const data = await sendChat(text)
    // 后端自动升级到多 Agent 编排：把 events 渲染成对话流里的一条「思考过程」消息，
    // 按顺序逐步 apply，模拟实时协作过程；最终结果作为独立 assistant 消息。
    if (data.events && data.events.length) {
      orchestrating.value = true
      pendingCommit.value = null
      const t = pushThinking()
      const sleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms))
      for (let i = 0; i < data.events.length; i++) {
        applyEvent(data.events[i], t)
        if (i < data.events.length - 1) await sleep(90)
      }
      orchestrating.value = false
    } else {
      messages.value.push({
        role: 'assistant',
        text: data.output ?? data.reply ?? '(无回复)',
        agent: data.agent,
      })
    }
  } catch (e) {
    messages.value.push({ role: 'assistant', text: '请求失败：' + String(e) })
  } finally {
    busy.value = false
    loadUserMemory() // 对话可能触发记忆写入，刷新右侧用户画像
  }
}

// 新建一条内联「思考过程」消息，返回响应式引用供 applyEvent 更新步骤
function pushThinking(): Msg {
  const t: Msg = { role: 'thinking', thinking: { steps: [], status: 'running' } }
  messages.value.push(t)
  return t
}

// 把编排事件应用到内联「思考过程」消息（Supervisor 派发哪个子 Agent 就显示哪个）。
// send() 普通聊天自动升级编排、triggerOrchestrate() 手动按钮，两者共用此渲染逻辑。
function applyEvent(e: OrchestrateEvent, t: Msg) {
  const steps = t.thinking!.steps
  if (e.type === 'plan' && e.steps) {
    for (const n of e.steps) {
      if (!steps.find((s) => s.name === n)) {
        steps.push({ name: n, label: nodeLabel[n] || n, status: 'idle' })
      }
    }
  } else if (e.type === 'agent_start' && e.agent) {
    let s = steps.find((x) => x.name === e.agent)
    if (!s) {
      s = { name: e.agent, label: nodeLabel[e.agent] || e.agent, status: 'running' }
      steps.push(s)
    } else {
      s.status = 'running'
    }
  } else if (e.type === 'agent_done' && e.agent) {
    const s = steps.find((x) => x.name === e.agent)
    if (s) {
      s.status = 'done'
      s.output = e.output || ''
    } else {
      steps.push({ name: e.agent, label: nodeLabel[e.agent] || e.agent, status: 'done', output: e.output || '' })
    }
  } else if (e.type === 'agent_error' && e.agent) {
    // 单节点失败：标红，但不中断整条链；Supervisor 会如实注明缺失继续
    const out = e.error || e.output || '节点失败'
    const s = steps.find((x) => x.name === e.agent)
    if (s) {
      s.status = 'failed'
      s.output = out
    } else {
      steps.push({ name: e.agent, label: nodeLabel[e.agent] || e.agent, status: 'failed', output: out })
    }
  } else if (e.type === 'complete') {
    t.thinking!.status = 'done'
    if (e.output) {
      messages.value.push({ role: 'assistant', text: e.output, agent: 'supervisor' })
    }
  } else if (e.type === 'pending_commit' && e.count) {
    pendingCommit.value = { count: e.count, records: e.records }
  } else if (e.type === 'error') {
    t.thinking!.status = 'done'
  }
}

// 触发多 Agent 主从编排：Supervisor 拆解 → 派发子 Agent → 回收 → 综合。
// 同样内联成「思考过程」消息，与自动升级体验一致。
function triggerOrchestrate(inputText: string) {
  if (orchestrating.value) return
  const msg = inputText || '请帮我生成本周的个人训练周报'
  messages.value.push({ role: 'user', text: '【多 Agent】' + msg })
  orchestrating.value = true
  pendingCommit.value = null
  const t = pushThinking()
  orchestrate(msg, (e) => applyEvent(e, t))
}

function pickFile() {
  fileInput.value?.click()
}

async function handleImage(file: File) {
  if (!file.type.startsWith('image/')) return
  uploading.value = true
  messages.value.push({ role: 'user', text: '[图片] ' + file.name })
  try {
    const res: any = await importImage(file)
    if (res && res.ok && res.saved) {
      const d = res.data || {}
      let summary = '已导入一条训练记录'
      if (d.type === 'run') summary = `已导入跑步：${d.distance_km} km / ${d.duration_min} 分`
      else if (d.type === 'strength') summary = `已导入力量训练（${(d.exercises || []).length} 个动作）`
      messages.value.push({ role: 'assistant', text: '[已导入] ' + summary })
    } else if (res && res.raw) {
      messages.value.push({
        role: 'assistant',
        text: '未能识别结构化训练数据。OCR 原文：\n' + String(res.raw).slice(0, 300),
      })
    } else {
      messages.value.push({ role: 'assistant', text: '[导入失败] ' + (res?.error || '未知错误') })
    }
  } catch (e) {
    messages.value.push({ role: 'assistant', text: '请求失败：' + String(e) })
  } finally {
    uploading.value = false
  }
}

function onFileChange(e: Event) {
  const f = (e.target as HTMLInputElement).files?.[0]
  if (f) handleImage(f)
  ;(e.target as HTMLInputElement).value = ''
}

onMounted(() => {
  ensureSession()
  refreshConn()
  loadUserMemory()
})
</script>

<style scoped>
.chat-module {
  display: flex;
  flex: 1;
  min-width: 0;
  height: 100vh;
}
.chat-page {
  flex: 1;
  min-width: 0;
  display: flex;
  justify-content: center;
}
.chat {
  width: 100%;
  max-width: 1000px;
  padding: 16px 28px;
  font-family: system-ui, -apple-system, 'Segoe UI', sans-serif;
  display: flex;
  flex-direction: column;
  height: 100vh;
  box-sizing: border-box;
}
.right-rail {
  display: flex;
  flex: none;
  height: 100vh;
}
</style>
