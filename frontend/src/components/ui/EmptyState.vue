<template>
  <div class="empty">
    <div class="badge" v-html="iconSvg"></div>
    <h3 class="t">{{ title }}</h3>
    <p v-if="desc" class="d">{{ desc }}</p>
    <div v-if="$slots.default" class="act"><slot /></div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = withDefaults(
  defineProps<{ title: string; desc?: string; icon?: 'inbox' | 'data' | 'spark' | 'warn' }>(),
  { icon: 'inbox' },
)

const STROKE =
  'fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"'

const ICONS: Record<string, string> = {
  inbox:
    `<svg viewBox="0 0 24 24" ${STROKE}><path d="M3 7.5A2.5 2.5 0 0 1 5.5 5h13A2.5 2.5 0 0 1 21 7.5v9A2.5 2.5 0 0 1 18.5 19h-13A2.5 2.5 0 0 1 3 16.5z"/><path d="M3 13h5l1.2 2h5.6L16 13h5"/></svg>`,
  data:
    `<svg viewBox="0 0 24 24" ${STROKE}><path d="M4 19V11"/><path d="M9.3 19V6"/><path d="M14.7 19v-5"/><path d="M20 19V9"/></svg>`,
  spark:
    `<svg viewBox="0 0 24 24" ${STROKE}><path d="M12 3l1.9 5.6L19.5 10l-5.6 1.9L12 17.5l-1.9-5.6L4.5 10l5.6-1.4z"/><path d="M18.5 15.5l.6 1.9 1.9.6-1.9.6-.6 1.9-.6-1.9-1.9-.6 1.9-.6z"/></svg>`,
  warn:
    `<svg viewBox="0 0 24 24" ${STROKE}><path d="M12 4.5l8.2 14.2H3.8z"/><path d="M12 10v4M12 16.6v.2"/></svg>`,
}

const iconSvg = computed(() => ICONS[props.icon] ?? ICONS.inbox)
</script>

<style scoped>
.empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
  padding: 46px 24px;
  animation: fade-up var(--t-slow) var(--ease-out) both;
}
.badge {
  width: 52px;
  height: 52px;
  border-radius: var(--r-lg);
  display: grid;
  place-items: center;
  color: var(--accent-hi);
  background: var(--grad-accent-soft);
  border: 1px solid var(--line-2);
  box-shadow: var(--hairline-top);
  margin-bottom: var(--sp-4);
}
.badge :deep(svg) {
  width: 24px;
  height: 24px;
}
.t {
  font-size: var(--fs-md);
  font-weight: var(--fw-semi);
  color: var(--ink);
}
.d {
  margin-top: 7px;
  font-size: var(--fs-sm);
  color: var(--ink-3);
  max-width: 380px;
  line-height: var(--lh-normal);
}
.act {
  margin-top: var(--sp-5);
}
</style>
