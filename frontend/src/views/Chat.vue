<template>
  <div class="chat">
    <header>
      <span class="title">个人体育训练助理</span>
      <span class="conn" :class="conn">
        <i class="dot"></i>{{ connText }}
      </span>
    </header>

    <!-- 多 Agent 协作链路看板：Supervisor 主 Agent 派发的子 Agent 实时状态（动态） -->
    <div v-if="showBoard" class="board">
      <div class="board-title">多 Agent 协作链路（Supervisor → 子 Agent）</div>
      <div class="nodes">
        <div v-for="n in chainOrder" :key="n" class="node" :class="chain[n].status">
          <div class="node-head">
            <span class="node-name">{{ nodeLabel[n] || n }}</span>
            <span class="node-state">{{ stateText(chain[n].status) }}</span>
          </div>
          <div v-if="chain[n].output" class="node-out">{{ truncate(chain[n].output, 160) }}</div>
        </div>
      </div>
      <div v-if="pendingCommit" class="pending">
        📥 主 Agent 编排解析出 <b>{{ pendingCommit.count }}</b> 条训练记录（暂存，未落库）
        <div class="pending-actions">
          <button class="p-btn" @click="doCommit">确认入库</button>
          <button class="p-btn ghost" @click="pendingCommit = null">暂不</button>
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

    <div class="messages" ref="msgBox">
      <div v-for="(m, i) in messages" :key="i" :class="['msg', m.role]">
        <div class="role">{{ m.role === 'user' ? '我' : '助理' }}</div>
        <div class="text md" v-html="rendered(m.text)"></div>
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
import { ref, reactive, onMounted, watch, nextTick } from 'vue'
import MarkdownIt from 'markdown-it'
import { sendChat, checkHealth, importImage, orchestrate, getSessions, commitRecords } from '../api/client'

// Markdown 渲染：把 DeepSeek 输出的 Markdown（#、**、表格、--- 等）渲染成富文本
// html:false 会转义原始 HTML，避免 LLM 输出里的标签造成 XSS
const md = new MarkdownIt({ html: false, linkify: true, breaks: true })
function rendered(text: string): string {
  if (!text) return ''
  try {
    return md.render(text)
  } catch {
    return text
  }
}

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

// 自动下滑：新消息进来（聊天/图片导入/编排终稿）滚到底部，第一时间看到输出过程
const msgBox = ref<HTMLElement | null>(null)
async function scrollToBottom() {
  await nextTick()
  if (msgBox.value) msgBox.value.scrollTop = msgBox.value.scrollHeight
}
watch(messages, () => scrollToBottom())

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

// ---- 多 Agent 编排看板状态（动态：Supervisor 派发哪个子 Agent 就显示哪个）----
const nodeLabel: Record<string, string> = {
  recorder: 'recorder · 记录',
  analyst: 'analyst · 分析',
  searcher: 'searcher · 搜索',
  clinician: 'clinician · 康复排查',
  expert: 'expert · 运动科学',
  planner: 'planner · 计划编排',
  memory: 'memory · 记忆',
  scheduler: 'scheduler · 日程',
  writer: 'writer · 润色',
  general: 'general · 通用',
  supervisor: 'supervisor · 主Agent',
}
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

function stateText(s: string) {
  return (
    ({ idle: '等待', running: '执行中…', done: '完成', failed: '失败' } as Record<string, string>)[s] || s
  )
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

// 触发多 Agent 主从编排：Supervisor 拆解 → 派发子 Agent → 回收 → 综合，SSE 实时刷新看板
function triggerOrchestrate() {
  if (orchestrating.value) return
  const msg = input.value.trim() || '请帮我生成本周的个人训练周报'
  messages.value.push({ role: 'user', text: '【生成周报】' + msg })
  input.value = ''
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
.node.failed {
  border-color: #d23b3b;
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
.node.failed .node-state {
  color: #d23b3b;
}
.node-out {
  margin-top: 6px;
  font-size: 12px;
  color: #555;
  white-space: pre-wrap;
  max-height: 80px;
  overflow-y: auto;
}
.pending {
  margin-top: 10px;
  background: #fff8ec;
  border: 1px solid #ffe2b8;
  border-radius: 10px;
  padding: 10px 12px;
  font-size: 13px;
  line-height: 1.6;
}
.pending-actions {
  margin-top: 8px;
  display: flex;
  gap: 8px;
}
.p-btn {
  background: #2f6df0;
  color: #fff;
  border: 0;
  border-radius: 8px;
  padding: 6px 14px;
  cursor: pointer;
  font-size: 13px;
}
.p-btn.ghost {
  background: #eef1f6;
  color: #5b6577;
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
/* Markdown 渲染样式 */
.msg .text.md {
  white-space: normal;
  display: block;
}
.msg .text.md :first-child {
  margin-top: 0;
}
.msg .text.md :last-child {
  margin-bottom: 0;
}
.msg .text.md h1,
.msg .text.md h2,
.msg .text.md h3 {
  margin: 10px 0 6px;
  line-height: 1.3;
}
.msg .text.md h1 {
  font-size: 18px;
}
.msg .text.md h2 {
  font-size: 16px;
}
.msg .text.md h3 {
  font-size: 15px;
}
.msg .text.md p {
  margin: 6px 0;
}
.msg .text.md ul,
.msg .text.md ol {
  margin: 6px 0;
  padding-left: 22px;
}
.msg .text.md li {
  margin: 2px 0;
}
.msg .text.md strong {
  font-weight: 700;
}
.msg .text.md code {
  background: #e8e8ea;
  padding: 1px 5px;
  border-radius: 4px;
  font-size: 12px;
  font-family: 'SFMono-Regular', Consolas, monospace;
}
.msg .text.md pre {
  background: #2b2b2b;
  color: #f1f1f1;
  padding: 10px;
  border-radius: 8px;
  overflow-x: auto;
  margin: 8px 0;
}
.msg .text.md pre code {
  background: none;
  color: inherit;
  padding: 0;
}
.msg .text.md blockquote {
  border-left: 3px solid #c4cdd6;
  margin: 8px 0;
  padding: 2px 12px;
  color: #555;
}
.msg .text.md hr {
  border: none;
  border-top: 1px solid #ddd;
  margin: 10px 0;
}
.msg .text.md table {
  border-collapse: collapse;
  width: 100%;
  margin: 8px 0;
  font-size: 13px;
}
.msg .text.md th,
.msg .text.md td {
  border: 1px solid #ddd;
  padding: 5px 8px;
  text-align: left;
}
.msg .text.md th {
  background: #eef2f6;
  font-weight: 600;
}
.msg .text.md a {
  color: #185fa5;
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
