<template>
  <!-- 折叠状态：窄竖条，点击展开 -->
  <div v-if="collapsed" class="profile-collapsed" @click="collapsed = false" title="展开用户画像">
    <span class="fold-icon">👤</span>
    <span class="fold-label">画像</span>
  </div>

  <!-- 展开状态：完整侧栏 -->
  <aside v-else class="profile">
    <div class="profile-head">
      <div class="profile-titles">
        <div class="profile-title">👤 用户画像</div>
        <div class="profile-sub">关于你的长期记忆 · 助手记得的</div>
      </div>
      <button class="fold-btn" title="收起" @click="collapsed = true">▶</button>
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
import { ref } from 'vue'

const COLLAPSE_KEY = 'sport-profile-sidebar-collapsed'
function loadCollapsed(): boolean {
  try {
    return localStorage.getItem(COLLAPSE_KEY) === '1'
  } catch {
    return false
  }
}

defineProps<{ entries: string[] }>()

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
.profile-collapsed {
  width: 40px;
  flex: none;
  height: 100vh;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  padding-top: 16px;
  cursor: pointer;
  background: color-mix(in srgb, var(--bg-soft) 80%, transparent);
  backdrop-filter: blur(14px);
  color: var(--muted);
  transition: color 0.12s, background 0.12s;
}
.profile-collapsed:hover {
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
.profile {
  width: 260px;
  flex: none;
  height: 100vh;
  display: flex;
  flex-direction: column;
  background: color-mix(in srgb, var(--bg-soft) 80%, transparent);
  backdrop-filter: blur(14px);
  overflow-y: auto;
  scrollbar-width: thin;
  scrollbar-color: var(--border) transparent;
}
.profile-head {
  padding: 14px 14px 10px;
  border-bottom: 1px solid var(--border-soft);
  display: flex;
  align-items: flex-start;
  gap: 6px;
}
.profile-titles {
  flex: 1;
  min-width: 0;
}
.profile-title {
  font-size: 16px;
  font-weight: 600;
}
.profile-sub {
  font-size: 12px;
  color: var(--faint);
  margin-top: 3px;
}
.fold-btn {
  flex: none;
  width: 28px;
  height: 28px;
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
  font-size: 14px;
  line-height: 1.6;
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
  font-size: 40px;
  opacity: 0.8;
}
.empty-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--text-soft);
}
.empty-hint {
  font-size: 13px;
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
