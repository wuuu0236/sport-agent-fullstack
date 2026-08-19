<template>
  <div v-if="sessions.length" class="sessions">
    <div class="board-title">最近训练</div>
    <div v-for="s in sessions" :key="s.date + s.summary" class="sess">
      <span class="sess-date">{{ s.date }}</span>
      <span class="sess-sum">{{ s.summary }}</span>
    </div>
  </div>
</template>

<script setup lang="ts">
defineProps<{ sessions: any[] }>()
</script>

<style scoped>
.sessions {
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 12px;
  margin: 12px 0;
  background: color-mix(in srgb, var(--card) 85%, transparent);
}
.board-title {
  font-size: 13px;
  font-weight: 600;
  margin-bottom: 8px;
  color: var(--accent);
}
.sess {
  display: flex;
  gap: 10px;
  font-size: 13px;
  padding: 5px 0;
  border-bottom: 1px dashed var(--border-soft);
}
.sess:last-child {
  border-bottom: none;
}
.sess-date {
  color: var(--accent);
  font-weight: 600;
  white-space: nowrap;
}
.sess-sum {
  color: var(--text-soft);
}
</style>
