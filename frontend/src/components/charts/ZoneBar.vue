<template>
  <div class="zones">
    <!-- 分段条：各区间按占比切分，段与段之间留 2px 缝隙 -->
    <div class="bar">
      <div
        v-for="z in filled"
        :key="z.name"
        class="seg"
        :style="{ width: z.pct + '%', background: z.color }"
        :title="`${z.short} · ${z.pct}%`"
      >
        <span v-if="z.pct >= 12" class="seg-txt num">{{ Math.round(z.pct) }}%</span>
      </div>
    </div>

    <!-- 图例：名称 + 占比条 + 数值 -->
    <ul class="legend">
      <li v-for="z in ZONE_ORDER" :key="z" class="row" :class="{ off: !pct(z) }">
        <i class="dot" :style="{ background: color(z) }" />
        <span class="name">{{ z }}</span>
        <span class="track"><i :style="{ width: pct(z) + '%', background: color(z) }" /></span>
        <span class="pct num">{{ pct(z) ? fmt(pct(z)) + '%' : '—' }}</span>
      </li>
    </ul>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

// 心率区间分布（数据来自后端 analyze_run 的 zones 字段）
const props = withDefaults(
  defineProps<{ zones: Record<string, number>; date?: string }>(),
  { zones: () => ({}) },
)

const ZONE_ORDER = ['Z1恢复', 'Z2有氧燃脂', 'Z3有氧耐力', 'Z4无氧阈', 'Z5最大']
const ZONE_COLORS: Record<string, string> = {
  Z1恢复: 'linear-gradient(90deg, #1f9457, #38d18f)',
  Z2有氧燃脂: 'linear-gradient(90deg, #189f8f, #2ed6c4)',
  Z3有氧耐力: 'linear-gradient(90deg, #c98f22, #f0c05a)',
  Z4无氧阈: 'linear-gradient(90deg, #e05f2c, #ff9868)',
  Z5最大: 'linear-gradient(90deg, #c23e37, #ff6b62)',
}
const ZONE_FLAT: Record<string, string> = {
  Z1恢复: '#2fb56f',
  Z2有氧燃脂: '#22b8a5',
  Z3有氧耐力: '#e0a63c',
  Z4无氧阈: '#ff7a45',
  Z5最大: '#e5534b',
}
const ZONE_SHORT: Record<string, string> = {
  Z1恢复: 'Z1 恢复',
  Z2有氧燃脂: 'Z2 有氧燃脂',
  Z3有氧耐力: 'Z3 有氧耐力',
  Z4无氧阈: 'Z4 无氧阈',
  Z5最大: 'Z5 最大',
}

function pct(z: string): number {
  const v = props.zones?.[z]
  return typeof v === 'number' && Number.isFinite(v) ? v : 0
}
function color(z: string) {
  return ZONE_COLORS[z] ?? 'var(--surface-4)'
}

const filled = computed(() =>
  ZONE_ORDER.filter((z) => pct(z) > 0).map((z) => ({
    name: z,
    short: ZONE_SHORT[z],
    color: ZONE_COLORS[z],
    flat: ZONE_FLAT[z],
    pct: pct(z),
  })),
)

function fmt(v: number) {
  return v % 1 === 0 ? String(v) : v.toFixed(1)
}
</script>

<style scoped>
.bar {
  display: flex;
  gap: 2px;
  height: 34px;
  border-radius: var(--r-md);
  overflow: hidden;
  background: var(--surface-4);
  margin-bottom: var(--sp-4);
  box-shadow: var(--hairline-top);
}
.seg {
  height: 100%;
  min-width: 3px;
  display: grid;
  place-items: center;
  transition: width var(--t-slow) var(--ease-out), filter var(--t-fast) var(--ease-out);
  animation: fade-up var(--t-slow) var(--ease-out) both;
}
.seg:hover {
  filter: brightness(1.12);
}
.seg-txt {
  font-size: 11px;
  font-weight: var(--fw-semi);
  color: rgba(6, 18, 31, 0.78);
}

.legend {
  display: flex;
  flex-direction: column;
  gap: 9px;
}
.row {
  display: grid;
  grid-template-columns: 9px 96px 1fr 52px;
  align-items: center;
  gap: 10px;
  font-size: var(--fs-sm);
}
.row.off {
  opacity: 0.42;
}
.dot {
  width: 9px;
  height: 9px;
  border-radius: 50%;
  flex: none;
}
.name {
  color: var(--ink-2);
  white-space: nowrap;
}
.track {
  height: 5px;
  border-radius: var(--r-full);
  background: var(--surface-4);
  overflow: hidden;
}
.track i {
  display: block;
  height: 100%;
  border-radius: var(--r-full);
  transition: width var(--t-slow) var(--ease-out);
}
.pct {
  text-align: right;
  color: var(--ink);
  font-weight: var(--fw-semi);
}
</style>
