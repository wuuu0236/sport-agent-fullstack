<template>
  <div class="chat">
    <header>
      <span class="title">个人体育训练助理</span>
      <span class="conn" :class="conn">
        <i class="dot"></i>{{ connText }}
      </span>
    </header>

    <!-- 多 Agent 协作链路看板：编排时实时显示 research -> coach -> writer 的状态 -->
    <div v-if="showBoard" class="board">
      <div class="board-title">多 Agent 协作链路</div>
      <div class="nodes">
        <div v-for="n in nodeOrder" :key="n" class="node" :class="chain[n].status">
          <div class="node-head">
            <span class="node-name">{{ nodeLabel[n] }}</span>
            <span class="node-state">{{ stateText(chain[n].status) }}</span>
          </div>
          <div v-if="chain[n].output" class="node-out">{{ truncate(chain[n].output, 160) }}</div>
        </div>
      </div>
    </div>

    <!-- 最近训练记录（持久化在后端，前端只读展示，解决『打开看不到训练记忆』） -->
    <div v-if="recentSessions.length" class="sessions">
      <div class="board-title">最近训练</div>
      <div v-for="s in recentSessions" :key="s.date + s.summary" class="sess">
        <span class="sess-date">{{ s.date }}</span>
        <span class="sess-sum">{{ s.summary }}</span>
      </div>
    </div>

    <div class="messages">
      <div v-for="(m, i) in messages" :key="i" :class="['msg', m.role]">
        <div class="role">{{ m.role === 'user' ? '我' : '助理' }}</div>
        <div class="text">{{ m.text }}</div>
        <div v-if="m.agent" class="agent">→ {{ m.agent }} agent</div>
      </div>
    </div>

    <div
      class="dropzone"
      :class="{ over: dragOver }"
      @click="pickFile"
      @dragover.prevent="dragOver = true"
      @dragleave.prevent="dragOver = false"
      @drop.prevent="onDrop"
    >
      <span v-if="!uploading">把训练截图拖到这里，或点击选择图片（本地 OCR，不上传）</span>
      <span v-else>正在识别截图…</span>
      <input ref="fileInput" type="file" accept="image/*" hidden @change="onFileChange" />
    </div>

    <div class="input">
      <textarea
        v-model="input"
        @keyup.enter.exact.prevent="send"
        @paste="onPaste"
        placeholder="说点什么，比如「我昨天跑了 5 公里」"
      ></textarea>
      <button @click="send" :disabled="busy">发送</button>
      <button class="orchestrate" @click="triggerOrchestrate" :disabled="orchestrating">
        {{ orchestrating ? '编排中…' : '生成周报（多 Agent）' }}
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted, watch } from 'vue'
import { sendChat, checkHealth, importImage, orchestrate, getSessions } from '../api/client'

interface Msg {
  role: 'user' | 'assistant'
  text: string
  agent?: string
}

const STORAGE_KEY = 'sport-chat-history'
function loadHistory(): Msg[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    return raw ? (JSON.parse(raw) as Msg[]) : []
  } catch {
    return []
  }
}
// 聊天历史持久化到 localStorage：刷新/重开页面仍可看到之前的对话
const messages = ref<Msg[]>(loadHistory())
const input = ref('')
watch(
  messages,
  (v) => {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(v))
    } catch {
      /* 忽略写入失败（隐私模式等） */
    }
  },
  { deep: true },
)

// 最近训练记录（从 agent-service /sessions 拉取，前端只读展示）
const recentSessions = ref<any[]>([])
async function loadSessions() {
  try {
    const d = await getSessions(12)
    recentSessions.value = d.sessions || []
  } catch {
    recentSessions.value = []
  }
}
const busy = ref(false)
const uploading = ref(false)
const dragOver = ref(false)
const conn = ref<'checking' | 'ok' | 'err'>('checking')
const connText = ref('连接检测中')
const fileInput = ref<HTMLInputElement | null>(null)

// ---- 多 Agent 编排看板状态 ----
const nodeOrder = ['research', 'coach', 'writer'] as const
const nodeLabel: Record<string, string> = {
  research: 'research · 研究',
  coach: 'coach · 教练分析',
  writer: 'writer · 周报成文',
}
const chain = reactive<Record<string, { status: string; output: string }>>({
  research: { status: 'idle', output: '' },
  coach: { status: 'idle', output: '' },
  writer: { status: 'idle', output: '' },
})
const showBoard = ref(false)
const orchestrating = ref(false)

function stateText(s: string) {
  return ({ idle: '等待', running: '执行中…', done: '完成' } as Record<string, string>)[s] || s
}
function truncate(s: string, n: number) {
  return s && s.length > n ? s.slice(0, n) + '…' : s || ''
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

async function send() {
  const text = input.value.trim()
  if (!text || busy.value) return
  messages.value.push({ role: 'user', text })
  input.value = ''
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
  }
}

// 触发多 Agent 编排流水线：research -> coach -> writer，状态经 SSE 实时刷新看板
function triggerOrchestrate() {
  if (orchestrating.value) return
  const msg = input.value.trim() || '请帮我生成本周的个人训练周报'
  messages.value.push({ role: 'user', text: '【生成周报】' + msg })
  input.value = ''
  showBoard.value = true
  orchestrating.value = true
  for (const n of nodeOrder) chain[n] = { status: 'idle', output: '' }
  orchestrate(msg, (e) => {
    if (e.type === 'agent_start' && e.agent) {
      chain[e.agent] = { status: 'running', output: '' }
    } else if (e.type === 'agent_done' && e.agent) {
      chain[e.agent] = { status: 'done', output: e.output || '' }
      if (e.final) {
        messages.value.push({
          role: 'assistant',
          text: e.output || '(无输出)',
          agent: 'writer',
        })
        orchestrating.value = false
      }
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

function onDrop(e: DragEvent) {
  dragOver.value = false
  const f = e.dataTransfer?.files?.[0]
  if (f) handleImage(f)
}

function onPaste(e: ClipboardEvent) {
  const items = e.clipboardData?.items
  if (!items) return
  for (const it of items) {
    if (it.type.startsWith('image/')) {
      const f = it.getAsFile()
      if (f) {
        e.preventDefault()
        handleImage(f)
      }
      break
    }
  }
}

onMounted(() => {
  refreshConn()
  loadSessions()
})
</script>

<style scoped>
.chat {
  max-width: 760px;
  margin: 0 auto;
  padding: 16px;
  font-family: system-ui, -apple-system, 'Segoe UI', sans-serif;
  display: flex;
  flex-direction: column;
  height: 100vh;
  box-sizing: border-box;
}
header {
  font-weight: 600;
  font-size: 18px;
  padding-bottom: 12px;
  border-bottom: 1px solid #eee;
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.conn {
  font-size: 12px;
  font-weight: 400;
  display: flex;
  align-items: center;
  gap: 5px;
}
.conn .dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  display: inline-block;
  background: #bbb;
}
.conn.ok .dot {
  background: #2e9e4f;
}
.conn.err .dot {
  background: #d23b3b;
}
.conn.ok {
  color: #2e9e4f;
}
.conn.err {
  color: #d23b3b;
}
/* 多 Agent 协作看板 */
.board {
  border: 1px solid #e3e8ef;
  border-radius: 10px;
  padding: 12px;
  margin: 12px 0;
  background: #fafcfd;
}
.board-title {
  font-size: 13px;
  font-weight: 600;
  margin-bottom: 8px;
  color: #185fa5;
}
/* 最近训练记录 */
.sessions {
  border: 1px solid #e3e8ef;
  border-radius: 10px;
  padding: 12px;
  margin: 12px 0;
  background: #fafcfd;
}
.sess {
  display: flex;
  gap: 10px;
  font-size: 13px;
  padding: 4px 0;
  border-bottom: 1px dashed #eef2f6;
}
.sess:last-child {
  border-bottom: none;
}
.sess-date {
  color: #185fa5;
  font-weight: 600;
  white-space: nowrap;
}
.sess-sum {
  color: #555;
}
.nodes {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.node {
  border: 1px solid #e3e8ef;
  border-radius: 8px;
  padding: 8px 10px;
  background: #fff;
}
.node.running {
  border-color: #185fa5;
}
.node.done {
  border-color: #2e9e4f;
}
.node-head {
  display: flex;
  justify-content: space-between;
  font-size: 13px;
}
.node-name {
  font-weight: 600;
}
.node-state {
  font-size: 12px;
  color: #888;
}
.node.running .node-state {
  color: #185fa5;
}
.node.done .node-state {
  color: #2e9e4f;
}
.node-out {
  margin-top: 6px;
  font-size: 12px;
  color: #555;
  white-space: pre-wrap;
  max-height: 80px;
  overflow-y: auto;
}
.messages {
  flex: 1;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin: 16px 0;
}
.msg {
  max-width: 82%;
  padding: 8px 12px;
  border-radius: 10px;
  white-space: pre-wrap;
  line-height: 1.5;
}
.msg.user {
  align-self: flex-end;
  background: #e6f1fb;
}
.msg.assistant {
  align-self: flex-start;
  background: #f4f4f5;
}
.role {
  font-size: 12px;
  color: #999;
  margin-bottom: 2px;
}
.agent {
  font-size: 12px;
  color: #888;
  margin-top: 4px;
}
.dropzone {
  border: 1.5px dashed #c4cdd6;
  border-radius: 10px;
  padding: 14px;
  text-align: center;
  font-size: 13px;
  color: #6b7280;
  cursor: pointer;
  transition: background 0.15s, border-color 0.15s;
  margin-bottom: 10px;
}
.dropzone:hover {
  border-color: #185fa5;
  background: #f3f8fd;
}
.dropzone.over {
  border-color: #185fa5;
  background: #e6f1fb;
}
.input {
  display: flex;
  gap: 8px;
}
textarea {
  flex: 1;
  height: 52px;
  resize: none;
  padding: 8px;
  border: 1px solid #ddd;
  border-radius: 8px;
  font-family: inherit;
}
button {
  padding: 0 20px;
  border: none;
  border-radius: 8px;
  background: #185fa5;
  color: #fff;
  cursor: pointer;
}
button.orchestrate {
  background: #3b6d11;
}
button:disabled {
  opacity: 0.6;
  cursor: default;
}
</style>
