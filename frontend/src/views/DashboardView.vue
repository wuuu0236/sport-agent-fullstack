<template>
  <div class="dash">
    <div class="wrap">
      <!-- 头部 -->
      <SectionTitle title="训练数据" :desc="headDesc">
        <AppButton variant="subtle" size="sm" :icon="REFRESH_ICON" :busy="loading" @click="load">
          刷新
        </AppButton>
      </SectionTitle>

      <!-- 加载中：骨架屏 -->
      <template v-if="loading && !sessions.length">
        <div class="kpis">
          <div v-for="i in 6" :key="i" class="sk-tile">
            <SkeletonBlock w="46%" h="11px" />
            <SkeletonBlock w="60%" h="30px" />
            <SkeletonBlock w="34%" h="10px" />
          </div>
        </div>
        <div class="charts">
          <AppCard v-for="i in 3" :key="i" title=" ">
            <SkeletonBlock h="150px" r="var(--r-md)" />
          </AppCard>
        </div>
      </template>

      <template v-else-if="!runs.length && !strengths.length">
        <EmptyState
          icon="data"
          title="还没有训练记录"
          desc="去「对话」里说一句“记录一下今天跑了 5 公里 30 分钟”，或直接发一张训练截图，数据会自动进库。"
        >
          <AppPill tone="accent" size="md">支持跑步 / 力量两类记录</AppPill>
        </EmptyState>
      </template>

      <template v-else>
        <!-- KPI 磁贴 -->
        <div class="kpis">
          <StatTile label="跑步次数" :value="stats.runCount" unit="次" tone="accent" :icon="ICONS.run" hint="累计记录" />
          <StatTile label="总跑量" :value="stats.totalDistance.toFixed(1)" unit="公里" tone="accent" :icon="ICONS.route" hint="全部跑步之和" />
          <StatTile label="平均配速" :value="stats.avgPace" unit="分/公里" tone="ok" :icon="ICONS.pace" hint="越低越快" />
          <StatTile label="平均心率" :value="stats.avgHr" unit="bpm" tone="energy" :icon="ICONS.hr" hint="仅统计带心率的记录" />
          <StatTile label="最大单次跑量" :value="stats.maxDistance.toFixed(1)" unit="公里" tone="accent" :icon="ICONS.trophy" hint="历史最长一次" />
          <StatTile label="最近负荷" :value="stats.lastLoad ?? '—'" unit="TRIMP" tone="warn" :icon="ICONS.load" hint="时长 × 强度" />
        </div>

        <!-- 趋势图 -->
        <div class="charts">
          <AppCard
            title="跑量趋势"
            :subtitle="runs.length >= 2 ? `最近 ${distPoints.length} 次跑步 · 公里` : '数据不足'"
          >
            <LineChart v-if="distPoints.length >= 2" :points="distPoints" color="#2ad4c8" unit=" km" />
            <p v-else class="nodata">至少 2 次跑步记录才能画出趋势</p>
          </AppCard>

          <AppCard
            title="配速趋势"
            :subtitle="pacePoints.length >= 2 ? `分/公里 · 越低越快` : '数据不足'"
          >
            <LineChart v-if="pacePoints.length >= 2" :points="pacePoints" color="#3d8bff" unit=" 分/km" />
            <p v-else class="nodata">至少 2 次跑步记录才能画出趋势</p>
          </AppCard>

          <AppCard
            title="训练负荷 TRIMP"
            :subtitle="loadPoints.length >= 2 ? '时长 × 强度，衡量单次训练压力' : '数据不足'"
          >
            <LineChart v-if="loadPoints.length >= 2" :points="loadPoints" color="#ff7a45" />
            <p v-else class="nodata">需要带心率的跑步记录才能计算负荷</p>
          </AppCard>

          <AppCard v-if="latestZoneRun" title="心率区间分布" :subtitle="`${latestZoneRun.date} · 最近一次带心率的跑步`">
            <ZoneBar :zones="latestZoneRun.zones || {}" />
          </AppCard>
        </div>

        <!-- 训练流水 -->
        <SectionTitle title="训练流水" :desc="`共 ${sessions.length} 条记录（最近优先）`" />
        <AppCard pad="none">
          <ul class="rows">
            <li v-for="(s, i) in recent" :key="i" class="row">
              <AppPill :tone="s.type === 'run' ? 'accent' : 'energy'" size="sm">
                {{ s.type === 'run' ? '跑步' : s.type === 'strength' ? '力量' : s.type }}
              </AppPill>
              <span class="date num">{{ s.date }}</span>
              <span class="main num">{{ mainText(s) }}</span>
              <span class="extra">
                <template v-for="(t, k) in extraTags(s)" :key="k">
                  <i v-if="k > 0" class="sep">·</i>
                  <span class="tag num">{{ t }}</span>
                </template>
              </span>
            </li>
          </ul>
        </AppCard>
      </template>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import AppCard from '../components/ui/AppCard.vue'
import AppPill from '../components/ui/AppPill.vue'
import AppButton from '../components/ui/AppButton.vue'
import StatTile from '../components/ui/StatTile.vue'
import SectionTitle from '../components/ui/SectionTitle.vue'
import EmptyState from '../components/ui/EmptyState.vue'
import SkeletonBlock from '../components/ui/SkeletonBlock.vue'
import LineChart from '../components/charts/LineChart.vue'
import type { LinePoint } from '../components/charts/types'
import ZoneBar from '../components/charts/ZoneBar.vue'
import { getSessions } from '../api/client'

const STROKE =
  'fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"'
const ICONS = {
  refresh: `<svg viewBox="0 0 24 24" ${STROKE}><path d="M19.5 12a7.5 7.5 0 1 1-2.3-5.4"/><path d="M19.9 4.6v4.2h-4.2"/></svg>`,
  run: `<svg viewBox="0 0 24 24" ${STROKE}><circle cx="14.2" cy="4.9" r="1.7"/><path d="M12.4 8.6 9 11.4l2.2 2.4-.9 5.4M12.4 8.6l3.1 1.6 3.1-.4M11.2 13.8l-3.4 1.1-2.4 3.5"/></svg>`,
  route: `<svg viewBox="0 0 24 24" ${STROKE}><path d="M4.5 18.5c0-2.2 1.8-3.4 4-3.4h7c2.2 0 4-1.2 4-3.4s-1.8-3.4-4-3.4h-7"/><circle cx="4.4" cy="18.5" r="1.7"/><circle cx="19.6" cy="8.3" r="1.7"/></svg>`,
  pace: `<svg viewBox="0 0 24 24" ${STROKE}><circle cx="12" cy="12" r="8"/><path d="M12 12l4.2-3"/><path d="M12 4v1.8M20 12h-1.8M12 20v-1.8M4 12h1.8"/></svg>`,
  hr: `<svg viewBox="0 0 24 24" ${STROKE}><path d="M3 12.6h3.4l1.8-4.4 3 10 2.3-6.2 1.4 3h6.1"/></svg>`,
  trophy: `<svg viewBox="0 0 24 24" ${STROKE}><path d="M8 4.5h8v4.1a4 4 0 0 1-8 0z"/><path d="M8 5.6H5.6v1.6A3 3 0 0 0 8 10M16 5.6h2.4v1.6A3 3 0 0 1 16 10"/><path d="M12 12.6v3.4M8.6 19.5h6.8"/></svg>`,
  load: `<svg viewBox="0 0 24 24" ${STROKE}><path d="M5.4 9.4h13.2M4 12h16M5.4 14.6h13.2"/><path d="M7.2 6.6v10.8M16.8 6.6v10.8"/></svg>`,
}
const REFRESH_ICON = ICONS.refresh

const sessions = ref<any[]>([])
const loading = ref(false)

const runs = computed(() => sessions.value.filter((s) => s.type === 'run'))
const strengths = computed(() => sessions.value.filter((s) => s.type === 'strength'))

// 一律按日期倒序（最新在前），不依赖后端顺序
const recent = computed(() =>
  [...sessions.value].sort((a, b) => String(b.date || '').localeCompare(String(a.date || ''))),
)
// 趋势图需要时间正序（最旧在左）
const runsAsc = computed(() =>
  [...runs.value].sort((a, b) => String(a.date || '').localeCompare(String(b.date || ''))),
)

const headDesc = computed(() => {
  if (!sessions.value.length) return '基于本地训练记录统计，数据不上传'
  return `${sessions.value.length} 条本地记录 · 数据不上传，OCR 也在本机跑`
})

const stats = computed(() => {
  const rs = runs.value
  const totalDistance = rs.reduce((a, r) => a + (Number(r.distance_km) || 0), 0)
  const paces = rs.map((r) => Number(r.pace_min_km)).filter((v) => v > 0)
  const avgPace = paces.length ? (paces.reduce((a, b) => a + b, 0) / paces.length).toFixed(2) : '—'
  const hrs = rs.map((r) => Number(r.avg_hr)).filter((v) => v > 0)
  const avgHr = hrs.length ? Math.round(hrs.reduce((a, b) => a + b, 0) / hrs.length) : '—'
  const maxDistance = rs.reduce((a, r) => Math.max(a, Number(r.distance_km) || 0), 0)
  const lastLoad = rs
    .map((r) => r.load)
    .filter((v) => typeof v === 'number')
    .at(-1)
  return {
    runCount: rs.length,
    totalDistance,
    avgPace,
    avgHr,
    maxDistance,
    lastLoad: typeof lastLoad === 'number' ? Math.round(lastLoad) : null,
  }
})

function mmdd(d: string): string {
  const s = String(d || '')
  const m = s.match(/(\d{4})-(\d{2})-(\d{2})/)
  return m ? `${m[2]}-${m[3]}` : s.slice(5) || s
}
function num(v: unknown): number | null {
  const n = typeof v === 'number' ? v : Number(v)
  return Number.isFinite(n) && n > 0 ? n : null
}

const distPoints = computed<LinePoint[]>(() =>
  runsAsc.value
    .map((r) => ({ label: mmdd(r.date), value: num(r.distance_km), sub: r.date }))
    .filter((p): p is LinePoint => p.value !== null),
)
const pacePoints = computed<LinePoint[]>(() =>
  runsAsc.value
    .map((r) => ({ label: mmdd(r.date), value: num(r.pace_min_km), sub: r.date }))
    .filter((p): p is LinePoint => p.value !== null),
)
const loadPoints = computed<LinePoint[]>(() =>
  runsAsc.value
    .map((r) => ({ label: mmdd(r.date), value: num(r.load), sub: r.date }))
    .filter((p): p is LinePoint => p.value !== null),
)

const latestZoneRun = computed(
  () => runs.value.find((r) => r.zones && Object.keys(r.zones).length) ?? null,
)

function mainText(s: any): string {
  if (s.type === 'run') {
    const km = s.distance_km ?? '—'
    const min = s.duration_min ? Math.round(Number(s.duration_min)) : '—'
    const hr = s.avg_hr ? ` · 均心 ${s.avg_hr}` : ''
    return `${km} km · ${min} 分${hr}`
  }
  if (s.type === 'strength') {
    const n = (s.exercises || []).length
    const names = (s.exercises || [])
      .slice(0, 3)
      .map((e: any) => e.name)
      .filter(Boolean)
      .join('、')
    return `${n} 个动作${names ? ` · ${names}` : ''}`
  }
  return '—'
}

function extraTags(s: any): string[] {
  const t: string[] = []
  if (s.pace_min_km) t.push(`配速 ${s.pace_min_km}`)
  if (s.load != null) t.push(`负荷 ${Math.round(Number(s.load))}`)
  if (s.rpe) t.push(`RPE ${s.rpe}`)
  if (s.max_hr) t.push(`最大心率 ${s.max_hr}`)
  return t
}

async function load() {
  loading.value = true
  try {
    const d = await getSessions(50)
    sessions.value = d.sessions || []
  } catch {
    sessions.value = []
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.dash {
  flex: 1;
  min-width: 0;
  height: 100vh;
  overflow-y: auto;
}
.wrap {
  max-width: 1080px;
  margin: 0 auto;
  padding: var(--sp-6) var(--sp-7) var(--sp-8);
}

.kpis {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: var(--sp-4);
  margin-bottom: var(--sp-6);
}
@media (max-width: 1180px) {
  .kpis {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

.sk-tile {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: var(--sp-5);
  border-radius: var(--r-lg);
  background: var(--surface-2);
  border: 1px solid var(--line);
}

.charts {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--sp-4);
  margin-bottom: var(--sp-6);
}
@media (max-width: 1180px) {
  .charts {
    grid-template-columns: minmax(0, 1fr);
  }
}

.nodata {
  font-size: var(--fs-sm);
  color: var(--ink-4);
  text-align: center;
  padding: 48px 0;
}

/* 训练流水：一行一条，指标用等宽数字对齐 */
.rows {
  display: flex;
  flex-direction: column;
}
.row {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
  padding: 13px var(--sp-5);
  border-bottom: 1px solid var(--line);
  transition: background var(--t-fast) var(--ease-out);
}
.row:last-child {
  border-bottom: none;
}
.row:hover {
  background: rgba(61, 139, 255, 0.045);
}
.date {
  font-size: var(--fs-sm);
  color: var(--ink-3);
  flex: none;
  width: 86px;
}
.main {
  font-size: var(--fs-base);
  color: var(--ink);
  font-weight: var(--fw-medium);
}
.extra {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: 7px;
  flex-wrap: wrap;
  justify-content: flex-end;
}
.tag {
  font-size: var(--fs-xs);
  color: var(--ink-4);
}
.sep {
  font-style: normal;
  color: var(--ink-4);
  opacity: 0.5;
}
</style>
