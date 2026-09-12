<template>
  <header class="hd">
    <span class="ava">
      <span v-html="COACH_ICON" />
      <i class="live" :class="conn" />
    </span>
    <div class="who">
      <h1 class="name">谭成义 <span class="role">· 训练助理</span></h1>
      <p class="stat">
        <StatusDot :status="conn" />
        <span class="txt">{{ connText }}</span>
      </p>
    </div>

    <div class="right">
      <AppPill tone="ok" size="sm" :outline="true">
        <span class="dot-local" />本地数据 · 不上传
      </AppPill>
    </div>
  </header>
</template>

<script setup lang="ts">
import StatusDot from '../ui/StatusDot.vue'
import AppPill from '../ui/AppPill.vue'

defineProps<{ conn: 'checking' | 'ok' | 'err'; connText: string }>()

const COACH_ICON =
  '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M5 8.5c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2v7c0 1.1-.9 2-2 2H7c-1.1 0-2-.9-2-2z"/><path d="M6.5 6V5a1.5 1.5 0 0 1 1.5-1.5h8A1.5 1.5 0 0 1 17.5 5v1"/><path d="M9 13.5h6"/></svg>'
</script>

<style scoped>
.hd {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
  padding: var(--sp-3) 0 var(--sp-4);
  border-bottom: 1px solid var(--line);
  margin-bottom: var(--sp-5);
}
.ava {
  position: relative;
  width: 38px;
  height: 38px;
  flex: none;
  display: grid;
  place-items: center;
  border-radius: var(--r-md);
  color: #ffb08a;
  background: linear-gradient(180deg, rgba(255, 122, 69, 0.18), rgba(255, 122, 69, 0.08));
  border: 1px solid rgba(255, 122, 69, 0.3);
  box-shadow: var(--hairline-top);
}
.ava :deep(svg) {
  width: 20px;
  height: 20px;
}
/* 连接状态角标 */
.live {
  position: absolute;
  right: -3px;
  bottom: -3px;
  width: 11px;
  height: 11px;
  border-radius: 50%;
  border: 2px solid var(--surface-0);
  background: var(--ink-4);
}
.live.ok {
  background: var(--ok);
}
.live.err {
  background: var(--danger);
}
.live.checking {
  background: var(--warn);
  animation: breathe 1.4s var(--ease-out) infinite;
}

.who {
  min-width: 0;
}
.name {
  font-size: var(--fs-md);
  font-weight: var(--fw-semi);
  color: var(--ink);
  letter-spacing: -0.01em;
}
.role {
  font-size: var(--fs-sm);
  font-weight: var(--fw-normal);
  color: var(--ink-3);
}
.stat {
  display: flex;
  align-items: center;
  gap: 7px;
  margin-top: 3px;
}
.txt {
  font-size: var(--fs-xs);
  color: var(--ink-4);
}

.right {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: var(--sp-2);
}
.dot-local {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: currentColor;
}
</style>
