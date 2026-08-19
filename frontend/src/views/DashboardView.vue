<template>
  <div class="dashboard">
    <div class="dash-head">
      <div class="dash-title">训练数据</div>
      <div class="dash-sub">基于本地训练记录统计，数据不上传</div>
    </div>

    <!-- 统计卡片 -->
    <div class="stats">
      <div class="stat">
        <div class="stat-label">跑步次数</div>
        <div class="stat-value">{{ stats.runCount }}</div>
        <div class="stat-unit">次</div>
      </div>
      <div class="stat">
        <div class="stat-label">总跑量</div>
        <div class="stat-value">{{ stats.totalDistance.toFixed(1) }}</div>
        <div class="stat-unit">公里</div>
      </div>
      <div class="stat">
        <div class="stat-label">平均配速</div>
        <div class="stat-value">{{ stats.avgPace }}</div>
        <div class="stat-unit">分/公里</div>
      </div>
      <div class="stat">
        <div class="stat-label">平均心率</div>
        <div class="stat-value">{{ stats.avgHr }}</div>
        <div class="stat-unit">次/分</div>
      </div>
      <div class="stat">
        <div class="stat-label">最大单次跑量</div>
        <div class="stat-value">{{ stats.maxDistance.toFixed(1) }}</div>
        <div class="stat-unit">公里</div>
      </div>
      <div class="stat">
        <div class="stat-label">最近负荷 TRIMP</div>
        <div class="stat-value">{{ stats.lastLoad ?? '—' }}</div>
        <div class="stat-unit">训练量</div>
      </div>
    </div>

    <!-- 图表 -->
    <TrainingCharts :sessions="sessions" />

    <!-- 最近训练列表 -->
    <div class="recent">
      <div class="board-title">最近训练</div>
      <div v-if="runs.length" class="list">
        <div v-for="(s, i) in runs" :key="i" class="row">
          <span class="date">{{ s.date }}</span>
          <span class="main">{{ runSummary(s) }}</span>
          <span class="extra">{{ extraSummary(s) }}</span>
        </div>
      </div>
      <div v-else class="no-data">还没有训练记录，去「对话」模块记录一次吧</div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import TrainingCharts from '../components/TrainingCharts.vue'
import { getSessions } from '../api/client'

const sessions = ref<any[]>([])
const runs = computed(() => sessions.value.filter((s) => s.type === 'run'))

const stats = computed(() => {
  const rs = runs.value
  const runCount = rs.length
  const totalDistance = rs.reduce((acc, r) => acc + (Number(r.distance_km) || 0), 0)
  const paces = rs.map((r) => Number(r.pace_min_km)).filter((v) => v > 0)
  const avgPace = paces.length ? (paces.reduce((a, b) => a + b, 0) / paces.length).toFixed(2) : '—'
  const hrs = rs.map((r) => Number(r.avg_hr)).filter((v) => v > 0)
  const avgHr = hrs.length ? Math.round(hrs.reduce((a, b) => a + b, 0) / hrs.length) : '—'
  const maxDistance = rs.reduce((acc, r) => Math.max(acc, Number(r.distance_km) || 0), 0)
  const lastLoad = rs[0]?.load ?? null
  return { runCount, totalDistance, avgPace, avgHr, maxDistance, lastLoad }
})

function runSummary(s: any) {
  return `${s.distance_km}km · ${s.duration_min}分 · 心率${s.avg_hr || '—'}`
}
function extraSummary(s: any) {
  const parts: string[] = []
  if (s.pace_min_km) parts.push(`配速${s.pace_min_km}`)
  if (s.load != null) parts.push(`负荷${s.load}`)
  return parts.join(' · ')
}

onMounted(async () => {
  try {
    const d = await getSessions(20)
    sessions.value = d.sessions || []
  } catch {
    sessions.value = []
  }
})
</script>

<style scoped>
.dashboard {
  flex: 1;
  min-width: 0;
  max-width: 1080px;
  margin: 0 auto;
  padding: 28px 32px;
  height: 100vh;
  overflow-y: auto;
  box-sizing: border-box;
  scrollbar-width: thin;
  scrollbar-color: var(--border) transparent;
}
.dash-head {
  margin-bottom: 20px;
}
.dash-title {
  font-size: 24px;
  font-weight: 700;
}
.dash-sub {
  font-size: 13px;
  color: var(--faint);
  margin-top: 4px;
}
.stats {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 14px;
  margin-bottom: 18px;
}
.stat {
  background: color-mix(in srgb, var(--card) 85%, transparent);
  border: 1px solid var(--border);
  border-radius: 14px;
  padding: 16px 18px;
}
.stat-label {
  font-size: 13px;
  color: var(--muted);
}
.stat-value {
  font-size: 30px;
  font-weight: 700;
  margin-top: 6px;
  color: var(--accent);
  font-variant-numeric: tabular-nums;
}
.stat-unit {
  font-size: 12px;
  color: var(--faint);
  margin-top: 2px;
}
.board-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--accent);
  margin-bottom: 10px;
}
.recent {
  margin-top: 18px;
  background: color-mix(in srgb, var(--card) 85%, transparent);
  border: 1px solid var(--border);
  border-radius: 14px;
  padding: 14px 18px;
}
.row {
  display: flex;
  gap: 14px;
  align-items: baseline;
  font-size: 14px;
  padding: 8px 0;
  border-bottom: 1px dashed var(--border-soft);
}
.row:last-child {
  border-bottom: none;
}
.date {
  color: var(--accent);
  font-weight: 600;
  white-space: nowrap;
  font-size: 13px;
}
.main {
  color: var(--text-soft);
}
.extra {
  margin-left: auto;
  color: var(--faint);
  font-size: 13px;
  white-space: nowrap;
}
.no-data {
  font-size: 14px;
  color: var(--faint);
  padding: 14px 0;
  text-align: center;
}
</style>
