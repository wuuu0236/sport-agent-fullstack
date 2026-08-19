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

        <!-- 多 Agent 协作链路看板：Supervisor 主 Agent 派发的子 Agent 实时状态（动态） -->
        <AgentBoard
          :showBoard="showBoard"
          :chainOrder="chainOrder"
          :chain="chain"
          :pendingCommit="pendingCommit"
          @commit="doCommit"
          @dismissCommit="pendingCommit = null"
        />

        <MessageList :messages="messages" />

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

    <!-- 右侧用户画像：USER 长期记忆（关于你的身份/偏好/训练基线） -->
    <UserProfileSidebar :entries="userMemory" />
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted, watch } from 'vue'
import HeaderBar from '../components/HeaderBar.vue'
import MessageList from '../components/MessageList.vue'
import ChatInput from '../components/ChatInput.vue'
import Dropzone from '../components/Dropzone.vue'
import AgentBoard from '../components/AgentBoard.vue'
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

// ---- 多 Agent 编排看板状态（动态：Supervisor 派发哪个子 Agent 就显示哪个）----
const chainOrder = ref<string[]>([])
const chain = reactive<Record<string, { status: string; output: string }>>({})
const showBoard = ref(false)
const orchestrating = ref(false)
const pendingCommit = ref<{ count: number; records?: any[] } | null>(null)

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
    messages.value.push({
      role: 'assistant',
      text: data.output ?? data.reply ?? '(无回复)',
      agent: data.agent,
    })
  } catch (e) {
    messages.value.push({ role: 'assistant', text: '请求失败：' + String(e) })
  } finally {
    busy.value = false
    loadUserMemory() // 对话可能触发记忆写入，刷新右侧用户画像
  }
}

// 触发多 Agent 主从编排：Supervisor 拆解 → 派发子 Agent → 回收 → 综合，SSE 实时刷新看板
function triggerOrchestrate(inputText: string) {
  if (orchestrating.value) return
  const msg = inputText || '请帮我生成本周的个人训练周报'
  messages.value.push({ role: 'user', text: '【多 Agent】' + msg })
  showBoard.value = true
  orchestrating.value = true
  pendingCommit.value = null
  chainOrder.value = []
  for (const k of Object.keys(chain)) delete chain[k]
  orchestrate(msg, (e) => {
    if (e.type === 'plan' && e.steps) {
      // Supervisor 已拆解出子任务序列，预置看板槽位
      chainOrder.value = e.steps
      for (const n of e.steps) chain[n] = { status: 'idle', output: '' }
    } else if (e.type === 'agent_start' && e.agent) {
      if (!chain[e.agent]) {
        chain[e.agent] = { status: 'running', output: '' }
        if (!chainOrder.value.includes(e.agent)) chainOrder.value.push(e.agent)
      } else {
        chain[e.agent] = { status: 'running', output: '' }
      }
    } else if (e.type === 'agent_done' && e.agent) {
      chain[e.agent] = { status: 'done', output: e.output || '' }
    } else if (e.type === 'agent_error' && e.agent) {
      // 单节点失败：看板标红，但不中断整条链；Supervisor 会如实注明缺失继续
      chain[e.agent] = { status: 'failed', output: e.error || e.output || '节点失败' }
    } else if (e.type === 'complete') {
      if (e.output) {
        messages.value.push({ role: 'assistant', text: e.output, agent: 'supervisor' })
      }
      orchestrating.value = false
    } else if (e.type === 'pending_commit' && e.count) {
      pendingCommit.value = { count: e.count, records: e.records }
    } else if (e.type === 'error') {
      orchestrating.value = false
    }
  })
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
  max-width: 860px;
  padding: 16px 24px;
  font-family: system-ui, -apple-system, 'Segoe UI', sans-serif;
  display: flex;
  flex-direction: column;
  height: 100vh;
  box-sizing: border-box;
}
</style>
