// 对话与多 Agent 编排（从原 Chat.vue 的 setup 中抽离）
// 职责：连接检测 / 发消息 / 编排 SSE 事件渲染 / 截图导入 / 暂存确认 / 用户画像
import { ref, type Ref } from 'vue'
import type { Msg, ThinkingStep } from '../types'
import {
  sendChat,
  checkHealth,
  importImage,
  orchestrate,
  commitRecords,
  getMemory,
  type OrchestrateEvent,
} from '../api/client'
import { agentMeta } from '../constants/agents'

export interface PendingCommit {
  count: number
  records?: any[]
}

export function useAgentChat(opts: {
  messages: Ref<Msg[]>
  /** 首条消息发出时回调：用于把「新会话」重命名为问题标题 */
  onFirstMessage?: (text: string) => void
}) {
  const { messages } = opts

  const busy = ref(false)
  const uploading = ref(false)
  const orchestrating = ref(false)
  const conn = ref<'checking' | 'ok' | 'err'>('checking')
  const connText = ref('连接检测中')
  const pendingCommit = ref<PendingCommit | null>(null)
  const profile = ref<string[]>([])

  // ---------- 连接状态 ----------
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

  // ---------- 用户画像（USER 长期记忆） ----------
  async function loadProfile() {
    try {
      const d = await getMemory()
      profile.value = d.user || []
    } catch {
      profile.value = []
    }
  }

  // ---------- 编排事件 → 内联时间轴 ----------
  function pushThinking(): Msg {
    const t: Msg = { role: 'thinking', thinking: { steps: [], status: 'running' } }
    messages.value.push(t)
    return t
  }

  function stepOf(steps: ThinkingStep[], name: string): ThinkingStep {
    let s = steps.find((x) => x.name === name)
    if (!s) {
      s = { name, label: agentMeta(name).label, status: 'idle' }
      steps.push(s)
    }
    return s
  }

  // Supervisor 派发哪个子 Agent 就显示哪个；单节点失败标红但不中断整条链
  function applyEvent(e: OrchestrateEvent, t: Msg) {
    const steps = t.thinking!.steps
    if (e.type === 'plan' && e.steps) {
      for (const n of e.steps) stepOf(steps, n)
    } else if (e.type === 'agent_start' && e.agent) {
      stepOf(steps, e.agent).status = 'running'
    } else if (e.type === 'agent_done' && e.agent) {
      const s = stepOf(steps, e.agent)
      s.status = 'done'
      s.output = e.output || ''
    } else if (e.type === 'agent_error' && e.agent) {
      const s = stepOf(steps, e.agent)
      s.status = 'failed'
      s.output = e.error || e.output || '节点失败'
    } else if (e.type === 'complete') {
      t.thinking!.status = 'done'
      if (e.output) {
        messages.value.push({ role: 'assistant', text: e.output, agent: 'supervisor' })
      }
    } else if (e.type === 'pending_commit' && e.count) {
      pendingCommit.value = { count: e.count, records: e.records }
      t.thinking!.status = 'done'
    } else if (e.type === 'error') {
      t.thinking!.status = 'done'
    }
  }

  // ---------- 发消息（后端返回 events 时自动升级为编排展示） ----------
  async function send(text: string) {
    const t = text.trim()
    if (!t || busy.value) return
    messages.value.push({ role: 'user', text: t })
    if (messages.value.length === 1) opts.onFirstMessage?.(t)

    busy.value = true
    try {
      const data = await sendChat(t)
      if (data.events && data.events.length) {
        // 编排事件按 90ms 节奏依次渲染，模拟实时协作过程
        orchestrating.value = true
        pendingCommit.value = null
        const trace = pushThinking()
        const sleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms))
        for (let i = 0; i < data.events.length; i++) {
          applyEvent(data.events[i], trace)
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
      loadProfile() // 对话可能触发记忆写入，刷新右下角用户画像
    }
  }

  /** 手动触发多 Agent 主从编排（SSE 实时事件） */
  function orchestrateNow(inputText: string) {
    if (orchestrating.value) return
    const msg = (inputText || '').trim() || '请帮我生成本周的个人训练周报'
    messages.value.push({ role: 'user', text: '【多 Agent 编排】' + msg })
    orchestrating.value = true
    pendingCommit.value = null
    const trace = pushThinking()
    orchestrate(msg, (e) => {
      applyEvent(e, trace)
      if (e.type === 'complete' || e.type === 'error') orchestrating.value = false
    })
  }

  // ---------- 截图导入（本地 OCR） ----------
  async function importFile(file: File) {
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

  // ---------- 暂存记录确认入库 ----------
  async function commit() {
    const recs = pendingCommit.value?.records
    try {
      const r = await commitRecords(recs?.length ? recs : undefined)
      messages.value.push({ role: 'assistant', text: r.msg || '已处理', agent: 'supervisor' })
    } catch (e) {
      messages.value.push({ role: 'assistant', text: '确认失败：' + String(e), agent: 'supervisor' })
    }
    pendingCommit.value = null
  }

  function dismissCommit() {
    pendingCommit.value = null
  }

  return {
    busy,
    uploading,
    orchestrating,
    conn,
    connText,
    pendingCommit,
    profile,
    refreshConn,
    loadProfile,
    send,
    orchestrateNow,
    importFile,
    commit,
    dismissCommit,
  }
}
