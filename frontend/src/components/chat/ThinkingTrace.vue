<template>
  <div class="trace" :class="{ running: status === 'running' }">
    <!-- 头部：状态 + 进度 -->
    <div class="th">
      <span class="bolt" :class="status">
        <i v-if="status === 'running'" class="ring" />
        <span v-html="status === 'done' ? DONE_ICON : BOLT_ICON" />
      </span>
      <div class="th-text">
        <h4 class="th-title">多 Agent 协作</h4>
        <p class="th-sub">
          {{ status === 'running' ? '主 Agent 正在拆解与派发…' : `已完成 ${doneCount}/${steps.length} 步` }}
        </p>
      </div>
      <span class="th-count num">{{ steps.length }} 步</span>
    </div>

    <!-- 进度细条 -->
    <div class="prog">
      <i :style="{ width: progress + '%' }" />
    </div>

    <!-- 时间轴 -->
    <ol class="steps">
      <li
        v-for="(s, i) in steps"
        :key="s.name + i"
        class="step"
        :class="s.status"
      >
        <span class="rail">
          <i class="node">
            <b v-if="s.status === 'done'" v-html="CHECK_ICON" />
            <b v-else-if="s.status === 'failed'" v-html="X_ICON" />
          </i>
          <i v-if="i < steps.length - 1" class="line" />
        </span>

        <div class="body">
          <div class="line-row">
            <span class="mini" :style="{ color: meta(s.name).hue }" v-html="meta(s.name).icon" />
            <span class="label">{{ meta(s.name).label }}</span>
            <code class="name">{{ s.name }}</code>
            <span class="state">{{ statusText(s.status) }}</span>
            <button
              v-if="s.output"
              class="toggle"
              @click="toggle(i)"
            >{{ open.has(i) ? '收起' : '查看产出' }}</button>
          </div>
          <p v-if="meta(s.name).role" class="role">{{ meta(s.name).role }}</p>
          <Transition name="expand">
            <pre v-if="open.has(i) && s.output" class="out num">{{ s.output }}</pre>
          </Transition>
        </div>
      </li>
    </ol>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { ThinkingStep } from '../../types'
import { agentMeta } from '../../constants/agents'

const props = defineProps<{ steps: ThinkingStep[]; status: 'running' | 'done' }>()

const STROKE =
  'fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"'
const BOLT_ICON = `<svg viewBox="0 0 24 24" fill="currentColor"><path d="M13.4 2.6 5.2 13.3h4.6l-1.5 8.1 8.6-11h-4.7z"/></svg>`
const DONE_ICON = `<svg viewBox="0 0 24 24" ${STROKE}><path d="M5 12.8 9.6 17.4 19 7.6"/></svg>`
const CHECK_ICON = `<svg viewBox="0 0 24 24" ${STROKE}><path d="M6 12.6 10 16.6 18 7.8"/></svg>`
const X_ICON = `<svg viewBox="0 0 24 24" ${STROKE}><path d="M7 7l10 10M17 7 7 17"/></svg>`

const meta = (name: string) => agentMeta(name)

// 展开态：按步骤下标记录
const open = ref<Set<number>>(new Set())

function toggle(i: number) {
  const next = new Set(open.value)
  next.has(i) ? next.delete(i) : next.add(i)
  open.value = next
}

const doneCount = computed(() => props.steps.filter((s) => s.status === 'done').length)
const progress = computed(() => {
  if (!props.steps.length) return 0
  const settled = props.steps.filter((s) => s.status === 'done' || s.status === 'failed').length
  return Math.round((settled / props.steps.length) * 100)
})

// 出错即展开：用户最需要先看到失败原因，不用再点一次
// （用 watch 而非 setup 内一次性判断：steps 是编排过程中逐步 push 的）
watch(
  () => props.steps.map((s) => s.status).join(','),
  () => {
    const idx = props.steps.findIndex((s) => s.status === 'failed')
    if (idx >= 0 && !open.value.has(idx)) {
      const next = new Set(open.value)
      next.add(idx)
      open.value = next
    }
  },
)

function statusText(s: ThinkingStep['status']) {
  return s === 'idle' ? '等待' : s === 'running' ? '执行中' : s === 'done' ? '完成' : '失败'
}
</script>

<style scoped>
.trace {
  border-radius: var(--r-lg);
  background: linear-gradient(180deg, var(--surface-3) 0%, var(--surface-2) 55%);
  border: 1px solid var(--line-2);
  box-shadow: var(--hairline-top), var(--shadow-2);
  padding: var(--sp-4) var(--sp-5) var(--sp-5);
  max-width: 100%;
  overflow: hidden;
}
.running {
  border-color: color-mix(in srgb, var(--accent) 34%, transparent);
}

.th {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
}
.bolt {
  position: relative;
  width: 30px;
  height: 30px;
  flex: none;
  display: grid;
  place-items: center;
  border-radius: var(--r-sm);
  background: var(--grad-accent-soft);
  border: 1px solid var(--line-2);
  color: var(--accent-hi);
}
.bolt.done {
  color: var(--ok);
  background: rgba(53, 209, 138, 0.12);
  border-color: rgba(53, 209, 138, 0.28);
}
.bolt :deep(svg) {
  width: 15px;
  height: 15px;
}
.ring {
  position: absolute;
  inset: -1px;
  border-radius: var(--r-sm);
  animation: pulse-ring 1.6s var(--ease-out) infinite;
}

.th-text {
  min-width: 0;
}
.th-title {
  font-size: var(--fs-base);
  font-weight: var(--fw-semi);
  color: var(--ink);
  letter-spacing: -0.01em;
}
.th-sub {
  margin-top: 2px;
  font-size: var(--fs-xs);
  color: var(--ink-4);
}
.th-count {
  margin-left: auto;
  flex: none;
  font-size: var(--fs-xs);
  color: var(--ink-3);
  padding: 4px 9px;
  border-radius: var(--r-full);
  background: var(--surface-4);
  border: 1px solid var(--line);
}

.prog {
  height: 2px;
  border-radius: var(--r-full);
  background: var(--surface-4);
  margin: var(--sp-4) 0 var(--sp-3);
  overflow: hidden;
}
.prog i {
  display: block;
  height: 100%;
  border-radius: var(--r-full);
  background: var(--grad-accent);
  transition: width var(--t-slow) var(--ease-out);
}

.steps {
  display: flex;
  flex-direction: column;
}

.step {
  display: flex;
  gap: var(--sp-3);
}

/* 左侧时间轴：节点 + 连线 */
.rail {
  position: relative;
  width: 18px;
  flex: none;
  display: flex;
  flex-direction: column;
  align-items: center;
}
.node {
  position: relative;
  z-index: 1;
  width: 15px;
  height: 15px;
  margin-top: 3px;
  border-radius: 50%;
  display: grid;
  place-items: center;
  background: var(--surface-4);
  border: 1.6px solid var(--line-3);
  color: transparent;
  transition: background var(--t-base) var(--ease-out),
    border-color var(--t-base) var(--ease-out);
}
.node :deep(svg) {
  width: 10px;
  height: 10px;
}
.line {
  flex: 1;
  width: 1.6px;
  margin: 3px 0;
  background: var(--line-2);
  border-radius: var(--r-full);
}

/* 四种状态 */
.step.running .node {
  background: var(--accent);
  border-color: var(--accent);
  animation: pulse-ring 1.6s var(--ease-out) infinite;
}
.step.done .node {
  background: var(--ok);
  border-color: var(--ok);
  color: #06121f;
}
.step.failed .node {
  background: var(--danger);
  border-color: var(--danger);
  color: #fff;
}
.step.done .line {
  background: color-mix(in srgb, var(--ok) 45%, var(--line-2));
}

.body {
  flex: 1;
  min-width: 0;
  padding-bottom: var(--sp-4);
}
.step:last-child .body {
  padding-bottom: 0;
}

.line-row {
  display: flex;
  align-items: center;
  gap: 8px;
  min-height: 21px;
  flex-wrap: wrap;
}
.mini {
  width: 15px;
  height: 15px;
  flex: none;
  display: inline-flex;
}
.mini :deep(svg) {
  width: 100%;
  height: 100%;
}
.label {
  font-size: var(--fs-sm);
  font-weight: var(--fw-semi);
  color: var(--ink);
}
.step.idle .label {
  color: var(--ink-3);
  font-weight: var(--fw-medium);
}
.name {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--ink-4);
  background: var(--surface-4);
  padding: 1px 6px;
  border-radius: var(--r-xs);
  border: 1px solid var(--line);
}
.state {
  font-size: 11px;
  color: var(--ink-4);
}
.step.running .state {
  color: var(--accent-hi);
}
.step.done .state {
  color: var(--ok);
}
.step.failed .state {
  color: var(--danger);
}

.toggle {
  margin-left: auto;
  font-size: 11px;
  color: var(--ink-3);
  padding: 3px 8px;
  border-radius: var(--r-full);
  border: 1px solid var(--line-2);
  transition: color var(--t-fast) var(--ease-out), border-color var(--t-fast) var(--ease-out);
}
.toggle:hover {
  color: var(--accent-hi);
  border-color: color-mix(in srgb, var(--accent) 45%, transparent);
}

.role {
  margin-top: 2px;
  font-size: var(--fs-xs);
  color: var(--ink-4);
}

.out {
  margin-top: var(--sp-2);
  padding: 11px 13px;
  max-height: 220px;
  overflow: auto;
  border-radius: var(--r-sm);
  background: var(--pre-bg);
  border: 1px solid var(--line);
  font-size: 11.5px;
  line-height: 1.65;
  color: var(--ink-2);
  white-space: pre-wrap;
  word-break: break-word;
}

.expand-enter-active,
.expand-leave-active {
  transition: opacity var(--t-base) var(--ease-out);
}
.expand-enter-from,
.expand-leave-to {
  opacity: 0;
}
</style>
