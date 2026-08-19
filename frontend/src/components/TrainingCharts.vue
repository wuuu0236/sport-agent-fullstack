<template>
  <div v-if="runs.length" class="charts">
    <div class="board-title">训练数据</div>

    <!-- 心率区间分布（最近一次带心率数据的跑） -->
    <div v-if="latestZoneRun" class="card">
      <div class="card-title">
        心率区间分布
        <span class="sub">{{ latestZoneRun.date }}</span>
      </div>
      <div class="zone-bar">
        <div
          v-for="z in ZONE_ORDER"
          v-show="zonePct(z) > 0"
          :key="z"
          class="zone-seg"
          :style="{ width: zonePct(z) + '%', background: ZONE_COLORS[z] }"
          :title="`${z} ${zonePct(z)}%`"
        ></div>
      </div>
      <div class="legend">
        <div v-for="z in ZONE_ORDER" v-show="zonePct(z) > 0" :key="z" class="lrow">
          <i class="dot" :style="{ background: ZONE_COLORS[z] }"></i>
          <span class="lname">{{ z }}</span>
          <span class="lpct">{{ zonePct(z) }}%</span>
        </div>
      </div>
    </div>

    <!-- 配速趋势（分/公里，越低越好） -->
    <div class="card">
      <div class="card-title">配速趋势 <span class="sub">分/公里 · 最近 {{ paceData.length }} 次</span></div>
      <SvgLineChart v-if="paceData.length >= 2" :values="paceData" color="var(--accent)" />
      <div v-else class="no-data">跑步数据不足 2 次，暂无趋势</div>
    </div>

    <!-- 距离趋势 -->
    <div class="card">
      <div class="card-title">跑量趋势 <span class="sub">公里 · 最近 {{ distanceData.length }} 次</span></div>
      <SvgLineChart v-if="distanceData.length >= 2" :values="distanceData" color="var(--ok)" />
      <div v-else class="no-data">跑步数据不足 2 次，暂无趋势</div>
    </div>

    <!-- 训练负荷趋势（TRIMP） -->
    <div class="card">
      <div class="card-title">训练负荷 TRIMP <span class="sub">最近 {{ loadData.length }} 次</span></div>
      <SvgLineChart v-if="loadData.length >= 2" :values="loadData" color="var(--warn)" />
      <div v-else class="no-data">负荷数据不足 2 次，暂无趋势</div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import SvgLineChart from './SvgLineChart.vue'

const props = defineProps<{ sessions: any[] }>()

const ZONE_ORDER = ['Z1恢复', 'Z2有氧燃脂', 'Z3有氧耐力', 'Z4无氧阈', 'Z5最大']
const ZONE_COLORS: Record<string, string> = {
  Z1恢复: '#2fb56f',
  Z2有氧燃脂: '#22b8a5',
  Z3有氧耐力: '#e0a63c',
  Z4无氧阈: '#ff7a45',
  Z5最大: '#e5534b',
}

// sessions 按 date 倒序（最新在前）；趋势图需要时间正序（最旧在左）
const runs = computed(() => props.sessions.filter((s) => s.type === 'run'))
const runsAsc = computed(() => [...runs.value].reverse())

const latestZoneRun = computed(() => {
  for (const r of runs.value) {
    if (r.zones && Object.keys(r.zones).length) return r
  }
  return null
})

function zonePct(z: string): number {
  return latestZoneRun.value?.zones?.[z] ?? 0
}

function toNum(v: unknown): number | null {
  const n = typeof v === 'number' ? v : Number(v)
  return Number.isFinite(n) && n > 0 ? n : null
}

const paceData = computed(() =>
  runsAsc.value.map((r) => toNum(r.pace_min_km)).filter((v): v is number => v !== null),
)
const distanceData = computed(() =>
  runsAsc.value.map((r) => toNum(r.distance_km)).filter((v): v is number => v !== null),
)
const loadData = computed(() =>
  runsAsc.value.map((r) => toNum(r.load)).filter((v): v is number => v !== null),
)
</script>

<style scoped>
.charts {
  display: flex;
  flex-direction: column;
  gap: 12px;
  margin: 14px 0;
}
.board-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--accent);
}
.card {
  background: color-mix(in srgb, var(--card) 85%, transparent);
  border: 1px solid var(--border);
  border-radius: 14px;
  padding: 16px 18px;
}
.card-title {
  font-size: 15px;
  font-weight: 600;
  margin-bottom: 12px;
  display: flex;
  align-items: baseline;
  gap: 8px;
}
.card-title .sub {
  font-size: 12px;
  font-weight: 400;
  color: var(--faint);
}
.zone-bar {
  display: flex;
  height: 26px;
  border-radius: 13px;
  overflow: hidden;
  background: var(--bg-soft);
  margin-bottom: 12px;
}
.zone-seg {
  height: 100%;
  min-width: 2px;
}
.legend {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 20px;
}
.lrow {
  display: flex;
  align-items: center;
  gap: 7px;
  font-size: 13px;
  color: var(--text-soft);
}
.lrow .dot {
  width: 12px;
  height: 12px;
  border-radius: 50%;
  flex: none;
}
.lpct {
  margin-left: auto;
  font-variant-numeric: tabular-nums;
  color: var(--text);
  font-weight: 600;
}
.no-data {
  font-size: 14px;
  color: var(--faint);
  padding: 14px 0;
  text-align: center;
}
</style>
