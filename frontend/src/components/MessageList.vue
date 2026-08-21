<template>
  <div class="messages" ref="msgBox">
    <div v-if="!messages.length" class="empty">
      <div class="empty-icon">🏃</div>
      <div class="empty-title">开始你的第一次对话</div>
      <div class="empty-sub">
        记录训练、分析数据、生成周报，或拖入一张训练截图
      </div>
    </div>
    <div v-for="(m, i) in messages" :key="i" :class="['msg', m.role]">
      <!-- 多 Agent 协作「思考过程」：内联在对话流里，可折叠 -->
      <template v-if="m.role === 'thinking'">
        <div class="role">🤔 多 Agent 协作过程</div>
        <div class="thinking-card">
          <div
            v-for="s in (m.thinking?.steps || [])"
            :key="s.name"
            class="t-step"
            :class="s.status"
          >
            <span class="t-dot"></span>
            <span class="t-label">{{ s.label }}</span>
            <span class="t-state">{{ stateText(s.status) }}</span>
            <div v-if="s.output" class="t-out">{{ truncate(s.output, 120) }}</div>
          </div>
          <div v-if="pendingCommit" class="t-pending">
            📥 主 Agent 解析出 <b>{{ pendingCommit.count }}</b> 条训练记录（暂存，未落库）
            <div class="t-pending-actions">
              <button class="t-btn" @click="$emit('commit')">确认入库</button>
              <button class="t-btn ghost" @click="$emit('dismissCommit')">暂不</button>
            </div>
          </div>
        </div>
      </template>

      <template v-else>
        <div class="role">{{ m.role === 'user' ? '我' : '助理' }}</div>
        <div class="text md" v-html="renderMarkdown(m.text || '')"></div>
        <div v-if="m.agent" class="agent">→ {{ m.agent }} agent</div>
      </template>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, watch, nextTick } from 'vue'
import { renderMarkdown } from '../utils/markdown'
import type { Msg } from '../types'

const props = defineProps<{
  messages: Msg[]
  pendingCommit?: { count: number; records?: any[] } | null
}>()
const emit = defineEmits<{
  (e: 'commit'): void
  (e: 'dismissCommit'): void
}>()

// 自动下滑：新消息进来滚到底部，第一时间看到输出
const msgBox = ref<HTMLElement | null>(null)
async function scrollToBottom() {
  await nextTick()
  if (msgBox.value) msgBox.value.scrollTop = msgBox.value.scrollHeight
}
watch(
  () => props.messages,
  () => scrollToBottom(),
  { deep: true },
)

// 子 Agent 状态文案（原 AgentBoard 逻辑迁移到内联思考过程）
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
.messages {
  flex: 1;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin: 16px 0;
  scrollbar-width: thin;
  scrollbar-color: var(--border) transparent;
}
.empty {
  margin: auto;
  text-align: center;
  color: var(--muted);
  padding: 40px 0;
}
.empty-icon {
  font-size: 60px;
  margin-bottom: 16px;
  opacity: 0.9;
}
.empty-title {
  font-size: 21px;
  font-weight: 600;
  color: var(--text-soft);
  margin-bottom: 10px;
}
.empty-sub {
  font-size: 15px;
  color: var(--faint);
}
.msg {
  max-width: 84%;
  padding: 10px 14px;
  border-radius: 12px;
  white-space: pre-wrap;
  line-height: 1.6;
  font-size: 14px;
  border: 1px solid transparent;
}
.msg.user {
  align-self: flex-end;
  background: var(--user-msg);
  border-color: var(--msg-border);
  border-bottom-right-radius: 4px;
}
.msg.assistant {
  align-self: flex-start;
  background: var(--assistant-msg);
  border-color: var(--msg-border);
  border-bottom-left-radius: 4px;
}
.role {
  font-size: 14px;
  color: var(--faint);
  margin-bottom: 3px;
}
.agent {
  font-size: 14px;
  color: var(--faint);
  margin-top: 5px;
}
/* 内联「思考过程」卡片（替代原右侧 AgentBoard 模块） */
.msg.thinking {
  background: var(--assistant-msg);
  border-color: var(--msg-border);
  border-bottom-left-radius: 4px;
  max-width: 92%;
}
.thinking-card {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-top: 2px;
}
.t-step {
  display: grid;
  grid-template-columns: 12px 1fr auto;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  padding: 4px 0;
}
.t-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--faint);
}
.t-step.running .t-dot {
  background: var(--node-running);
  animation: tpulse 1.3s infinite;
}
.t-step.done .t-dot {
  background: var(--node-done);
}
.t-step.failed .t-dot {
  background: var(--node-failed);
}
@keyframes tpulse {
  0% { box-shadow: 0 0 0 0 rgba(72, 187, 120, 0.45); }
  70% { box-shadow: 0 0 0 5px rgba(72, 187, 120, 0); }
  100% { box-shadow: 0 0 0 0 rgba(72, 187, 120, 0); }
}
.t-label {
  font-weight: 600;
  color: var(--text-soft);
}
.t-state {
  color: var(--muted);
  font-size: 12px;
}
.t-step.running .t-state {
  color: var(--node-running);
}
.t-step.done .t-state {
  color: var(--node-done);
}
.t-step.failed .t-state {
  color: var(--node-failed);
}
.t-out {
  grid-column: 1 / -1;
  margin-top: 2px;
  font-size: 12px;
  color: var(--muted);
  white-space: pre-wrap;
}
.t-pending {
  margin-top: 6px;
  background: color-mix(in srgb, var(--warn) 12%, var(--card));
  border: 1px solid color-mix(in srgb, var(--warn) 45%, transparent);
  border-radius: 10px;
  padding: 10px 12px;
  font-size: 13px;
  line-height: 1.6;
  color: var(--text-soft);
}
.t-pending-actions {
  margin-top: 6px;
  display: flex;
  gap: 8px;
}
.t-btn {
  background: var(--accent);
  color: #fff;
  border: 0;
  border-radius: 8px;
  padding: 5px 14px;
  cursor: pointer;
  font-size: 13px;
}
.t-btn:hover {
  background: var(--accent-hover);
}
.t-btn.ghost {
  background: transparent;
  border: 1px solid var(--border);
  color: var(--muted);
}
.t-btn.ghost:hover {
  color: var(--text);
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
  margin: 12px 0 7px;
  line-height: 1.3;
}
.msg .text.md h1 {
  font-size: 20px;
}
.msg .text.md h2 {
  font-size: 18px;
}
.msg .text.md h3 {
  font-size: 16px;
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
  background: var(--code-bg);
  padding: 1px 6px;
  border-radius: 4px;
  font-size: 14px;
  font-family: 'SFMono-Regular', Consolas, monospace;
  color: var(--pre-text);
}
.msg .text.md pre {
  background: var(--pre-bg);
  color: var(--pre-text);
  padding: 10px;
  border-radius: 8px;
  overflow-x: auto;
  margin: 8px 0;
  border: 1px solid var(--border);
}
.msg .text.md pre code {
  background: none;
  color: inherit;
  padding: 0;
}
.msg .text.md blockquote {
  border-left: 3px solid var(--border);
  margin: 8px 0;
  padding: 2px 12px;
  color: var(--muted);
}
.msg .text.md hr {
  border: none;
  border-top: 1px solid var(--border);
  margin: 10px 0;
}
.msg .text.md table {
  border-collapse: collapse;
  width: 100%;
  margin: 10px 0;
  font-size: 14px;
}
.msg .text.md th,
.msg .text.md td {
  border: 1px solid var(--border);
  padding: 5px 8px;
  text-align: left;
}
.msg .text.md th {
  background: var(--bg-soft);
  font-weight: 600;
}
.msg .text.md a {
  color: var(--accent);
}
</style>
