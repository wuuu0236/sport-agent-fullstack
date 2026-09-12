<template>
  <span class="dot-wrap" :title="title">
    <span class="dot" :class="status" />
    <span v-if="label" class="label">{{ label }}</span>
  </span>
</template>

<script setup lang="ts">
// 连接状态点：checking 呼吸 / ok 常亮 / err 常亮
withDefaults(
  defineProps<{ status: 'checking' | 'ok' | 'err'; label?: string; title?: string }>(),
  {},
)
</script>

<style scoped>
.dot-wrap {
  display: inline-flex;
  align-items: center;
  gap: 7px;
}
.dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  flex: none;
  background: var(--ink-4);
}
.dot.checking {
  background: var(--warn);
  animation: breathe 1.4s var(--ease-out) infinite;
}
.dot.ok {
  background: var(--ok);
  box-shadow: 0 0 0 3px rgba(53, 209, 138, 0.16);
}
.dot.err {
  background: var(--danger);
  box-shadow: 0 0 0 3px rgba(255, 95, 86, 0.16);
}
.label {
  font-size: var(--fs-xs);
  color: var(--ink-3);
}
</style>
