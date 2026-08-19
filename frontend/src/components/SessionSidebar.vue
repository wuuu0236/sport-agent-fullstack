<template>
  <aside class="sidebar">
    <div class="sidebar-head">
      <button class="new-btn" @click="emit('new')">＋ 新会话</button>
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
import type { SessionMeta } from '../utils/session'

defineProps<{
  sessions: SessionMeta[]
  currentId: string | null
}>()
const emit = defineEmits<{
  (e: 'new'): void
  (e: 'select', id: string): void
  (e: 'delete', id: string): void
}>()
</script>

<style scoped>
.sidebar {
  width: 240px;
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
}
.new-btn {
  width: 100%;
  padding: 10px 0;
  border: none;
  border-radius: 10px;
  background: var(--accent);
  color: #fff;
  font-size: 14px;
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
  font-size: 14px;
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
  font-size: 12px;
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
