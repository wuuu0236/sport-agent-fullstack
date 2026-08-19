<template>
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
        <button class="p-btn" @click="emit('commit')">确认入库</button>
        <button class="p-btn ghost" @click="emit('dismissCommit')">暂不</button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
defineProps<{
  showBoard: boolean
  chainOrder: string[]
  chain: Record<string, { status: string; output: string }>
  pendingCommit: { count: number; records?: any[] } | null
}>()
const emit = defineEmits<{
  (e: 'commit'): void
  (e: 'dismissCommit'): void
}>()

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

function stateText(s: string) {
  return (
    ({ idle: '等待', running: '执行中…', done: '完成', failed: '失败' } as Record<string, string>)[s] || s
  )
}

function truncate(s: string, n: number) {
  return s && s.length > n ? s.slice(0, n) + '…' : s || ''
}
</script>

<style scoped>
.board {
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 14px;
  margin: 14px 0;
  background: color-mix(in srgb, var(--card) 85%, transparent);
}
.board-title {
  font-size: 15px;
  font-weight: 600;
  margin-bottom: 10px;
  color: var(--accent);
}
.nodes {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.node {
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 10px 12px;
  background: var(--node-bg);
}
.node.running {
  border-color: var(--node-running);
}
.node.done {
  border-color: var(--node-done);
}
.node.failed {
  border-color: var(--node-failed);
}
.node-head {
  display: flex;
  justify-content: space-between;
  font-size: 14px;
}
.node-name {
  font-weight: 600;
}
.node-state {
  font-size: 13px;
  color: var(--muted);
}
.node.running .node-state {
  color: var(--node-running);
}
.node.done .node-state {
  color: var(--node-done);
}
.node.failed .node-state {
  color: var(--node-failed);
}
.node-out {
  margin-top: 6px;
  font-size: 13px;
  color: var(--muted);
  white-space: pre-wrap;
  max-height: 80px;
  overflow-y: auto;
}
.pending {
  margin-top: 10px;
  background: color-mix(in srgb, var(--warn) 12%, var(--card));
  border: 1px solid color-mix(in srgb, var(--warn) 45%, transparent);
  border-radius: 10px;
  padding: 12px 14px;
  font-size: 14px;
  line-height: 1.6;
  color: var(--text-soft);
}
.pending-actions {
  margin-top: 8px;
  display: flex;
  gap: 8px;
}
.p-btn {
  background: var(--accent);
  color: #fff;
  border: 0;
  border-radius: 8px;
  padding: 7px 16px;
  cursor: pointer;
  font-size: 14px;
}
.p-btn:hover {
  background: var(--accent-hover);
}
.p-btn.ghost {
  background: transparent;
  border: 1px solid var(--border);
  color: var(--muted);
}
.p-btn.ghost:hover {
  color: var(--text);
}
</style>
