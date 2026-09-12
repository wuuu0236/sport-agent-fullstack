<template>
  <div class="msg" :class="msg.role">
    <!-- 用户消息：右对齐气泡 -->
    <template v-if="msg.role === 'user'">
      <div class="bubble user">
        <p class="utext">{{ msg.text }}</p>
      </div>
    </template>

    <!-- 编排过程：多 Agent 时间轴 -->
    <template v-else-if="msg.role === 'thinking'">
      <ThinkingTrace
        :steps="msg.thinking?.steps ?? []"
        :status="msg.thinking?.status ?? 'running'"
      />
    </template>

    <!-- 助理消息：带头部的卡片式富文本 -->
    <template v-else>
      <div class="assistant-card">
        <header class="a-head">
          <span class="avatar" :style="{ '--h': meta.hue }">
            <span v-html="meta.icon" />
          </span>
          <div class="who">
            <span class="name">{{ meta.label }}</span>
            <span v-if="agent" class="tag">{{ agent }}</span>
          </div>
          <button class="copy" :class="{ ok: copied }" @click="copy">
            {{ copied ? '已复制' : '复制' }}
          </button>
        </header>
        <div class="prose" v-html="html" />
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import type { Msg } from '../../types'
import { renderMarkdown } from '../../utils/markdown'
import { agentMeta } from '../../constants/agents'
import ThinkingTrace from './ThinkingTrace.vue'

const props = defineProps<{ msg: Msg }>()

const agent = computed(() => props.msg.agent)
const meta = computed(() => agentMeta(props.msg.agent))

const html = computed(() => renderMarkdown(props.msg.text || ''))

const copied = ref(false)
async function copy() {
  try {
    await navigator.clipboard.writeText(props.msg.text || '')
    copied.value = true
    setTimeout(() => (copied.value = false), 1400)
  } catch {
    /* 剪贴板不可用（非 https / 无权限）时静默 */
  }
}
</script>

<style scoped>
.msg {
  display: flex;
  width: 100%;
  animation: fade-up var(--t-slow) var(--ease-out) both;
}
.msg.user {
  justify-content: flex-end;
}

/* ---------- 用户气泡 ---------- */
.bubble.user {
  max-width: 78%;
  padding: 11px 15px;
  border-radius: var(--r-lg) var(--r-lg) var(--r-xs) var(--r-lg);
  background: linear-gradient(135deg, #2f6fd0 0%, #2b5aa8 100%);
  border: 1px solid rgba(255, 255, 255, 0.14);
  box-shadow: var(--hairline-top), var(--shadow-2);
}
.utext {
  font-size: var(--fs-base);
  line-height: var(--lh-normal);
  color: #f2f7ff;
  white-space: pre-wrap;
  word-break: break-word;
}

/* ---------- 助理卡片 ---------- */
.assistant-card {
  max-width: 100%;
  width: 100%;
  padding: var(--sp-4) var(--sp-5) var(--sp-5);
  border-radius: var(--r-lg);
  background: color-mix(in srgb, var(--surface-2) 88%, transparent);
  border: 1px solid var(--line);
  box-shadow: var(--hairline-top), var(--shadow-1);
  backdrop-filter: blur(8px);
}
.a-head {
  display: flex;
  align-items: center;
  gap: 10px;
  padding-bottom: 12px;
  margin-bottom: 14px;
  border-bottom: 1px solid var(--line);
}
.avatar {
  width: 27px;
  height: 27px;
  flex: none;
  display: grid;
  place-items: center;
  border-radius: var(--r-sm);
  color: var(--h);
  background: color-mix(in srgb, var(--h) 15%, transparent);
  border: 1px solid color-mix(in srgb, var(--h) 30%, transparent);
}
.avatar :deep(svg) {
  width: 15px;
  height: 15px;
}
.who {
  display: flex;
  align-items: baseline;
  gap: 8px;
  min-width: 0;
}
.name {
  font-size: var(--fs-sm);
  font-weight: var(--fw-semi);
  color: var(--ink);
}
.tag {
  font-family: var(--font-mono);
  font-size: 10.5px;
  color: var(--ink-4);
  background: var(--surface-4);
  padding: 1px 6px;
  border-radius: var(--r-xs);
  border: 1px solid var(--line);
}
.copy {
  margin-left: auto;
  flex: none;
  font-size: 11px;
  color: var(--ink-4);
  padding: 3px 9px;
  border-radius: var(--r-full);
  border: 1px solid transparent;
  transition: color var(--t-fast) var(--ease-out), border-color var(--t-fast) var(--ease-out),
    background var(--t-fast) var(--ease-out);
}
.copy:hover {
  color: var(--ink-2);
  border-color: var(--line-2);
  background: var(--surface-3);
}
.copy.ok {
  color: var(--ok);
  border-color: rgba(53, 209, 138, 0.35);
}
</style>
