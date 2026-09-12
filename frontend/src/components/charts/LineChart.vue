<template>
  <div ref="wrapRef" class="chart" :style="{ height: height + 'px' }" @mouseleave="hover = null">
    <svg :width="width" :height="height" class="svg">
      <defs>
        <!-- 面积渐变：主色 28% → 透明，营造体积感 -->
        <linearGradient :id="areaId" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" :stop-color="color" stop-opacity="0.3" />
          <stop offset="62%" :stop-color="color" stop-opacity="0.07" />
          <stop offset="100%" :stop-color="color" stop-opacity="0" />
        </linearGradient>
        <!-- 折线自身的渐变描边：左淡右亮 -->
        <linearGradient :id="lineId" x1="0" y1="0" x2="1" y2="0">
          <stop offset="0%" :stop-color="color" stop-opacity="0.55" />
          <stop offset="100%" :stop-color="color" stop-opacity="1" />
        </linearGradient>
      </defs>

      <!-- 横向网格 + Y 轴刻度 -->
      <g class="grid">
        <template v-for="(g, i) in yTicks" :key="'g' + i">
          <line :x1="pad.l" :x2="width - pad.r" :y1="g.y" :y2="g.y" />
          <text :x="pad.l - 8" :y="g.y + 4" class="axis-y num">{{ g.label }}</text>
        </template>
      </g>

      <!-- 面积填充 -->
      <path :d="areaPath" :fill="`url(#${areaId})`" class="area" />

      <!-- 折线：描边入场动画 -->
      <path
        :d="linePath"
        fill="none"
        :stroke="`url(#${lineId})`"
        stroke-width="2.2"
        stroke-linecap="round"
        stroke-linejoin="round"
        class="line"
        :style="{ strokeDasharray: lineLen, strokeDashoffset: lineLen }"
      />

      <!-- 数据点（点少时常显，点多时只显悬停点） -->
      <circle
        v-for="(p, i) in pts"
        v-show="pts.length <= 12 || hover === i"
        :key="'d' + i"
        :cx="p.x"
        :cy="p.y"
        :r="hover === i ? 5 : 3.2"
        :fill="color"
        class="dot"
        :class="{ on: hover === i }"
      />

      <!-- 悬停十字线 + 高亮点 -->
      <g v-if="hover !== null">
        <line
          class="crosshair"
          :x1="pts[hover].x"
          :x2="pts[hover].x"
          :y1="pad.t - 4"
          :y2="height - pad.b + 4"
        />
        <circle :cx="pts[hover].x" :cy="pts[hover].y" r="9" :fill="color" opacity="0.16" />
        <circle :cx="pts[hover].x" :cy="pts[hover].y" r="4.4" :fill="color" stroke="var(--surface-2)" stroke-width="2" />
      </g>

      <!-- X 轴标签 -->
      <text
        v-for="(t, i) in xTicks"
        :key="'x' + i"
        :x="t.x"
        :y="height - 6"
        class="axis-x num"
        :text-anchor="t.anchor"
      >
        {{ t.label }}
      </text>

      <!-- 透明命中区：按时段分栏，鼠标滑过即定位最近点 -->
      <rect
        v-for="(p, i) in pts"
        :key="'h' + i"
        :x="p.hitX"
        :y="0"
        :width="p.hitW"
        :height="height"
        fill="transparent"
        @mouseenter="hover = i"
      />
    </svg>

    <!-- 悬停提示卡 -->
    <div
      v-if="hover !== null"
      class="tip"
      :style="tipStyle"
    >
      <span class="tip-label">{{ pts[hover].label }}</span>
      <span class="tip-val num">
        {{ fmt(pts[hover].value) }}<i v-if="unit">{{ unit }}</i>
      </span>
      <span v-if="pts[hover].sub" class="tip-sub">{{ pts[hover].sub }}</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import type { LinePoint } from './types'

const props = withDefaults(
  defineProps<{
    points: LinePoint[]
    color?: string
    unit?: string
    height?: number
  }>(),
  { color: 'var(--accent)', height: 186, unit: '' },
)

// 每个实例一套唯一渐变 id，避免同页多图互相覆盖
let seq = 0
const uid = `lc${++seq}_${Math.random().toString(36).slice(2, 7)}`
const areaId = `area_${uid}`
const lineId = `line_${uid}`

const pad = { t: 16, r: 14, b: 24, l: 36 }

// ---- 尺寸自适应（ResizeObserver：像素坐标，避免 viewBox 拉伸导致描边变形）----
const wrapRef = ref<HTMLElement | null>(null)
const width = ref(640)
let ro: ResizeObserver | null = null

function measure() {
  const w = wrapRef.value?.clientWidth
  if (w && w > 0) width.value = w
}

onMounted(() => {
  measure()
  if (typeof ResizeObserver !== 'undefined' && wrapRef.value) {
    ro = new ResizeObserver(measure)
    ro.observe(wrapRef.value)
  } else {
    window.addEventListener('resize', measure)
  }
})
onBeforeUnmount(() => {
  ro?.disconnect()
  window.removeEventListener('resize', measure)
})

// ---- 数值 → 坐标 ----
const hover = ref<number | null>(null)

const bounds = computed(() => {
  const vs = props.points.map((p) => p.value)
  if (!vs.length) return { min: 0, max: 1 }
  let min = Math.min(...vs)
  let max = Math.max(...vs)
  if (min === max) {
    // 全等值时人为撑开区间，避免线贴边或除零
    const d = Math.abs(min) > 1 ? Math.abs(min) * 0.12 : 1
    min -= d
    max += d
  } else {
    const padv = (max - min) * 0.14
    min -= padv
    max += padv
  }
  return { min, max }
})

const plotW = computed(() => Math.max(width.value - pad.l - pad.r, 10))
const plotH = computed(() => Math.max(props.height - pad.t - pad.b, 10))

function xAt(i: number) {
  const n = props.points.length
  if (n <= 1) return pad.l + plotW.value / 2
  return pad.l + (plotW.value * i) / (n - 1)
}
function yAt(v: number) {
  const { min, max } = bounds.value
  const ratio = (v - min) / (max - min || 1)
  return pad.t + plotH.value * (1 - ratio)
}

const pts = computed(() =>
  props.points.map((p, i) => {
    const step = props.points.length > 1 ? plotW.value / (props.points.length - 1) : plotW.value
    return {
      x: xAt(i),
      y: yAt(p.value),
      label: p.label,
      value: p.value,
      sub: p.sub,
      hitX: xAt(i) - step / 2,
      hitW: step,
    }
  }),
)

// ---- 平滑曲线（Catmull-Rom → 三次贝塞尔，张力 0.5）----
function smoothPath(list: { x: number; y: number }[]) {
  if (!list.length) return ''
  if (list.length === 1) return `M ${list[0].x} ${list[0].y}`
  let d = `M ${list[0].x} ${list[0].y}`
  for (let i = 0; i < list.length - 1; i++) {
    const p0 = list[i - 1] ?? list[i]
    const p1 = list[i]
    const p2 = list[i + 1]
    const p3 = list[i + 2] ?? p2
    const c1x = p1.x + (p2.x - p0.x) / 6
    const c1y = p1.y + (p2.y - p0.y) / 6
    const c2x = p2.x - (p3.x - p1.x) / 6
    const c2y = p2.y - (p3.y - p1.y) / 6
    d += ` C ${c1x} ${c1y}, ${c2x} ${c2y}, ${p2.x} ${p2.y}`
  }
  return d
}

const linePath = computed(() => smoothPath(pts.value))

const areaPath = computed(() => {
  if (!pts.value.length) return ''
  const base = pad.t + plotH.value
  const last = pts.value[pts.value.length - 1]
  return `${smoothPath(pts.value)} L ${last.x} ${base} L ${pts.value[0].x} ${base} Z`
})

// 描边长度：用于入场动画（估算上限即可，略大不影响观感）
const lineLen = computed(() => Math.round((plotW.value + plotH.value) * 1.5))

// ---- 轴标签 ----
const yTicks = computed(() => {
  const { min, max } = bounds.value
  return [max, (max + min) / 2, min].map((v) => ({
    y: yAt(v),
    label: fmtCompact(v),
  }))
})

const xTicks = computed(() => {
  const n = props.points.length
  if (!n) return []
  const maxLabels = Math.max(2, Math.min(6, n))
  const step = Math.max(1, Math.ceil(n / maxLabels))
  const out: { x: number; label: string; anchor: string }[] = []
  for (let i = 0; i < n; i += step) {
    out.push({
      x: xAt(i),
      label: props.points[i].label,
      anchor: i === 0 ? 'start' : 'middle',
    })
  }
  const lastIdx = n - 1
  if (out.length && out[out.length - 1].x !== xAt(lastIdx)) {
    out.push({ x: xAt(lastIdx), label: props.points[lastIdx].label, anchor: 'end' })
  }
  return out
})

// ---- 提示卡定位（贴边时夹紧，避免溢出容器）----
const tipStyle = computed(() => {
  if (hover.value === null) return {}
  const p = pts.value[hover.value]
  const half = 52
  const x = Math.min(Math.max(p.x, half), Math.max(width.value - half, half))
  return {
    left: `${x}px`,
    top: `${Math.max(p.y - 12, 6)}px`,
  }
})

function fmt(v: number) {
  return Number.isInteger(v) ? String(v) : v.toFixed(v >= 100 ? 0 : 1)
}
function fmtCompact(v: number) {
  if (Math.abs(v) >= 1000) return (v / 1000).toFixed(1) + 'k'
  if (Math.abs(v) >= 100) return v.toFixed(0)
  return v.toFixed(Math.abs(v) < 10 ? 1 : 0)
}

watch(
  () => props.points,
  () => (hover.value = null),
)
</script>

<style scoped>
.chart {
  position: relative;
  width: 100%;
}
.svg {
  display: block;
  overflow: visible;
}

.grid line {
  stroke: var(--line);
  stroke-dasharray: 3 5;
}
.axis-y,
.axis-x {
  fill: var(--ink-4);
  font-size: 10.5px;
  font-family: var(--font-sans);
}
.axis-y {
  text-anchor: end;
}

.area {
  animation: fade-up var(--t-slow) var(--ease-out) both;
}
.line {
  animation: draw 1.1s var(--ease-out) forwards;
}
.dot {
  transition: r var(--t-fast) var(--ease-out);
}

.crosshair {
  stroke: var(--line-3);
  stroke-dasharray: 3 4;
}

.tip {
  position: absolute;
  transform: translate(-50%, -100%);
  padding: 7px 11px;
  border-radius: var(--r-sm);
  background: var(--glass-strong);
  backdrop-filter: blur(14px);
  border: 1px solid var(--line-2);
  box-shadow: var(--shadow-2);
  display: flex;
  flex-direction: column;
  gap: 1px;
  pointer-events: none;
  white-space: nowrap;
  z-index: 3;
  animation: pop-in var(--t-fast) var(--ease-out) both;
}
.tip-label {
  font-size: 10.5px;
  color: var(--ink-4);
}
.tip-val {
  font-size: var(--fs-md);
  font-weight: var(--fw-bold);
  color: var(--ink);
  letter-spacing: -0.01em;
}
.tip-val i {
  font-style: normal;
  font-size: var(--fs-xs);
  font-weight: var(--fw-normal);
  color: var(--ink-3);
  margin-left: 2px;
}
.tip-sub {
  font-size: 10.5px;
  color: var(--ink-3);
}
</style>
