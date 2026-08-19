<template>
  <svg :viewBox="`0 0 ${W} ${H}`" class="line-chart" preserveAspectRatio="none">
    <!-- 水平网格线 -->
    <line
      v-for="gy in gridYs"
      :key="gy"
      :x1="P"
      :y1="gy"
      :x2="W - P"
      :y2="gy"
      class="grid"
    />
    <!-- 折线 -->
    <polyline
      :points="polyPoints"
      fill="none"
      :stroke="color"
      stroke-width="2"
      stroke-linecap="round"
      stroke-linejoin="round"
      class="line"
    />
    <!-- 数据点 -->
    <circle
      v-for="(p, i) in pts"
      :key="i"
      :cx="p.x"
      :cy="p.y"
      r="3"
      :fill="color"
      class="dot"
    />
    <!-- 值标签 -->
    <text
      v-for="(p, i) in pts"
      :key="'t' + i"
      :x="p.x"
      :y="p.y - 8"
      class="val"
      text-anchor="middle"
    >
      {{ format(p.v) }}
    </text>
  </svg>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = withDefaults(
  defineProps<{
    values: number[]
    color?: string
    height?: number
  }>(),
  { color: 'var(--accent)', height: 130 },
)

const W = 340
const H = props.height
const P = 24

const pts = computed(() => {
  const vals = props.values
  const n = vals.length
  const min = Math.min(...vals)
  const max = Math.max(...vals)
  const range = max - min || 1
  return vals.map((v, i) => {
    const x = P + (i * (W - 2 * P)) / (n - 1 || 1)
    const y = H - P - ((v - min) / range) * (H - 2 * P)
    return { x, y, v }
  })
})

const polyPoints = computed(() => pts.value.map((p) => `${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(' '))

const gridYs = computed(() => {
  const ys: number[] = []
  for (let i = 0; i < 3; i++) ys.push(P + ((H - 2 * P) / 2) * i)
  return ys
})

function format(v: number) {
  return Number.isInteger(v) ? String(v) : v.toFixed(1)
}
</script>

<style scoped>
.line-chart {
  width: 100%;
  height: auto;
  overflow: visible;
}
.grid {
  stroke: var(--border-soft);
  stroke-width: 1;
  stroke-dasharray: 3 4;
}
.line {
  transition: stroke 0.2s;
}
.dot {
  stroke: var(--card);
  stroke-width: 1.5;
}
.val {
  font-size: 9px;
  fill: var(--muted);
}
</style>
