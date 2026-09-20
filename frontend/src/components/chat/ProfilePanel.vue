<template>
  <aside class="panel">
    <header class="p-head">
      <div>
        <h3 class="p-title">用户画像</h3>
        <p class="p-sub">来自长期记忆 <code>USER.md</code></p>
      </div>
      <button class="refresh" title="刷新" :class="{ spinning }" @click="reload">
        <span v-html="REFRESH_ICON" />
      </button>
    </header>

    <div class="p-body">
      <ul v-if="entries.length" class="facts">
        <li
          v-for="(e, i) in entries"
          :key="i"
          class="fact"
          :class="{ confirming: confirmIdx === i }"
        >
          <span class="mk" :class="'c' + (i % 4)" />
          <div class="f-main">
            <span class="tx">{{ e.text }}</span>
            <!-- 删除用二步确认内联展开（与「计划」模块一致），不用原生 confirm 弹窗 -->
            <div v-if="confirmIdx === i" class="ops">
              <span class="ops-tip">删除后不可恢复</span>
              <div class="ops-row">
                <AppButton variant="danger" size="sm" :busy="busy" @click="doDelete(i, e.id)">
                  确认删除
                </AppButton>
                <AppButton variant="ghost" size="sm" :disabled="busy" @click="cancelDelete">
                  取消
                </AppButton>
              </div>
            </div>
            <p v-if="err && errIdx === i" class="err">{{ err }}</p>
          </div>
          <button
            v-if="confirmIdx !== i"
            class="del"
            type="button"
            title="删除这条画像"
            aria-label="删除这条画像"
            @click="askDelete(i)"
          >
            <span v-html="TRASH_ICON" />
          </button>
        </li>
      </ul>
      <div v-else class="none">
        <p>还没有写入画像</p>
        <span>对话中提到你的身体状况、目标或偏好，助理会记进 USER 记忆。</span>
      </div>
    </div>

    <footer class="p-foot">
      <span class="lock" v-html="LOCK_ICON" />
      数据只存本机，不上传
    </footer>
  </aside>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import AppButton from '../ui/AppButton.vue'
import { forgetMemoryById, type MemoryEntry } from '../../api/client'

const props = defineProps<{ entries: MemoryEntry[] }>()
const emit = defineEmits<{ reload: [] }>()

const STROKE =
  'fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"'
const REFRESH_ICON = `<svg viewBox="0 0 24 24" ${STROKE}><path d="M19.5 12a7.5 7.5 0 1 1-2.3-5.4"/><path d="M19.9 4.6v4.2h-4.2"/></svg>`
const LOCK_ICON = `<svg viewBox="0 0 24 24" ${STROKE}><rect x="5" y="10.4" width="14" height="9.6" rx="2.2"/><path d="M8.4 10.4V7.8a3.6 3.6 0 0 1 7.2 0v2.6"/></svg>`
const TRASH_ICON = `<svg viewBox="0 0 24 24" ${STROKE}><path d="M4.8 7.4h14.4"/><path d="M9.6 7.4V5.6h4.8v1.8"/><path d="M6.6 7.4 7.6 19a1.4 1.4 0 0 0 1.4 1.3h6a1.4 1.4 0 0 0 1.4-1.3l1-11.6"/><path d="M10.2 11.2v5.2M13.8 11.2v5.2"/></svg>`

const spinning = ref(false)
function reload() {
  spinning.value = true
  emit('reload')
  setTimeout(() => (spinning.value = false), 700)
}

// ---- 逐条删除（2026-09-17：用户可以自主删掉不用的画像）----
const confirmIdx = ref<number | null>(null)
const errIdx = ref<number | null>(null)
const busy = ref(false)
const err = ref('')

// 列表刷新后索引会整体前移，确认态必须清掉——否则「取消 / 确认」会落到另一条上
watch(
  () => props.entries,
  () => {
    confirmIdx.value = null
    errIdx.value = null
    err.value = ''
  },
)

function askDelete(i: number) {
  err.value = ''
  errIdx.value = null
  confirmIdx.value = i
}

function cancelDelete() {
  confirmIdx.value = null
}

async function doDelete(i: number, id: number) {
  busy.value = true
  err.value = ''
  try {
    // 面板自己发请求：emit 没法把失败原因（后端是 `{ok:false,msg}` 这种返回值式错误，
    // 不抛异常）回传给父组件，而失败必须在点下去的那一条上就地显示。
    // 传 /memory 返回的稳定 id——后端按主键精确删；两条内容有包含关系的条目也不会删错。
    const res = await forgetMemoryById(id)
    confirmIdx.value = null
    if (res.ok) {
      emit('reload')
    } else {
      errIdx.value = i
      err.value = res.msg || '删除失败'
    }
  } catch (e) {
    confirmIdx.value = null
    errIdx.value = i
    err.value = '删除失败：' + String(e)
  } finally {
    busy.value = false
  }
}
</script>

<style scoped>
.panel {
  width: var(--panel-w);
  flex: none;
  height: 100vh;
  display: flex;
  flex-direction: column;
  background: color-mix(in srgb, var(--surface-1) 68%, transparent);
  backdrop-filter: blur(16px);
  border-left: 1px solid var(--line);
}

.p-head {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
  padding: var(--sp-5) var(--sp-4) var(--sp-4);
  border-bottom: 1px solid var(--line);
}
.p-title {
  font-size: var(--fs-base);
  font-weight: var(--fw-semi);
  color: var(--ink);
}
.p-sub {
  margin-top: 3px;
  font-size: var(--fs-2xs);
  color: var(--ink-4);
}
.p-sub code {
  font-family: var(--font-mono);
  font-size: var(--fs-2xs);
  padding: 1px 4px;
  border-radius: var(--r-xs);
  background: var(--surface-4);
  border: 1px solid var(--line);
}
.refresh {
  margin-left: auto;
  width: 27px;
  height: 27px;
  display: grid;
  place-items: center;
  border-radius: var(--r-sm);
  color: var(--ink-4);
  transition: color var(--t-fast) var(--ease-out), background var(--t-fast) var(--ease-out);
}
.refresh:hover {
  color: var(--accent-hi);
  background: var(--surface-3);
}
.refresh.spinning span {
  display: inline-flex;
  animation: spin 0.7s linear infinite;
}
.refresh :deep(svg) {
  width: 14px;
  height: 14px;
}

.p-body {
  flex: 1;
  overflow-y: auto;
  padding: var(--sp-4);
}

.facts {
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
}
.fact {
  display: flex;
  gap: 9px;
  padding: 10px 12px;
  border-radius: var(--r-md);
  background: var(--surface-2);
  border: 1px solid var(--line);
  transition: border-color var(--t-base) var(--ease-out),
    transform var(--t-base) var(--ease-out);
}
.fact:hover {
  transform: translateX(1px);
  border-color: var(--line-3);
}
/* 待确认删除的那一条：整体染红，避免点错 */
.fact.confirming {
  background: color-mix(in srgb, var(--danger) 9%, var(--surface-2));
  border-color: color-mix(in srgb, var(--danger) 38%, transparent);
}
.f-main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 9px;
}

.ops {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 8px;
}
.ops-row {
  display: flex;
  flex-wrap: wrap;
  gap: var(--sp-2);
}
.ops-tip {
  font-size: var(--fs-2xs);
  color: var(--danger);
}
.err {
  font-size: var(--fs-2xs);
  color: var(--danger);
  line-height: var(--lh-normal);
  word-break: break-all;
}

.del {
  width: 24px;
  height: 24px;
  flex: none;
  display: grid;
  place-items: center;
  border-radius: var(--r-sm);
  color: var(--ink-4);
  transition: color var(--t-fast) var(--ease-out), background var(--t-fast) var(--ease-out);
}
.del:hover {
  color: var(--danger);
  background: var(--danger-soft);
}
.del :deep(svg) {
  width: 14px;
  height: 14px;
}
/* 每条前的小圆点轮换 4 种语义色，让列表有节奏 */
.mk {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  flex: none;
  margin-top: 6px;
  background: var(--accent);
}
.mk.c1 {
  background: var(--accent-2);
}
.mk.c2 {
  background: var(--warn);
}
.mk.c3 {
  background: var(--energy);
}
.tx {
  font-size: var(--fs-sm);
  color: var(--ink-2);
  line-height: var(--lh-normal);
}

.none {
  padding: 30px 14px;
  text-align: center;
}
.none p {
  font-size: var(--fs-sm);
  color: var(--ink-3);
  font-weight: var(--fw-medium);
}
.none span {
  display: block;
  margin-top: 7px;
  font-size: var(--fs-xs);
  color: var(--ink-4);
  line-height: var(--lh-normal);
}

.p-foot {
  display: flex;
  align-items: center;
  gap: 7px;
  padding: var(--sp-3) var(--sp-4);
  border-top: 1px solid var(--line);
  font-size: var(--fs-2xs);
  color: var(--ink-4);
}
.lock {
  width: 13px;
  height: 13px;
  display: inline-flex;
  color: var(--ok);
}
.lock :deep(svg) {
  width: 100%;
  height: 100%;
}
</style>
