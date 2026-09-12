<template>
  <div class="tile" :class="[`tone-${tone}`, { compact }]">
    <div class="top">
      <span class="label">{{ label }}</span>
      <span v-if="icon" class="icon" v-html="icon"></span>
    </div>
    <div class="value-row">
      <span class="value num">{{ display }}</span>
      <span v-if="unit" class="unit">{{ unit }}</span>
    </div>
    <div v-if="hint || $slots.footer" class="hint">
      <slot name="footer">{{ hint }}</slot>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

// KPI 磁贴：大号数字 + 单位 + 可选图标/脚注
const props = withDefaults(
  defineProps<{
    label: string
    value: string | number | null | undefined
    unit?: string
    icon?: string
    hint?: string
    tone?: 'accent' | 'ok' | 'warn' | 'energy' | 'neutral'
    compact?: boolean
  }>(),
  { tone: 'accent', compact: false },
)

const display = computed(() => {
  const v = props.value
  if (v === null || v === undefined || v === '' || v === '—') return '—'
  return v
})
</script>

<style scoped>
.tile {
  position: relative;
  padding: var(--sp-5);
  border-radius: var(--r-lg);
  background: linear-gradient(180deg, var(--surface-3) 0%, var(--surface-2) 62%);
  border: 1px solid var(--line);
  box-shadow: var(--hairline-top), var(--shadow-2);
  overflow: hidden;
  transition: transform var(--t-base) var(--ease-out),
    border-color var(--t-base) var(--ease-out);
}
.tile:hover {
  transform: translateY(-2px);
  border-color: var(--line-3);
}

/* 右上角一轮柔光：颜色的语义暗示，不喧宾夺主 */
.tile::after {
  content: '';
  position: absolute;
  top: -46px;
  right: -46px;
  width: 130px;
  height: 130px;
  border-radius: 50%;
  opacity: 0.5;
  filter: blur(17px);
  pointer-events: none;
}
.tone-accent::after {
  background: radial-gradient(circle, rgba(61, 139, 255, 0.34), transparent 70%);
}
.tone-ok::after {
  background: radial-gradient(circle, rgba(53, 209, 138, 0.3), transparent 70%);
}
.tone-warn::after {
  background: radial-gradient(circle, rgba(240, 178, 60, 0.3), transparent 70%);
}
.tone-energy::after {
  background: radial-gradient(circle, rgba(255, 122, 69, 0.32), transparent 70%);
}

.top {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
}
.label {
  font-size: var(--fs-sm);
  color: var(--ink-3);
  letter-spacing: 0.01em;
}
.icon {
  margin-left: auto;
  width: 17px;
  height: 17px;
  color: var(--ink-4);
  display: inline-flex;
}
.icon :deep(svg) {
  width: 100%;
  height: 100%;
}

.value-row {
  display: flex;
  align-items: baseline;
  gap: 6px;
  margin-top: 10px;
}
.value {
  font-size: var(--fs-2xl);
  font-weight: var(--fw-bold);
  line-height: 1.05;
  letter-spacing: -0.02em;
  color: var(--ink);
}
/* 主色磁贴的数字用渐变文字，强化品牌识别 */
.tone-accent .value {
  background: var(--grad-accent);
  -webkit-background-clip: text;
  background-clip: text;
  -webkit-text-fill-color: transparent;
}
.tone-ok .value {
  color: var(--ok);
}
.tone-warn .value {
  color: var(--warn);
}
.tone-energy .value {
  color: var(--energy);
}

.unit {
  font-size: var(--fs-xs);
  color: var(--ink-4);
  white-space: nowrap;
}

.hint {
  margin-top: 9px;
  font-size: var(--fs-xs);
  color: var(--ink-4);
}

.compact {
  padding: var(--sp-4);
}
.compact .value {
  font-size: var(--fs-xl);
}
</style>
