<template>
  <section class="app-card" :class="[`tone-${tone}`, { hoverable: hover, flush: pad === 'none' }]">
    <header v-if="title || $slots.actions || $slots.extra" class="head">
      <div class="head-text">
        <h3 v-if="title" class="title">{{ title }}</h3>
        <p v-if="subtitle" class="subtitle">{{ subtitle }}</p>
      </div>
      <div v-if="$slots.extra" class="extra"><slot name="extra" /></div>
      <div v-if="$slots.actions" class="actions"><slot name="actions" /></div>
    </header>
    <div class="body"><slot /></div>
    <footer v-if="$slots.footer" class="foot"><slot name="footer" /></footer>
  </section>
</template>

<script setup lang="ts">
// 通用卡片：分层表面 + 发丝内高光 + 柔和投影
// tone 用于语义强调（左侧渐变竖条），hover 用于可点击卡片
withDefaults(
  defineProps<{
    title?: string
    subtitle?: string
    tone?: 'neutral' | 'accent' | 'ok' | 'warn' | 'danger' | 'energy'
    pad?: 'sm' | 'md' | 'lg' | 'none'
    hover?: boolean
  }>(),
  { tone: 'neutral', pad: 'md', hover: false },
)
</script>

<style scoped>
.app-card {
  position: relative;
  background: var(--surface-2);
  border: 1px solid var(--line);
  border-radius: var(--r-lg);
  box-shadow: var(--hairline-top), var(--shadow-2);
  overflow: hidden;
  transition: border-color var(--t-base) var(--ease-out),
    transform var(--t-base) var(--ease-out), box-shadow var(--t-base) var(--ease-out);
}

/* 顶部一道极淡的横向渐隐光，让卡片有「被打光」的感觉 */
.app-card::before {
  content: '';
  position: absolute;
  inset: 0 0 auto 0;
  height: 1px;
  background: linear-gradient(
    90deg,
    transparent,
    rgba(255, 255, 255, 0.16),
    transparent
  );
  pointer-events: none;
}

.hoverable {
  cursor: pointer;
}
.hoverable:hover {
  transform: translateY(-1px);
  border-color: var(--line-3);
  box-shadow: var(--hairline-top), var(--shadow-3);
}

/* 语义色调：左侧 2px 渐变竖条 */
.tone-accent,
.tone-ok,
.tone-warn,
.tone-danger,
.tone-energy {
  padding-left: 2px;
}
.tone-accent::after,
.tone-ok::after,
.tone-warn::after,
.tone-danger::after,
.tone-energy::after {
  content: '';
  position: absolute;
  left: 0;
  top: 14px;
  bottom: 14px;
  width: 2px;
  border-radius: var(--r-full);
}
.tone-accent::after {
  background: var(--grad-accent);
}
.tone-ok::after {
  background: var(--ok);
}
.tone-warn::after {
  background: var(--warn);
}
.tone-danger::after {
  background: var(--danger);
}
.tone-energy::after {
  background: var(--energy);
}

.head {
  display: flex;
  align-items: flex-start;
  gap: var(--sp-3);
  padding: var(--sp-5) var(--sp-5) 0;
}
.head-text {
  min-width: 0;
}
.title {
  font-size: var(--fs-md);
  font-weight: var(--fw-semi);
  color: var(--ink);
  letter-spacing: -0.01em;
}
.subtitle {
  margin-top: 3px;
  font-size: var(--fs-sm);
  color: var(--ink-3);
}
.extra {
  margin-left: auto;
  flex: none;
}
.actions {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  flex: none;
}

.body {
  padding: var(--sp-5);
}
.head + .body {
  padding-top: var(--sp-4);
}
.pad-sm .body {
  padding: var(--sp-3) var(--sp-4);
}
.pad-lg .body {
  padding: var(--sp-6);
}
.flush .body {
  padding: 0;
}

.foot {
  padding: var(--sp-3) var(--sp-5);
  border-top: 1px solid var(--line);
  background: rgba(0, 0, 0, 0.16);
}
</style>
