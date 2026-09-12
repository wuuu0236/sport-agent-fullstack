<template>
  <div class="pending">
    <header class="p-head">
      <span class="ico" v-html="INBOX_ICON" />
      <div class="pt">
        <h4>解析出 {{ count }} 条训练记录</h4>
        <p>已放入暂存区，<b>尚未写入训练库</b>——确认无误后再入库。</p>
      </div>
    </header>

    <ul v-if="records?.length" class="recs">
      <li v-for="(r, i) in records" :key="r._staged_id || i" class="rec">
        <AppPill :tone="r.type === 'run' ? 'accent' : 'energy'" size="sm">
          {{ r.type === 'run' ? '跑步' : r.type === 'strength' ? '力量' : r.type }}
        </AppPill>
        <span class="date num">{{ r.date }}</span>
        <span class="detail num">{{ summary(r) }}</span>
      </li>
    </ul>

    <footer class="acts">
      <AppButton variant="subtle" size="sm" @click="emit('dismiss')">忽略</AppButton>
      <AppButton variant="primary" size="sm" :icon="CHECK_ICON" @click="emit('confirm')">
        确认入库
      </AppButton>
    </footer>
  </div>
</template>

<script setup lang="ts">
import AppButton from '../ui/AppButton.vue'
import AppPill from '../ui/AppPill.vue'

defineProps<{ count: number; records?: any[] }>()
const emit = defineEmits<{ confirm: []; dismiss: [] }>()

const STROKE =
  'fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"'
const INBOX_ICON = `<svg viewBox="0 0 24 24" ${STROKE}><path d="M3.4 7.6A2.2 2.2 0 0 1 5.6 5.4h12.8a2.2 2.2 0 0 1 2.2 2.2v8.8a2.2 2.2 0 0 1-2.2 2.2H5.6a2.2 2.2 0 0 1-2.2-2.2z"/><path d="M3.4 13h4.4l1.1 1.9h6.2L16.2 13h4.4"/></svg>`
const CHECK_ICON = `<svg viewBox="0 0 24 24" ${STROKE}><path d="M5 12.6 9.4 17 19 7.4"/></svg>`

function summary(r: any): string {
  if (r.type === 'run') {
    const km = r.distance_km ?? '—'
    const min = r.duration_min ? Math.round(r.duration_min) : '—'
    const hr = r.avg_hr ? ` · 均心 ${r.avg_hr}` : ''
    return `${km} km · ${min} 分${hr}`
  }
  if (r.type === 'strength') {
    const n = (r.exercises || []).length
    const names = (r.exercises || []).slice(0, 2).map((e: any) => e.name).join('、')
    return `${n} 个动作${names ? ` · ${names}` : ''}`
  }
  return '—'
}
</script>

<style scoped>
.pending {
  border-radius: var(--r-lg);
  background: linear-gradient(180deg, rgba(240, 178, 60, 0.09), var(--surface-2) 60%);
  border: 1px solid rgba(240, 178, 60, 0.34);
  box-shadow: var(--hairline-top), var(--shadow-2);
  padding: var(--sp-4) var(--sp-5) var(--sp-4);
  animation: pop-in var(--t-slow) var(--ease-out) both;
}
.p-head {
  display: flex;
  gap: var(--sp-3);
  align-items: flex-start;
}
.ico {
  width: 30px;
  height: 30px;
  flex: none;
  display: grid;
  place-items: center;
  border-radius: var(--r-sm);
  color: var(--warn);
  background: rgba(240, 178, 60, 0.14);
  border: 1px solid rgba(240, 178, 60, 0.3);
}
.ico :deep(svg) {
  width: 16px;
  height: 16px;
}
.pt h4 {
  font-size: var(--fs-base);
  font-weight: var(--fw-semi);
  color: var(--ink);
}
.pt p {
  margin-top: 3px;
  font-size: var(--fs-xs);
  color: var(--ink-3);
}
.pt b {
  color: var(--warn);
  font-weight: var(--fw-semi);
}

.recs {
  margin-top: var(--sp-3);
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.rec {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 11px;
  border-radius: var(--r-sm);
  background: var(--surface-1);
  border: 1px solid var(--line);
}
.date {
  font-size: var(--fs-xs);
  color: var(--ink-2);
  font-weight: var(--fw-semi);
}
.detail {
  margin-left: auto;
  font-size: var(--fs-xs);
  color: var(--ink-4);
}

.acts {
  display: flex;
  justify-content: flex-end;
  gap: var(--sp-2);
  margin-top: var(--sp-4);
}
</style>
