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
  type MemoryEntry,
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
  const profile = ref<MemoryEntry[]>([])

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
      // error 事件带 message（如「编排失败：DeepSeek 超时」）。以前只把 thinking 标 done，
      // 用户看到的是「转圈停了 + 页面空白」，属于无感知失败——这里把原因说出来。
      t.thinking!.status = 'done'
      messages.value.push({
        role: 'assistant',
        text: e.message || '编排失败，请稍后重试',
        agent: 'supervisor',
      })
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
      } else if (res && res.ok && res.staged) {
        // 后端已改成「先暂存、确认后入库」：saved 恒为 false，成功信号是 staged。
        // 以前只认 res.saved，于是每次导入都掉进下面的「导入失败」分支——
        // 后端明明有待确认记录，用户却只看到失败、也找不到入库入口（闭环断在中间）。
        const d = res.data || {}
        let summary = '一条训练记录'
        if (d.type === 'run') summary = `跑步：${d.distance_km} km / ${d.duration_min} 分`
        else if (d.type === 'strength') summary = `力量训练（${(d.exercises || []).length} 个动作）`
        // 累加而不是覆盖：连传两张截图时，后一张不能把前一张的待确认记录顶掉
        // （否则卡片只报 1 条，另一条留在服务端、再也提交不了）。
        const prev = pendingCommit.value?.records || []
        const merged = prev.concat(res.staged_records || [])
        pendingCommit.value = { count: merged.length, records: merged }
        messages.value.push({
          role: 'assistant',
          text: `[已解析，待确认] ${summary}\n还没有入库：请核对下方「待确认训练记录」，无误后再点确认。`,
        })
      } else if (res && res.ok) {
        // 解析成功但没能进待确认队列（类型不认识 / 力量动作列表为空）
        messages.value.push({
          role: 'assistant',
          text: '[未入库] ' + (res.save_error || '已解析出内容，但不属于可入库的训练记录类型'),
        })
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
      // 后端落库失败时返回 ok:false + kept:true（暂存记录仍留在服务端）——
      // 此时别把待确认卡片收掉，否则记录虽在、用户却找不到重试入口。
      if (r.kept) return
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
