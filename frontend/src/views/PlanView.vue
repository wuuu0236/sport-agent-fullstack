<template>
  <div class="plan-page">
    <header class="plan-header">
      <div class="brand">
        <div class="brand-en">SPORT / TRAINING</div>
        <div class="brand-name">战狼养成系统</div>
      </div>
      <div class="meta">
        <span class="sync-dot"></span>
        <span>数据已同步 {{ syncTime }}</span>
        <span class="sep">·</span>
        <span>来源 {{ planSource }} · 更新于 {{ updateDate }}</span>
      </div>
    </header>

    <!-- 待确认计划（由聊天生成后提示） -->
    <section v-if="pending" class="pending-card">
      <div class="pending-title">🆕 待确认计划：{{ pending.name }}</div>
      <div class="pending-desc">
        聊天中刚生成一份新计划。请选择如何应用到左侧「计划」模块：
      </div>
      <div class="pending-actions">
        <button class="btn-primary" @click="apply('replace')">替换当前计划</button>
        <button class="btn-secondary" @click="apply('add')">加入为第二方案</button>
        <button class="btn-ghost btn-discard" @click="doDiscard">放弃</button>
      </div>
    </section>

    <!-- 主卡片 -->
    <section v-if="activePlan" class="hero-card">
      <button class="hero-del" title="删除当前计划" @click="doDelete(activePlan.id, activePlan.name)">🗑 删除</button>
      <div class="hero-bg" aria-hidden="true">
        <div class="hero-blob hero-blob-1"></div>
        <div class="hero-blob hero-blob-2"></div>
      </div>

      <div class="hero-content">
        <div class="today-title">{{ activePlan.name || '当前训练计划' }}</div>
        <div class="today-sub">{{ activePlan.goal }}</div>
        <div class="today-meta">
          <span>{{ activePlan.cycleMeta || activePlan.goal }}</span>
          <span v-if="activePlan.countdown" class="countdown">{{ activePlan.countdown }}</span>
        </div>

        <div class="divider"></div>

        <!-- 结构化 days（若后端解析成功） -->
        <template v-if="activePlan.days && activePlan.days.length">
          <div class="next-week">
            <div class="next-label">NEXT WEEK / 下一周安排</div>
            <div class="next-title">{{ activePlan.name }}</div>
          </div>
          <div class="plan-table">
            <div class="table-head">
              <span>日期</span>
              <span>周几</span>
              <span>主项安排</span>
              <span>本日重点</span>
            </div>
            <div
              v-for="(day, i) in activePlan.days"
              :key="i"
              class="table-row"
              :class="{ rest: day.rest }"
            >
              <span class="col-date">{{ day.date }}</span>
              <span class="col-weekday">{{ day.weekday }}</span>
              <span class="col-main">
                <span v-if="day.rest" class="rest-badge">休息日</span>
                <template v-else>
                  <div v-for="(item, j) in day.items" :key="j" class="workout-line">
                    <strong>{{ item.name }}</strong>
                    <span class="detail">{{ item.detail }}</span>
                  </div>
                </template>
              </span>
              <span class="col-focus">{{ day.focus }}</span>
            </div>
          </div>
        </template>

        <!-- 否则渲染 markdown 内容 -->
        <div v-else-if="activePlan.content" class="markdown-content" v-html="renderedContent"></div>
      </div>
    </section>

    <!-- 无计划：引导生成 -->
    <section v-else class="empty-card">
      <div class="empty-icon">📋</div>
      <div class="empty-title">还没有训练计划</div>
      <div class="empty-desc">
        你可以在聊天里说「帮我生成减脂三分化计划」，生成后会询问是否更新到这里；也可以直接在下框输入目标生成。
      </div>
      <div class="generate-box">
        <input v-model="generateGoal" placeholder="例如：减脂三分化" @keyup.enter="doGenerate" />
        <button class="btn-primary" :disabled="generating" @click="doGenerate">
          {{ generating ? '生成中…' : '生成计划' }}
        </button>
      </div>
      <div v-if="generateMsg" class="generate-msg">{{ generateMsg }}</div>
    </section>

    <!-- 备选方案 -->
    <section v-if="alternatives.length" class="alt-section">
      <div class="alt-title">备选方案</div>
      <div class="alt-list">
        <div v-for="p in alternatives" :key="p.id" class="alt-item">
          <div class="alt-info">
            <div class="alt-name">{{ p.name }}</div>
            <div class="alt-goal">{{ p.goal }}</div>
          </div>
          <div class="alt-ops">
            <button class="btn-ghost" @click="doSwitch(p.id)">切换</button>
            <button class="btn-ghost btn-del" title="删除方案" @click="doDelete(p.id, p.name)">🗑</button>
          </div>
        </div>
      </div>
    </section>

    <div class="bg-tip">
      提示：可在「外观」设置上传自己的动漫/健身人物背景图，铺满聊天区域
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { getPlans, applyPlan, generatePlan, switchPlan, deletePlan, discardPending } from '../api/client'
import type { PlanData } from '../api/client'

const activeId = ref<string | null>(null)
const pending = ref<PlanData | null>(null)
const plans = ref<PlanData[]>([])
const loading = ref(false)
const error = ref('')

const activePlan = computed(() => plans.value.find((p) => p.id === activeId.value) || null)
const alternatives = computed(() => plans.value.filter((p) => p.id !== activeId.value))
const syncTime = computed(() => {
  const d = activePlan.value?.updatedAt || activePlan.value?.createdAt
  if (!d) return '-'
  try {
    return new Date(d).toLocaleString('zh-CN')
  } catch {
    return d
  }
})
const updateDate = computed(() => {
  const d = activePlan.value?.updatedAt || activePlan.value?.createdAt
  if (!d) return '-'
  try {
    return new Date(d).toLocaleDateString('zh-CN')
  } catch {
    return d.slice(0, 10)
  }
})
const planSource = computed(() => (activePlan.value ? 'assistant' : 'v10'))

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
    error.value = String(e)
  } finally {
    loading.value = false
  }
}

async function apply(action: 'replace' | 'add') {
  try {
    const res = await applyPlan(action)
    if (res.ok) {
      pending.value = null
      await load()
    }
  } catch (e) {
    error.value = String(e)
  }
}

async function doGenerate() {
  if (!generateGoal.value.trim()) return
  generating.value = true
  generateMsg.value = ''
  try {
    await generatePlan(generateGoal.value.trim())
    generateMsg.value = '已生成，请在上方选择「替换当前计划」或「加入第二方案」。'
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

async function doDelete(id: string, name: string) {
  if (!confirm(`确定删除计划「${name}」吗？此操作不可撤销。`)) return
  try {
    const res = await deletePlan(id)
    if (res.ok) {
      await load()
    } else {
      error.value = res.msg || '删除失败'
    }
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

function escapeHtml(str: string): string {
  return str
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
}

function renderMarkdown(md: string): string {
  if (!md) return ''
  const lines = md.split('\n')
  const out: string[] = []
  let inList = false
  let inTable = false
  const tableRows: string[] = []

  const flushTable = () => {
    if (tableRows.length < 2) {
      out.push(...tableRows.map((l) => `<p>${escapeHtml(l)}</p>`))
    } else {
      const headCells = tableRows[0]
        .split('|')
        .filter((_, i, arr) => i > 0 && i < arr.length - 1)
        .map((c) => `<th>${escapeHtml(c.trim())}</th>`)
        .join('')
      const bodyRows = tableRows.slice(2)
        .map((row) => {
          const cells = row
            .split('|')
            .filter((_, i, arr) => i > 0 && i < arr.length - 1)
            .map((c) => `<td>${escapeHtml(c.trim())}</td>`)
            .join('')
          return `<tr>${cells}</tr>`
        })
        .join('')
      out.push(`<table class="md-table"><thead><tr>${headCells}</tr></thead><tbody>${bodyRows}</tbody></table>`)
    }
    tableRows.length = 0
    inTable = false
  }

  const flushList = () => {
    if (inList) {
      out.push('</ul>')
      inList = false
    }
  }

  for (let line of lines) {
    line = line.trimEnd()
    if (!line) {
      if (inTable) flushTable()
      continue
    }

    // table
    if (line.startsWith('|')) {
      if (inList) flushList()
      inTable = true
      tableRows.push(line)
      continue
    } else if (inTable) {
      flushTable()
    }

    // headings
    if (line.startsWith('### ')) {
      flushList()
      out.push(`<h3>${escapeHtml(line.slice(4))}</h3>`)
      continue
    }
    if (line.startsWith('## ')) {
      flushList()
      out.push(`<h2>${escapeHtml(line.slice(3))}</h2>`)
      continue
    }
    if (line.startsWith('# ')) {
      flushList()
      out.push(`<h1>${escapeHtml(line.slice(2))}</h1>`)
      continue
    }

    // list
    if (line.startsWith('- ') || line.startsWith('* ')) {
      if (!inList) {
        out.push('<ul>')
        inList = true
      }
      out.push(`<li>${inlineFormat(line.slice(2))}</li>`)
      continue
    } else {
      flushList()
    }

    // normal paragraph
    out.push(`<p>${inlineFormat(line)}</p>`)
  }
  if (inTable) flushTable()
  flushList()
  return out.join('')
}

function inlineFormat(text: string): string {
  let s = escapeHtml(text)
  // bold
  s = s.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
  // italic
  s = s.replace(/\*(.+?)\*/g, '<em>$1</em>')
  return s
}

const renderedContent = computed(() => {
  const c = activePlan.value?.content
  return c ? renderMarkdown(c) : ''
})

onMounted(load)
</script>

<style scoped>
.plan-page {
  flex: 1;
  min-width: 0;
  padding: 28px 36px 36px;
  height: 100vh;
  overflow-y: auto;
  box-sizing: border-box;
  scrollbar-width: thin;
  scrollbar-color: var(--border) transparent;
}

.plan-header {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  margin-bottom: 22px;
}
.brand-en {
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.18em;
  color: var(--faint);
  text-transform: uppercase;
}
.brand-name {
  font-size: 28px;
  font-weight: 800;
  margin-top: 6px;
  color: var(--text);
  letter-spacing: 0.04em;
}
.meta {
  font-size: 13px;
  color: var(--muted);
  display: flex;
  align-items: center;
  gap: 8px;
}
.sync-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--ok);
  box-shadow: 0 0 8px var(--ok);
}
.sep {
  color: var(--faint);
}

.pending-card {
  margin-bottom: 18px;
  padding: 18px 20px;
  border-radius: 16px;
  border: 1px solid var(--accent);
  background: color-mix(in srgb, var(--accent-soft) 24%, transparent);
  color: var(--text);
}
.pending-title {
  font-size: 16px;
  font-weight: 700;
  margin-bottom: 6px;
}
.pending-desc {
  font-size: 13px;
  color: var(--text-soft);
  margin-bottom: 12px;
}
.pending-actions {
  display: flex;
  gap: 10px;
}

.hero-card {
  position: relative;
  min-height: 640px;
  border-radius: 24px;
  background: color-mix(in srgb, var(--card) 92%, transparent);
  border: 1px solid var(--border);
  overflow: hidden;
  box-shadow: 0 24px 70px rgba(0, 0, 0, 0.35);
}
.hero-bg {
  position: absolute;
  right: -40px;
  top: 0;
  bottom: 0;
  width: 55%;
  pointer-events: none;
  overflow: hidden;
  z-index: 1;
}
.hero-blob {
  position: absolute;
  border-radius: 50%;
  filter: blur(46px);
}
.hero-blob-1 {
  width: 340px;
  height: 340px;
  right: -50px;
  bottom: -70px;
  opacity: 0.55;
  background: radial-gradient(
    circle at 50% 50%,
    color-mix(in srgb, var(--accent) 55%, transparent),
    transparent 70%
  );
}
.hero-blob-2 {
  width: 210px;
  height: 210px;
  right: 150px;
  top: 70px;
  opacity: 0.42;
  background: radial-gradient(
    circle at 50% 50%,
    color-mix(in srgb, var(--ok) 45%, transparent),
    transparent 70%
  );
}
.hero-content {
  position: relative;
  z-index: 2;
  max-width: 62%;
  padding: 34px 38px 38px;
}
.hero-del {
  position: absolute;
  top: 16px;
  right: 18px;
  z-index: 3;
  padding: 7px 13px;
  border-radius: 10px;
  border: 1px solid var(--border);
  background: color-mix(in srgb, var(--bg) 70%, transparent);
  color: var(--text-soft);
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.12s, color 0.12s, border-color 0.12s;
}
.hero-del:hover {
  background: var(--danger-soft);
  color: var(--danger);
  border-color: var(--danger);
}

.today-title {
  font-size: 38px;
  font-weight: 800;
  color: var(--text);
  letter-spacing: 0.03em;
}
.today-sub {
  font-size: 16px;
  color: var(--text-soft);
  margin-top: 8px;
}
.today-meta {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-top: 14px;
  font-size: 13px;
  color: var(--muted);
}
.countdown {
  color: var(--accent);
  font-weight: 600;
}

.divider {
  height: 1px;
  background: linear-gradient(to right, var(--border), transparent);
  margin: 26px 0;
}

.next-week {
  margin-bottom: 18px;
}
.next-label {
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.16em;
  color: var(--faint);
  text-transform: uppercase;
}
.next-title {
  font-size: 22px;
  font-weight: 700;
  color: var(--text);
  margin-top: 6px;
}

.plan-table {
  border-radius: 16px;
  border: 1px solid var(--border-soft);
  overflow: hidden;
  background: color-mix(in srgb, var(--bg-soft) 72%, transparent);
  backdrop-filter: blur(8px);
}
.table-head,
.table-row {
  display: grid;
  grid-template-columns: 70px 56px 1fr 240px;
  gap: 14px;
  padding: 14px 18px;
  font-size: 14px;
  align-items: center;
}
.table-head {
  background: color-mix(in srgb, var(--bg-soft) 90%, transparent);
  color: var(--faint);
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}
.table-row {
  border-top: 1px solid var(--border-soft);
  color: var(--text-soft);
  transition: background 0.12s;
}
.table-row:hover {
  background: color-mix(in srgb, var(--card-hover) 60%, transparent);
}
.table-row.rest {
  opacity: 0.72;
}
.col-date {
  color: var(--accent);
  font-weight: 700;
  font-variant-numeric: tabular-nums;
}
.col-weekday {
  color: var(--muted);
}
.col-main {
  display: flex;
  flex-direction: column;
  gap: 5px;
}
.workout-line strong {
  color: var(--text);
  font-weight: 600;
  margin-right: 10px;
}
.workout-line .detail {
  color: var(--muted);
}
.rest-badge {
  display: inline-flex;
  align-self: flex-start;
  padding: 4px 10px;
  border-radius: 20px;
  background: var(--accent-soft);
  color: var(--accent);
  font-size: 12px;
  font-weight: 600;
}
.col-focus {
  color: var(--muted);
  font-size: 13px;
  line-height: 1.5;
}

.markdown-content {
  color: var(--text-soft);
  font-size: 14px;
  line-height: 1.7;
}
.markdown-content :deep(h1),
.markdown-content :deep(h2),
.markdown-content :deep(h3) {
  color: var(--text);
  margin: 18px 0 10px;
}
.markdown-content :deep(p) {
  margin: 8px 0;
}
.markdown-content :deep(ul) {
  margin: 8px 0;
  padding-left: 20px;
}
.markdown-content :deep(li) {
  margin: 4px 0;
}
.markdown-content :deep(.md-table) {
  width: 100%;
  border-collapse: collapse;
  margin: 14px 0;
  font-size: 13px;
  background: color-mix(in srgb, var(--bg-soft) 70%, transparent);
  border-radius: 12px;
  overflow: hidden;
}
.markdown-content :deep(.md-table th),
.markdown-content :deep(.md-table td) {
  padding: 10px 12px;
  border-top: 1px solid var(--border-soft);
  text-align: left;
  vertical-align: top;
}
.markdown-content :deep(.md-table th) {
  color: var(--faint);
  font-weight: 600;
  background: color-mix(in srgb, var(--bg-soft) 90%, transparent);
}
.markdown-content :deep(.md-table tr:first-child th) {
  border-top: none;
}
.markdown-content :deep(strong) {
  color: var(--text);
}

.empty-card {
  min-height: 420px;
  border-radius: 24px;
  background: color-mix(in srgb, var(--card) 92%, transparent);
  border: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  padding: 40px;
  text-align: center;
}
.empty-icon {
  font-size: 48px;
}
.empty-title {
  font-size: 22px;
  font-weight: 700;
  color: var(--text);
}
.empty-desc {
  font-size: 14px;
  color: var(--muted);
  max-width: 420px;
  line-height: 1.6;
}
.generate-box {
  display: flex;
  gap: 10px;
  margin-top: 10px;
}
.generate-box input {
  width: 220px;
  padding: 10px 12px;
  border-radius: 10px;
  border: 1px solid var(--border);
  background: var(--bg-soft);
  color: var(--text);
  font-size: 14px;
}
.generate-msg {
  font-size: 13px;
  color: var(--text-soft);
  margin-top: 6px;
}

.alt-section {
  margin-top: 22px;
}
.alt-title {
  font-size: 13px;
  font-weight: 700;
  color: var(--faint);
  letter-spacing: 0.08em;
  text-transform: uppercase;
  margin-bottom: 10px;
}
.alt-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.alt-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 16px;
  border-radius: 12px;
  background: color-mix(in srgb, var(--card) 80%, transparent);
  border: 1px solid var(--border-soft);
}
.alt-ops {
  display: flex;
  align-items: center;
  gap: 8px;
}
.alt-ops .btn-del {
  color: var(--faint);
}
.alt-ops .btn-del:hover {
  background: var(--danger-soft);
  color: var(--danger);
  border-color: var(--danger);
}
.btn-discard {
  color: var(--muted);
}
.btn-discard:hover {
  background: var(--danger-soft);
  color: var(--danger);
  border-color: var(--danger);
}
.alt-name {
  font-size: 15px;
  font-weight: 600;
  color: var(--text);
}
.alt-goal {
  font-size: 12px;
  color: var(--muted);
  margin-top: 2px;
}

.btn-primary,
.btn-secondary,
.btn-ghost {
  padding: 8px 14px;
  border-radius: 10px;
  border: 1px solid var(--border);
  background: var(--bg);
  color: var(--text);
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.12s, color 0.12s, border-color 0.12s;
}
.btn-primary {
  background: var(--accent);
  color: #fff;
  border-color: var(--accent);
}
.btn-primary:hover {
  filter: brightness(1.1);
}
.btn-secondary:hover,
.btn-ghost:hover {
  background: var(--card-hover);
}
.btn-primary:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.bg-tip {
  margin-top: 16px;
  font-size: 12px;
  color: var(--faint);
  text-align: right;
}

@media (max-width: 1100px) {
  .hero-bg {
    display: none;
  }
  .hero-content {
    max-width: 100%;
  }
  .table-head,
  .table-row {
    grid-template-columns: 64px 48px 1fr 180px;
  }
}
@media (max-width: 760px) {
  .plan-header {
    flex-direction: column;
    align-items: flex-start;
    gap: 10px;
  }
  .table-head,
  .table-row {
    grid-template-columns: 1fr;
    gap: 6px;
  }
  .table-head {
    display: none;
  }
  .table-row {
    padding: 16px;
  }
  .generate-box {
    flex-direction: column;
  }
  .generate-box input {
    width: 100%;
  }
}
</style>
