<template>
  <aside class="profile">
    <div class="profile-head">
      <div class="profile-title">👤 用户画像</div>
      <div class="profile-sub">关于你的长期记忆 · 助手记得的</div>
    </div>

    <div v-if="entries.length" class="entries">
      <div v-for="(e, i) in entries" :key="i" class="entry">
        <span class="bullet">•</span>
        <span class="text">{{ e }}</span>
      </div>
    </div>
    <div v-else class="empty">
      <div class="empty-icon">🗒️</div>
      <div class="empty-title">还没有关于你的记忆</div>
      <div class="empty-hint">对助手说「记住我每周三晨跑」「我是跑步爱好者」等，它会写入这里的长期记忆</div>
    </div>

    <div class="profile-foot">
      <span>记忆跨会话常驻，注入所有子 Agent</span>
    </div>
  </aside>
</template>

<script setup lang="ts">
defineProps<{ entries: string[] }>()
</script>

<style scoped>
.profile {
  width: 240px;
  flex: none;
  height: 100vh;
  display: flex;
  flex-direction: column;
  background: color-mix(in srgb, var(--bg-soft) 80%, transparent);
  backdrop-filter: blur(14px);
  border-left: 1px solid var(--border);
  overflow-y: auto;
  scrollbar-width: thin;
  scrollbar-color: var(--border) transparent;
}
.profile-head {
  padding: 14px 14px 10px;
  border-bottom: 1px solid var(--border-soft);
}
.profile-title {
  font-size: 14px;
  font-weight: 600;
}
.profile-sub {
  font-size: 11px;
  color: var(--faint);
  margin-top: 3px;
}
.entries {
  flex: 1;
  padding: 12px 14px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.entry {
  display: flex;
  gap: 7px;
  font-size: 13px;
  line-height: 1.55;
  color: var(--text-soft);
  background: color-mix(in srgb, var(--card) 70%, transparent);
  border: 1px solid var(--border-soft);
  border-radius: 8px;
  padding: 8px 10px;
}
.bullet {
  color: var(--accent);
  flex: none;
}
.text {
  word-break: break-word;
}
.empty {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 20px;
  text-align: center;
  gap: 8px;
}
.empty-icon {
  font-size: 34px;
  opacity: 0.8;
}
.empty-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-soft);
}
.empty-hint {
  font-size: 12px;
  color: var(--faint);
  line-height: 1.6;
}
.profile-foot {
  padding: 10px 14px;
  border-top: 1px solid var(--border-soft);
  font-size: 11px;
  color: var(--faint);
}
</style>
