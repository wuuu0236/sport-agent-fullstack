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
      <div class="role">{{ m.role === 'user' ? '我' : '助理' }}</div>
      <div class="text md" v-html="renderMarkdown(m.text)"></div>
      <div v-if="m.agent" class="agent">→ {{ m.agent }} agent</div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, watch, nextTick } from 'vue'
import { renderMarkdown } from '../utils/markdown'
import type { Msg } from '../types'

const props = defineProps<{ messages: Msg[] }>()

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
  font-size: 44px;
  margin-bottom: 12px;
  opacity: 0.9;
}
.empty-title {
  font-size: 16px;
  font-weight: 600;
  color: var(--text-soft);
  margin-bottom: 6px;
}
.empty-sub {
  font-size: 13px;
  color: var(--faint);
}
.msg {
  max-width: 82%;
  padding: 8px 12px;
  border-radius: 12px;
  white-space: pre-wrap;
  line-height: 1.55;
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
  font-size: 12px;
  color: var(--faint);
  margin-bottom: 2px;
}
.agent {
  font-size: 12px;
  color: var(--faint);
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
  background: var(--code-bg);
  padding: 1px 5px;
  border-radius: 4px;
  font-size: 12px;
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
  margin: 8px 0;
  font-size: 13px;
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
