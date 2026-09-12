<template>
  <aside class="panel">
    <header class="p-head">
      <div>
        <h3 class="p-title">用户画像</h3>
        <p class="p-sub">来自长期记忆 <code>USER.md</code></p>
      </div>
      <button class="refresh" title="刷新" :class="{ spinning }" @click="reload">
        <span v-html="REFRESH_ICON" />
      </button>
    </header>

    <div class="p-body">
      <ul v-if="entries.length" class="facts">
        <li v-for="(e, i) in entries" :key="i" class="fact">
          <span class="mk" :class="'c' + (i % 4)" />
          <span class="tx">{{ e }}</span>
        </li>
      </ul>
      <div v-else class="none">
        <p>还没有写入画像</p>
        <span>对话中提到你的身体状况、目标或偏好，助理会记进 USER 记忆。</span>
      </div>
    </div>

    <footer class="p-foot">
      <span class="lock" v-html="LOCK_ICON" />
      数据只存本机，不上传
    </footer>
  </aside>
</template>

<script setup lang="ts">
import { ref } from 'vue'

const props = defineProps<{ entries: string[] }>()
const emit = defineEmits<{ reload: [] }>()

const STROKE =
  'fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"'
const REFRESH_ICON = `<svg viewBox="0 0 24 24" ${STROKE}><path d="M19.5 12a7.5 7.5 0 1 1-2.3-5.4"/><path d="M19.9 4.6v4.2h-4.2"/></svg>`
const LOCK_ICON = `<svg viewBox="0 0 24 24" ${STROKE}><rect x="5" y="10.4" width="14" height="9.6" rx="2.2"/><path d="M8.4 10.4V7.8a3.6 3.6 0 0 1 7.2 0v2.6"/></svg>`

const spinning = ref(false)
function reload() {
  spinning.value = true
  emit('reload')
  setTimeout(() => (spinning.value = false), 700)
}
</script>

<style scoped>
.panel {
  width: var(--panel-w);
  flex: none;
  height: 100vh;
  display: flex;
  flex-direction: column;
  background: color-mix(in srgb, var(--surface-1) 68%, transparent);
  backdrop-filter: blur(16px);
  border-left: 1px solid var(--line);
}

.p-head {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
  padding: var(--sp-5) var(--sp-4) var(--sp-4);
  border-bottom: 1px solid var(--line);
}
.p-title {
  font-size: var(--fs-base);
  font-weight: var(--fw-semi);
  color: var(--ink);
}
.p-sub {
  margin-top: 3px;
  font-size: 11px;
  color: var(--ink-4);
}
.p-sub code {
  font-family: var(--font-mono);
  font-size: 10px;
  padding: 1px 4px;
  border-radius: var(--r-xs);
  background: var(--surface-4);
  border: 1px solid var(--line);
}
.refresh {
  margin-left: auto;
  width: 27px;
  height: 27px;
  display: grid;
  place-items: center;
  border-radius: var(--r-sm);
  color: var(--ink-4);
  transition: color var(--t-fast) var(--ease-out), background var(--t-fast) var(--ease-out);
}
.refresh:hover {
  color: var(--accent-hi);
  background: var(--surface-3);
}
.refresh.spinning span {
  display: inline-flex;
  animation: spin 0.7s linear infinite;
}
.refresh :deep(svg) {
  width: 14px;
  height: 14px;
}

.p-body {
  flex: 1;
  overflow-y: auto;
  padding: var(--sp-4);
}

.facts {
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
}
.fact {
  display: flex;
  gap: 9px;
  padding: 10px 12px;
  border-radius: var(--r-md);
  background: var(--surface-2);
  border: 1px solid var(--line);
  transition: border-color var(--t-base) var(--ease-out),
    transform var(--t-base) var(--ease-out);
}
.fact:hover {
  transform: translateX(1px);
  border-color: var(--line-3);
}
/* 每条前的小圆点轮换 4 种语义色，让列表有节奏 */
.mk {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  flex: none;
  margin-top: 6px;
  background: var(--accent);
}
.mk.c1 {
  background: var(--accent-2);
}
.mk.c2 {
  background: var(--warn);
}
.mk.c3 {
  background: var(--energy);
}
.tx {
  font-size: var(--fs-sm);
  color: var(--ink-2);
  line-height: var(--lh-normal);
}

.none {
  padding: 30px 14px;
  text-align: center;
}
.none p {
  font-size: var(--fs-sm);
  color: var(--ink-3);
  font-weight: var(--fw-medium);
}
.none span {
  display: block;
  margin-top: 7px;
  font-size: var(--fs-xs);
  color: var(--ink-4);
  line-height: var(--lh-normal);
}

.p-foot {
  display: flex;
  align-items: center;
  gap: 7px;
  padding: var(--sp-3) var(--sp-4);
  border-top: 1px solid var(--line);
  font-size: 11px;
  color: var(--ink-4);
}
.lock {
  width: 13px;
  height: 13px;
  display: inline-flex;
  color: var(--ok);
}
.lock :deep(svg) {
  width: 100%;
  height: 100%;
}
</style>
