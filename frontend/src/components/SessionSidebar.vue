<template>
  <!-- 折叠状态：窄竖条，点击展开 -->
  <div v-if="collapsed" class="sidebar-collapsed" @click="collapsed = false" title="展开会话列表">
    <span class="fold-icon">☰</span>
    <span class="fold-label">会话</span>
  </div>

  <!-- 展开状态：完整侧栏 -->
  <aside v-else class="sidebar">
    <div class="sidebar-head">
      <button class="new-btn" @click="emit('new')">＋ 新会话</button>
      <button class="fold-btn" title="收起" @click="collapsed = true">◀</button>
    </div>
    <div class="list">
      <div
        v-for="s in sessions"
        :key="s.id"
        class="item"
        :class="{ active: s.id === currentId }"
        @click="emit('select', s.id)"
      >
        <div class="item-body">
          <div class="item-title">{{ s.title }}</div>
          <div class="item-meta">{{ s.messageCount }} 条消息</div>
        </div>
        <button class="del" title="删除会话" @click.stop="emit('delete', s.id)">🗑</button>
      </div>
      <div v-if="!sessions.length" class="list-empty">暂无会话，点「新会话」开始</div>
    </div>
    <div class="sidebar-foot">
      <span class="foot-hint">本地保存 · 不上传</span>
    </div>
  </aside>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import type { SessionMeta } from '../utils/session'

const COLLAPSE_KEY = 'sport-session-sidebar-collapsed'
function loadCollapsed(): boolean {
  try {
    return localStorage.getItem(COLLAPSE_KEY) === '1'
  } catch {
    return false
  }
}

defineProps<{
  sessions: SessionMeta[]
  currentId: string | null
}>()
const emit = defineEmits<{
  (e: 'new'): void
  (e: 'select', id: string): void
  (e: 'delete', id: string): void
}>()

const collapsed = ref(loadCollapsed())
function toggle(c: boolean) {
  collapsed.value = c
  try {
    localStorage.setItem(COLLAPSE_KEY, c ? '1' : '0')
  } catch {
    /* ignore */
  }
}
</script>

<style scoped>
.sidebar-collapsed {
  width: 40px;
  flex: none;
  height: 100vh;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  padding-top: 16px;
  cursor: pointer;
  background: color-mix(in srgb, var(--bg-soft) 82%, transparent);
  backdrop-filter: blur(14px);
  border-right: 1px solid var(--border);
  color: var(--muted);
  transition: color 0.12s, background 0.12s;
}
.sidebar-collapsed:hover {
  color: var(--accent);
  background: var(--card-hover);
}
.fold-icon {
  font-size: 18px;
}
.fold-label {
  font-size: 12px;
  writing-mode: vertical-rl;
}
.sidebar {
  width: 260px;
  flex: none;
  height: 100vh;
  display: flex;
  flex-direction: column;
  background: color-mix(in srgb, var(--bg-soft) 82%, transparent);
  backdrop-filter: blur(14px);
  border-right: 1px solid var(--border);
}
.sidebar-head {
  padding: 14px 12px 10px;
  display: flex;
  align-items: center;
  gap: 6px;
}
.new-btn {
  flex: 1;
  padding: 11px 0;
  border: none;
  border-radius: 10px;
  background: var(--accent);
  color: #fff;
  font-size: 15px;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.12s, transform 0.06s;
}
.new-btn:hover {
  background: var(--accent-hover);
}
.new-btn:active {
  transform: scale(0.98);
}
.fold-btn {
  flex: none;
  width: 30px;
  height: 30px;
  border: none;
  border-radius: 8px;
  background: transparent;
  color: var(--muted);
  font-size: 12px;
  cursor: pointer;
  transition: background 0.12s, color 0.12s;
}
.fold-btn:hover {
  background: var(--card-hover);
  color: var(--text);
}
.list {
  flex: 1;
  overflow-y: auto;
  padding: 4px 8px 8px;
  display: flex;
  flex-direction: column;
  gap: 2px;
  scrollbar-width: thin;
  scrollbar-color: var(--border) transparent;
}
.item {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 11px 10px;
  border-radius: 10px;
  cursor: pointer;
  border: 1px solid transparent;
  transition: background 0.12s, border-color 0.12s;
}
.item:hover {
  background: var(--card-hover);
}
.item.active {
  background: var(--accent-soft);
  border-color: color-mix(in srgb, var(--accent) 45%, transparent);
}
.item-body {
  flex: 1;
  min-width: 0;
}
.item-title {
  font-size: 15px;
  font-weight: 500;
  color: var(--text-soft);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.item.active .item-title {
  color: var(--text);
}
.item-meta {
  font-size: 13px;
  color: var(--faint);
  margin-top: 3px;
}
.del {
  flex: none;
  border: none;
  background: transparent;
  color: var(--faint);
  font-size: 12px;
  cursor: pointer;
  padding: 4px 5px;
  border-radius: 6px;
  opacity: 0;
  transition: opacity 0.12s, background 0.12s;
}
.item:hover .del {
  opacity: 1;
}
.del:hover {
  background: var(--danger-soft);
}
.list-empty {
  padding: 20px 10px;
  font-size: 12px;
  color: var(--faint);
  text-align: center;
}
.sidebar-foot {
  padding: 10px 12px;
  border-top: 1px solid var(--border-soft);
}
.foot-hint {
  font-size: 11px;
  color: var(--faint);
}
</style>
