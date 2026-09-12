<template>
  <div class="plan-page">
    <div class="wrap">
      <SectionTitle title="训练计划" :desc="headDesc">
        <AppButton variant="subtle" size="sm" :icon="REFRESH_ICON" :busy="loading" @click="load">
          刷新
        </AppButton>
      </SectionTitle>

      <!-- 错误提示 -->
      <div v-if="error" class="err-bar">
        <span v-html="WARN_ICON" />
        <span>{{ error }}</span>
        <button @click="error = ''">✕</button>
      </div>

      <!-- 待确认计划 -->
      <AppCard v-if="pending" tone="warn" pad="lg" class="pending">
        <div class="pd-head">
          <span class="pd-badge" v-html="SPARK_ICON" />
          <div>
            <h3 class="pd-title">待确认：{{ pending.name }}</h3>
            <p class="pd-desc">
              刚生成一份新计划，选择一种方式应用（未确认前不会影响当前计划）。
            </p>
          </div>
        </div>
        <div class="pd-acts">
          <AppButton variant="primary" size="sm" :busy="applying" @click="apply('replace')">
            替换当前计划
          </AppButton>
          <AppButton variant="subtle" size="sm" :busy="applying" @click="apply('add')">
            加入为第二方案
          </AppButton>
          <AppButton variant="ghost" size="sm" @click="doDiscard">放弃</AppButton>
        </div>
      </AppCard>

      <!-- 加载骨架 -->
      <AppCard v-if="loading && !plans.length" pad="lg">
        <div class="sk-stack">
          <SkeletonBlock w="30%" h="26px" />
          <SkeletonBlock w="55%" h="13px" />
          <SkeletonBlock h="150px" r="var(--r-md)" />
        </div>
      </AppCard>

      <!-- 当前计划 -->
      <section v-else-if="activePlan" class="hero">
        <div class="hero-glow" aria-hidden="true" />

        <header class="hero-head">
          <div class="hero-left">
            <div class="hero-eyebrow">
              <span class="dot" />当前执行中
            </div>
            <h2 class="hero-name">{{ activePlan.name || '当前训练计划' }}</h2>
            <div class="hero-tags">
              <AppPill v-if="activePlan.goal" tone="accent" size="md">{{ activePlan.goal }}</AppPill>
              <AppPill v-if="activePlan.phase" tone="neutral" size="md">{{ activePlan.phase }}</AppPill>
              <AppPill v-if="activePlan.countdown" tone="energy" size="md" dot>
                {{ activePlan.countdown }}
              </AppPill>
            </div>
            <p class="hero-meta">
              <span v-if="activePlan.cycleMeta">{{ activePlan.cycleMeta }}</span>
              <i v-if="activePlan.cycleMeta">·</i>
              <span>更新于 {{ updateDate }}</span>
            </p>
          </div>

          <div class="hero-ops">
            <template v-if="confirmDelId === activePlan.id">
              <span class="confirm-tip">删除后不可恢复</span>
              <AppButton variant="danger" size="sm" @click="doDelete(activePlan.id)">确认删除</AppButton>
              <AppButton variant="ghost" size="sm" @click="confirmDelId = null">取消</AppButton>
            </template>
            <AppButton
              v-else
              variant="ghost"
              size="sm"
              :icon="TRASH_ICON"
              @click="confirmDelId = activePlan.id"
            >
              删除
            </AppButton>
          </div>
        </header>

        <!-- 结构化周安排 -->
        <div v-if="activePlan.days && activePlan.days.length" class="days">
          <div
            v-for="(d, i) in activePlan.days"
            :key="i"
            class="day"
            :class="{ rest: d.rest, today: isToday(d.date) }"
          >
            <div class="day-head">
              <span class="day-wd">{{ d.weekday }}</span>
              <span class="day-date num">{{ d.date }}</span>
              <span v-if="isToday(d.date)" class="today-tag">今天</span>
            </div>
            <div v-if="d.rest" class="day-rest">休息日 · 主动恢复</div>
            <ul v-else class="day-items">
              <li v-for="(it, j) in d.items" :key="j" class="day-item">
                <span class="it-name">{{ it.name }}</span>
                <span v-if="it.detail" class="it-detail num">{{ it.detail }}</span>
              </li>
            </ul>
            <div v-if="d.focus" class="day-focus">{{ d.focus }}</div>
          </div>
        </div>

        <!-- 否则渲染 markdown 内容 -->
        <div v-else-if="activePlan.content" class="hero-body">
          <div class="prose" v-html="renderedContent" />
        </div>

        <p v-else class="hero-empty">这份计划还没有内容，可以在对话里让它重新生成。</p>
      </section>

      <!-- 无计划：引导生成 -->
      <EmptyState
        v-else
        icon="spark"
        title="还没有训练计划"
        desc="在对话框输入目标直接生成；也可以在「对话」里让助理结合你的训练数据出计划，生成后会在这里等你确认。"
      >
        <div class="gen">
          <input
            v-model="generateGoal"
            class="gen-input"
            placeholder="例如：减脂三分化 / 提升 1km 成绩"
            @keyup.enter="doGenerate"
          />
          <AppButton
            variant="primary"
            size="md"
            :busy="generating"
            :disabled="!generateGoal.trim()"
            @click="doGenerate"
          >
            生成计划
          </AppButton>
        </div>
        <p v-if="generateMsg" class="gen-msg">{{ generateMsg }}</p>
      </EmptyState>

      <!-- 备选方案 -->
      <template v-if="alternatives.length">
        <SectionTitle title="备选方案" :desc="`${alternatives.length} 份未启用`" />
        <div class="alts">
          <AppCard v-for="p in alternatives" :key="p.id" tone="neutral" hover>
            <div class="alt">
              <div class="alt-info">
                <h4 class="alt-name">{{ p.name }}</h4>
                <p class="alt-goal">{{ p.goal || '—' }}</p>
                <p class="alt-time">更新于 {{ fmtDate(p.updatedAt || p.createdAt) }}</p>
              </div>
              <div class="alt-ops">
                <template v-if="confirmDelId === p.id">
                  <AppButton variant="danger" size="sm" @click="doDelete(p.id)">确认删除</AppButton>
                  <AppButton variant="ghost" size="sm" @click="confirmDelId = null">取消</AppButton>
                </template>
                <template v-else>
                  <AppButton variant="subtle" size="sm" @click="doSwitch(p.id)">切换启用</AppButton>
                  <AppButton
                    variant="ghost"
                    size="sm"
                    :icon="TRASH_ICON"
                    @click="confirmDelId = p.id"
                  />
                </template>
              </div>
            </div>
          </AppCard>
        </div>
      </template>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import AppCard from '../components/ui/AppCard.vue'
import AppPill from '../components/ui/AppPill.vue'
import AppButton from '../components/ui/AppButton.vue'
import SectionTitle from '../components/ui/SectionTitle.vue'
import EmptyState from '../components/ui/EmptyState.vue'
import SkeletonBlock from '../components/ui/SkeletonBlock.vue'
import { getPlans, applyPlan, generatePlan, switchPlan, deletePlan, discardPending } from '../api/client'
import type { PlanData } from '../api/client'
import { renderMarkdown } from '../utils/markdown'

const STROKE =
  'fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"'
const REFRESH_ICON = `<svg viewBox="0 0 24 24" ${STROKE}><path d="M19.5 12a7.5 7.5 0 1 1-2.3-5.4"/><path d="M19.9 4.6v4.2h-4.2"/></svg>`
const TRASH_ICON = `<svg viewBox="0 0 24 24" ${STROKE}><path d="M5 7h14M9.5 7V5.4A1.4 1.4 0 0 1 10.9 4h2.2a1.4 1.4 0 0 1 1.4 1.4V7"/><path d="M6.6 7l.8 11.2A1.9 1.9 0 0 0 9.3 20h5.4a1.9 1.9 0 0 0 1.9-1.8L17.4 7"/></svg>`
const WARN_ICON = `<svg viewBox="0 0 24 24" ${STROKE}><path d="M12 4.5l8.2 14.2H3.8z"/><path d="M12 10v4M12 16.6v.2"/></svg>`
const SPARK_ICON = `<svg viewBox="0 0 24 24" ${STROKE}><path d="M12 3.4l1.9 5.4 5.4 1.9-5.4 1.9L12 18l-1.9-5.4L4.7 10.7l5.4-1.9z"/></svg>`

const activeId = ref<string | null>(null)
const pending = ref<PlanData | null>(null)
const plans = ref<PlanData[]>([])
const loading = ref(false)
const applying = ref(false)
const error = ref('')

const activePlan = computed(() => plans.value.find((p) => p.id === activeId.value) || null)
const alternatives = computed(() => plans.value.filter((p) => p.id !== activeId.value))

const headDesc = computed(() => {
  if (!activePlan.value) return '计划存放在本机 plans.json，与对话里生成的方案共用一份'
  return `来源 对话生成 · 更新于 ${updateDate.value}`
})
const updateDate = computed(() => fmtDate(activePlan.value?.updatedAt || activePlan.value?.createdAt))
const renderedContent = computed(() => renderMarkdown(activePlan.value?.content || ''))

function fmtDate(d?: string): string {
  if (!d) return '—'
  try {
    return new Date(d).toLocaleString('zh-CN', { hour12: false })
  } catch {
    return String(d).slice(0, 16)
  }
}

function isToday(date: string): boolean {
  if (!date) return false
  const t = new Date()
  const pad = (n: number) => String(n).padStart(2, '0')
  const today = `${t.getFullYear()}-${pad(t.getMonth() + 1)}-${pad(t.getDate())}`
  return String(date).replace(/\//g, '-').startsWith(today)
}

// 删除采用「二步确认」内联交互，替代原生 confirm 弹窗
const confirmDelId = ref<string | null>(null)

const generateGoal = ref('')
const generating = ref(false)
const generateMsg = ref('')

async function load() {
  loading.value = true
  error.value = ''
  try {
    const data = await getPlans()
    activeId.value = data.activeId
    pending.value = data.pending
    plans.value = data.plans || []
  } catch (e) {
    error.value = '读取计划失败：' + String(e)
  } finally {
    loading.value = false
  }
}

async function apply(action: 'replace' | 'add') {
  applying.value = true
  try {
    const res = await applyPlan(action)
    if (res.ok) {
      pending.value = null
      await load()
    } else {
      error.value = res.msg || '应用失败'
    }
  } catch (e) {
    error.value = String(e)
  } finally {
    applying.value = false
  }
}

async function doGenerate() {
  const goal = generateGoal.value.trim()
  if (!goal) return
  generating.value = true
  generateMsg.value = ''
  try {
    await generatePlan(goal)
    generateMsg.value = '已生成，请在上方选择「替换当前计划」或「加入为第二方案」。'
    generateGoal.value = ''
    await load()
  } catch (e) {
    generateMsg.value = '生成失败：' + String(e)
  } finally {
    generating.value = false
  }
}

async function doSwitch(id: string) {
  try {
    await switchPlan(id)
    await load()
  } catch (e) {
    error.value = String(e)
  }
}

async function doDelete(id: string) {
  confirmDelId.value = null
  try {
    const res = await deletePlan(id)
    if (res.ok) await load()
    else error.value = res.msg || '删除失败'
  } catch (e) {
    error.value = String(e)
  }
}

async function doDiscard() {
  try {
    const res = await discardPending()
    if (res.ok) {
      pending.value = null
      await load()
    }
  } catch (e) {
    error.value = String(e)
  }
}

onMounted(load)
</script>

<style scoped>
.plan-page {
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

.err-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 11px 14px;
  margin-bottom: var(--sp-4);
  border-radius: var(--r-md);
  background: rgba(255, 95, 86, 0.1);
  border: 1px solid rgba(255, 95, 86, 0.32);
  color: var(--danger);
  font-size: var(--fs-sm);
}
.err-bar :deep(svg) {
  width: 15px;
  height: 15px;
  flex: none;
}
.err-bar button {
  margin-left: auto;
  color: var(--danger);
  opacity: 0.7;
}
.err-bar button:hover {
  opacity: 1;
}

/* ---------- 待确认 ---------- */
.pending {
  margin-bottom: var(--sp-5);
}
.pd-head {
  display: flex;
  gap: var(--sp-3);
  align-items: flex-start;
}
.pd-badge {
  width: 32px;
  height: 32px;
  flex: none;
  display: grid;
  place-items: center;
  border-radius: var(--r-sm);
  color: var(--warn);
  background: rgba(240, 178, 60, 0.15);
  border: 1px solid rgba(240, 178, 60, 0.3);
}
.pd-badge :deep(svg) {
  width: 17px;
  height: 17px;
}
.pd-title {
  font-size: var(--fs-md);
  font-weight: var(--fw-semi);
  color: var(--ink);
}
.pd-desc {
  margin-top: 3px;
  font-size: var(--fs-sm);
  color: var(--ink-3);
}
.pd-acts {
  display: flex;
  gap: var(--sp-2);
  margin-top: var(--sp-4);
  flex-wrap: wrap;
}

.sk-stack {
  display: flex;
  flex-direction: column;
  gap: var(--sp-3);
}

/* ---------- 当前计划 hero ---------- */
.hero {
  position: relative;
  border-radius: var(--r-xl);
  background: linear-gradient(180deg, var(--surface-3) 0%, var(--surface-2) 48%);
  border: 1px solid var(--line-2);
  box-shadow: var(--hairline-top), var(--shadow-3);
  padding: var(--sp-6);
  overflow: hidden;
}
/* 右上角渐变色晕，呼应「进行中」的状态感 */
.hero-glow {
  position: absolute;
  top: -140px;
  right: -100px;
  width: 380px;
  height: 380px;
  border-radius: 50%;
  background: radial-gradient(circle, rgba(61, 139, 255, 0.22), rgba(42, 212, 200, 0.08) 45%, transparent 70%);
  filter: blur(38px);
  pointer-events: none;
}

.hero-head {
  position: relative;
  display: flex;
  align-items: flex-start;
  gap: var(--sp-4);
  padding-bottom: var(--sp-5);
  border-bottom: 1px solid var(--line);
}
.hero-eyebrow {
  display: flex;
  align-items: center;
  gap: 7px;
  font-size: var(--fs-xs);
  font-weight: var(--fw-semi);
  color: var(--accent-hi);
  letter-spacing: 0.06em;
}
.hero-eyebrow .dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--ok);
  box-shadow: 0 0 0 3px rgba(53, 209, 138, 0.18);
  animation: breathe 2s var(--ease-out) infinite;
}
.hero-name {
  margin-top: 9px;
  font-size: var(--fs-2xl);
  font-weight: var(--fw-bold);
  letter-spacing: -0.025em;
  line-height: 1.12;
  background: linear-gradient(180deg, #ffffff, #b9c6d8);
  -webkit-background-clip: text;
  background-clip: text;
  -webkit-text-fill-color: transparent;
}
.hero-tags {
  display: flex;
  gap: var(--sp-2);
  margin-top: var(--sp-3);
  flex-wrap: wrap;
}
.hero-meta {
  margin-top: var(--sp-3);
  display: flex;
  align-items: center;
  gap: 7px;
  font-size: var(--fs-xs);
  color: var(--ink-4);
}
.hero-meta i {
  font-style: normal;
  opacity: 0.6;
}
.hero-ops {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  flex: none;
  position: relative;
  z-index: 1;
}
.confirm-tip {
  font-size: var(--fs-xs);
  color: var(--danger);
}

/* ---------- 周安排卡片网格 ---------- */
.days {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(196px, 1fr));
  gap: var(--sp-3);
  margin-top: var(--sp-5);
}
.day {
  display: flex;
  flex-direction: column;
  gap: 9px;
  padding: var(--sp-4);
  border-radius: var(--r-md);
  background: var(--surface-1);
  border: 1px solid var(--line);
  transition: transform var(--t-base) var(--ease-out),
    border-color var(--t-base) var(--ease-out);
}
.day:hover {
  transform: translateY(-2px);
  border-color: var(--line-3);
}
.day.today {
  border-color: color-mix(in srgb, var(--accent) 55%, transparent);
  background: linear-gradient(180deg, rgba(61, 139, 255, 0.11), var(--surface-1));
  box-shadow: var(--ring-accent);
}
.day.rest {
  opacity: 0.72;
}
.day-head {
  display: flex;
  align-items: center;
  gap: 7px;
}
.day-wd {
  font-size: var(--fs-base);
  font-weight: var(--fw-semi);
  color: var(--ink);
}
.day-date {
  font-size: var(--fs-xs);
  color: var(--ink-4);
}
.today-tag {
  margin-left: auto;
  font-size: 10px;
  font-weight: var(--fw-semi);
  color: #06121f;
  background: var(--grad-accent);
  padding: 2px 7px;
  border-radius: var(--r-full);
}
.day-rest {
  font-size: var(--fs-sm);
  color: var(--ink-3);
  padding: 6px 0;
}
.day-items {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.day-item {
  display: flex;
  flex-direction: column;
  gap: 1px;
  padding-left: 9px;
  border-left: 2px solid color-mix(in srgb, var(--accent) 45%, transparent);
}
.it-name {
  font-size: var(--fs-sm);
  font-weight: var(--fw-medium);
  color: var(--ink-2);
}
.it-detail {
  font-size: var(--fs-xs);
  color: var(--ink-4);
}
.day-focus {
  margin-top: auto;
  align-self: flex-start;
  font-size: 10.5px;
  color: var(--ink-3);
  padding: 2px 8px;
  border-radius: var(--r-full);
  background: var(--surface-4);
  border: 1px solid var(--line);
}

.hero-body {
  margin-top: var(--sp-5);
}
.hero-empty {
  margin-top: var(--sp-5);
  font-size: var(--fs-sm);
  color: var(--ink-4);
}

/* ---------- 生成计划 ---------- */
.gen {
  display: flex;
  gap: var(--sp-2);
  width: 100%;
  max-width: 460px;
  margin: 0 auto;
}
.gen-input {
  flex: 1;
  min-width: 0;
  padding: 10px 14px;
  border-radius: var(--r-md);
  background: var(--surface-2);
  border: 1px solid var(--line-2);
  color: var(--ink);
  outline: none;
  transition: border-color var(--t-base) var(--ease-out), box-shadow var(--t-base) var(--ease-out);
}
.gen-input::placeholder {
  color: var(--ink-4);
}
.gen-input:focus {
  border-color: color-mix(in srgb, var(--accent) 55%, transparent);
  box-shadow: 0 0 0 3px rgba(61, 139, 255, 0.12);
}
.gen-msg {
  margin-top: var(--sp-3);
  font-size: var(--fs-sm);
  color: var(--ok);
}

/* ---------- 备选方案 ---------- */
.alts {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: var(--sp-4);
}
.alt {
  display: flex;
  align-items: center;
  gap: var(--sp-4);
}
.alt-info {
  min-width: 0;
}
.alt-name {
  font-size: var(--fs-md);
  font-weight: var(--fw-semi);
  color: var(--ink);
}
.alt-goal {
  margin-top: 3px;
  font-size: var(--fs-sm);
  color: var(--ink-3);
}
.alt-time {
  margin-top: 5px;
  font-size: var(--fs-xs);
  color: var(--ink-4);
}
.alt-ops {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  flex: none;
}
</style>
