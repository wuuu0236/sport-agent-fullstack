<template>
  <div class="sec">
    <div class="left">
      <h2 class="t">{{ title }}</h2>
      <p v-if="desc" class="d">{{ desc }}</p>
    </div>
    <div v-if="$slots.default" class="right"><slot /></div>
  </div>
</template>

<script setup lang="ts">
defineProps<{ title: string; desc?: string }>()
</script>

<style scoped>
.sec {
  display: flex;
  align-items: flex-end;
  gap: var(--sp-4);
  margin-bottom: var(--sp-4);
}
.t {
  font-size: var(--fs-lg);
  font-weight: var(--fw-semi);
  letter-spacing: -0.015em;
  color: var(--ink);
  display: flex;
  align-items: center;
  gap: 10px;
}
/* 标题前的一小段渐变装饰线 */
.t::before {
  content: '';
  width: 3px;
  height: 15px;
  border-radius: var(--r-full);
  background: var(--grad-accent);
  flex: none;
}
.d {
  margin: 5px 0 0 13px;
  font-size: var(--fs-sm);
  color: var(--ink-3);
}
.right {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: var(--sp-2);
}
</style>
