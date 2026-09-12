<template>
  <aside class="side">
    <div class="head">
      <h2 class="title">对话</h2>
      <button class="add" title="新建对话" @click="emit('new')">
        <span v-html="PLUS_ICON" />
      </button>
    </div>

    <div class="search">
      <span class="s-ico" v-html="SEARCH_ICON" />
      <input v-model="kw" type="text" placeholder="搜索会话" spellcheck="false" />
      <button v-if="kw" class="s-clear" title="清空" @click="kw = ''">✕</button>
    </div>

    <ul class="list">
      <li v-for="s in filtered" :key="s.id" class="row" :class="{ on: s.id === currentId }">
        <button class="item" :title="s.title" @click="emit('select', s.id)">
          <span class="i-title">{{ s.title }}</span>
          <span class="i-meta">
            <span class="num">{{ s.messageCount }}</span> 条
            <i>·</i>
            {{ rel(s.updatedAt) }}
          </span>
        </button>
        <button class="del" title="删除会话" @click.stop="emit('delete', s.id)">
          <span v-html="TRASH_ICON" />
        </button>
      </li>
      <li v-if="!filtered.length" class="none">
        {{ kw ? '没有匹配的会话' : '还没有会话，发一条消息开始' }}
      </li>
    </ul>
  </aside>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import type { SessionMeta } from '../../utils/session'

const props = defineProps<{ sessions: SessionMeta[]; currentId: string | null }>()
const emit = defineEmits<{
  new: []
  select: [id: string]
  delete: [id: string]
}>()

const STROKE =
  'fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"'
const PLUS_ICON = `<svg viewBox="0 0 24 24" ${STROKE}><path d="M12 5.5v13M5.5 12h13"/></svg>`
const SEARCH_ICON = `<svg viewBox="0 0 24 24" ${STROKE}><circle cx="11" cy="11" r="6"/><path d="M15.5 15.5 20 20"/></svg>`
const TRASH_ICON = `<svg viewBox="0 0 24 24" ${STROKE}><path d="M5 7h14M9.5 7V5.4A1.4 1.4 0 0 1 10.9 4h2.2a1.4 1.4 0 0 1 1.4 1.4V7"/><path d="M6.6 7l.8 11.2A1.9 1.9 0 0 0 9.3 20h5.4a1.9 1.9 0 0 0 1.9-1.8L17.4 7"/></svg>`

const kw = ref('')

// 最近更新的排前面（localStorage 里是插入序，这里按时间重排）
const sorted = computed(() => [...props.sessions].sort((a, b) => b.updatedAt - a.updatedAt))

const filtered = computed(() => {
  const k = kw.value.trim().toLowerCase()
  if (!k) return sorted.value
  return sorted.value.filter((s) => s.title.toLowerCase().includes(k))
})

function rel(ts: number): string {
  if (!ts) return '—'
  const diff = Date.now() - ts
  const min = Math.floor(diff / 60000)
  if (min < 1) return '刚刚'
  if (min < 60) return `${min} 分钟前`
  const h = Math.floor(min / 60)
  if (h < 24) return `${h} 小时前`
  const d = Math.floor(h / 24)
  if (d < 30) return `${d} 天前`
  return new Date(ts).toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit' })
}
</script>

<style scoped>
.side {
  width: var(--sidebar-w);
  flex: none;
  height: 100vh;
  display: flex;
  flex-direction: column;
  gap: var(--sp-3);
  padding: var(--sp-4) var(--sp-3);
  background: color-mix(in srgb, var(--surface-1) 72%, transparent);
  backdrop-filter: blur(16px);
  border-right: 1px solid var(--line);
}

.head {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
  padding: 0 var(--sp-2) 0 var(--sp-2);
}
.title {
  font-size: var(--fs-md);
  font-weight: var(--fw-semi);
  color: var(--ink);
  letter-spacing: -0.01em;
}
.add {
  margin-left: auto;
  width: 30px;
  height: 30px;
  display: grid;
  place-items: center;
  border-radius: var(--r-sm);
  color: var(--ink-2);
  background: var(--surface-3);
  border: 1px solid var(--line-2);
  box-shadow: var(--hairline-top);
  transition: color var(--t-fast) var(--ease-out), background var(--t-fast) var(--ease-out),
    border-color var(--t-fast) var(--ease-out);
}
.add:hover {
  color: #06121f;
  background: var(--grad-accent);
  border-color: transparent;
}
.add :deep(svg) {
  width: 15px;
  height: 15px;
}

.search {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 0 10px;
  height: 34px;
  border-radius: var(--r-md);
  background: var(--surface-2);
  border: 1px solid var(--line);
  transition: border-color var(--t-base) var(--ease-out);
}
.search:focus-within {
  border-color: color-mix(in srgb, var(--accent) 55%, transparent);
  box-shadow: 0 0 0 3px rgba(61, 139, 255, 0.12);
}
.s-ico {
  width: 14px;
  height: 14px;
  color: var(--ink-4);
  flex: none;
  display: inline-flex;
}
.s-ico :deep(svg) {
  width: 100%;
  height: 100%;
}
.search input {
  flex: 1;
  min-width: 0;
  border: none;
  outline: none;
  background: none;
  font-size: var(--fs-sm);
  color: var(--ink);
}
.search input::placeholder {
  color: var(--ink-4);
}
.s-clear {
  font-size: 11px;
  color: var(--ink-4);
}
.s-clear:hover {
  color: var(--ink-2);
}

.list {
  flex: 1;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding-right: 2px;
}

.row {
  position: relative;
  border-radius: var(--r-md);
  transition: background var(--t-fast) var(--ease-out);
}
.row:hover {
  background: var(--surface-3);
}
.row.on {
  background: var(--grad-accent-soft);
  box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--accent) 32%, transparent);
}
/* 当前会话左侧发光条 */
.row.on::before {
  content: '';
  position: absolute;
  left: 0;
  top: 50%;
  transform: translateY(-50%);
  width: 2px;
  height: 20px;
  border-radius: var(--r-full);
  background: var(--grad-accent);
  box-shadow: 0 0 10px rgba(61, 139, 255, 0.7);
}

.item {
  display: flex;
  flex-direction: column;
  gap: 3px;
  width: 100%;
  text-align: left;
  padding: 10px 34px 10px 12px;
}
.i-title {
  font-size: var(--fs-sm);
  color: var(--ink-2);
  font-weight: var(--fw-medium);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.row.on .i-title {
  color: var(--ink);
  font-weight: var(--fw-semi);
}
.i-meta {
  font-size: 11px;
  color: var(--ink-4);
  display: flex;
  align-items: center;
  gap: 4px;
}
.i-meta i {
  font-style: normal;
  opacity: 0.6;
}

.del {
  position: absolute;
  right: 7px;
  top: 50%;
  transform: translateY(-50%);
  width: 24px;
  height: 24px;
  display: grid;
  place-items: center;
  border-radius: var(--r-xs);
  color: var(--ink-4);
  opacity: 0;
  transition: opacity var(--t-fast) var(--ease-out), color var(--t-fast) var(--ease-out),
    background var(--t-fast) var(--ease-out);
}
.row:hover .del {
  opacity: 1;
}
.del:hover {
  color: var(--danger);
  background: rgba(255, 95, 86, 0.12);
}
.del :deep(svg) {
  width: 14px;
  height: 14px;
}

.none {
  font-size: var(--fs-xs);
  color: var(--ink-4);
  text-align: center;
  padding: 22px 10px;
  line-height: var(--lh-normal);
}
</style>
