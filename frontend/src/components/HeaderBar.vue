<template>
  <header>
    <span class="title">个人体育训练助理</span>
    <div class="right">
      <span class="conn" :class="conn">
        <i class="dot"></i>{{ connText }}
      </span>
      <button class="settings-btn" title="外观设置" @click="emit('openSettings')">🎨</button>
    </div>
  </header>
</template>

<script setup lang="ts">
defineProps<{
  conn: 'checking' | 'ok' | 'err'
  connText: string
}>()
const emit = defineEmits<{ (e: 'openSettings'): void }>()
</script>

<style scoped>
header {
  font-weight: 600;
  font-size: 18px;
  padding-bottom: 12px;
  border-bottom: 1px solid var(--border);
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.right {
  display: flex;
  align-items: center;
  gap: 10px;
}
.conn {
  font-size: 12px;
  font-weight: 400;
  display: flex;
  align-items: center;
  gap: 5px;
}
.conn .dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  display: inline-block;
  background: var(--faint);
}
.conn.ok .dot {
  background: var(--ok);
}
.conn.err .dot {
  background: var(--danger);
}
.conn.ok {
  color: var(--ok);
}
.conn.err {
  color: var(--danger);
}
.settings-btn {
  background: transparent;
  border: 1px solid var(--border);
  border-radius: 8px;
  width: 32px;
  height: 32px;
  font-size: 15px;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  transition: background 0.12s;
}
.settings-btn:hover {
  background: var(--card-hover);
}
</style>
