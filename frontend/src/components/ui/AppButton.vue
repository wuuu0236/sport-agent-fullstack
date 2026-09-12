<template>
  <button
    class="btn"
    :class="[`v-${variant}`, `s-${size}`, { block, loading: busy }]"
    :disabled="disabled || busy"
    :type="type"
    @click="$emit('click', $event)"
  >
    <span v-if="busy" class="spinner" />
    <span v-else-if="icon" class="ic" v-html="icon" />
    <span class="txt"><slot /></span>
  </button>
</template>

<script setup lang="ts">
// 通用按钮：primary（渐变主按钮）/ subtle（次级）/ ghost（纯文字）/ danger
withDefaults(
  defineProps<{
    variant?: 'primary' | 'subtle' | 'ghost' | 'danger'
    size?: 'sm' | 'md' | 'lg'
    disabled?: boolean
    busy?: boolean
    block?: boolean
    icon?: string
    type?: 'button' | 'submit'
  }>(),
  { variant: 'subtle', size: 'md', disabled: false, busy: false, block: false, type: 'button' },
)

defineEmits<{ click: [MouseEvent] }>()
</script>

<style scoped>
.btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 7px;
  border-radius: var(--r-md);
  font-weight: var(--fw-medium);
  white-space: nowrap;
  border: 1px solid transparent;
  transition: transform var(--t-fast) var(--ease-out),
    background var(--t-base) var(--ease-out), border-color var(--t-base) var(--ease-out),
    box-shadow var(--t-base) var(--ease-out), color var(--t-base) var(--ease-out);
}
.btn:active:not(:disabled) {
  transform: scale(0.975);
}
.btn:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}
.block {
  width: 100%;
}

.s-sm {
  padding: 6px 11px;
  font-size: var(--fs-sm);
  border-radius: var(--r-sm);
}
.s-md {
  padding: 9px 15px;
  font-size: var(--fs-base);
}
.s-lg {
  padding: 12px 20px;
  font-size: var(--fs-md);
  border-radius: var(--r-lg);
}

/* 主按钮：渐变 + 内高光 + 悬停上浮 */
.v-primary {
  background: var(--grad-accent);
  color: #06121f;
  font-weight: var(--fw-semi);
  box-shadow: var(--hairline-top), 0 8px 22px -10px rgba(61, 139, 255, 0.7);
}
.v-primary:hover:not(:disabled) {
  transform: translateY(-1px);
  box-shadow: var(--hairline-top), 0 12px 28px -10px rgba(61, 139, 255, 0.8);
}
.v-primary:hover:not(:disabled):active {
  transform: translateY(0) scale(0.975);
}

.v-subtle {
  background: var(--surface-3);
  border-color: var(--line-2);
  color: var(--ink);
  box-shadow: var(--hairline-top);
}
.v-subtle:hover:not(:disabled) {
  background: var(--surface-4);
  border-color: var(--line-3);
}

.v-ghost {
  background: transparent;
  color: var(--ink-3);
}
.v-ghost:hover:not(:disabled) {
  background: var(--surface-3);
  color: var(--ink);
}

.v-danger {
  background: rgba(255, 95, 86, 0.14);
  border-color: rgba(255, 95, 86, 0.3);
  color: var(--danger);
}
.v-danger:hover:not(:disabled) {
  background: rgba(255, 95, 86, 0.22);
}

.ic {
  width: 15px;
  height: 15px;
  display: inline-flex;
  flex: none;
}
.ic :deep(svg) {
  width: 100%;
  height: 100%;
}

.spinner {
  width: 13px;
  height: 13px;
  border-radius: 50%;
  border: 2px solid currentColor;
  border-top-color: transparent;
  animation: spin 0.7s linear infinite;
  flex: none;
}
</style>
