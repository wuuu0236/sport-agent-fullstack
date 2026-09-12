<template>
  <span class="pill" :class="[`tone-${tone}`, `size-${size}`, { outline }]">
    <i v-if="dot" class="d" />
    <slot />
  </span>
</template>

<script setup lang="ts">
// 徽章 / 标签：类型标记（跑步/力量）、状态、阶段
withDefaults(
  defineProps<{
    tone?: 'neutral' | 'accent' | 'ok' | 'warn' | 'danger' | 'energy'
    size?: 'sm' | 'md'
    dot?: boolean
    outline?: boolean
  }>(),
  { tone: 'neutral', size: 'sm', dot: false, outline: false },
)
</script>

<style scoped>
.pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  border-radius: var(--r-full);
  font-weight: var(--fw-medium);
  white-space: nowrap;
  border: 1px solid transparent;
  line-height: 1;
}
.size-sm {
  padding: 4px 9px;
  font-size: var(--fs-xs);
}
.size-md {
  padding: 6px 12px;
  font-size: var(--fs-sm);
}
.d {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: currentColor;
  flex: none;
}

.tone-neutral {
  background: var(--surface-4);
  color: var(--ink-2);
}
.tone-accent {
  background: rgba(61, 139, 255, 0.15);
  color: var(--accent-hi);
}
.tone-ok {
  background: rgba(53, 209, 138, 0.14);
  color: var(--ok);
}
.tone-warn {
  background: rgba(240, 178, 60, 0.15);
  color: var(--warn);
}
.tone-danger {
  background: rgba(255, 95, 86, 0.15);
  color: var(--danger);
}
.tone-energy {
  background: rgba(255, 122, 69, 0.15);
  color: var(--energy);
}
.outline {
  background: transparent;
  border-color: currentColor;
  opacity: 0.9;
}
</style>
