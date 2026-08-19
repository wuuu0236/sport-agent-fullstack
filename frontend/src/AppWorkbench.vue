<template>
  <div class="workbench" :style="wallpaperStyle">
    <!-- 左侧图标导航 -->
    <nav class="rail">
      <button
        v-for="m in MODULES"
        :key="m.id"
        class="rail-btn"
        :class="{ active: current === m.id }"
        :title="m.name"
        @click="current = m.id"
      >
        <span class="rail-icon" v-html="m.iconSvg"></span>
        <span class="rail-label">{{ m.name }}</span>
      </button>
      <div class="rail-spacer"></div>
      <button class="rail-btn" title="外观设置" @click="showSettings = true">
        <span class="rail-icon" v-html="SETTINGS_ICON"></span>
        <span class="rail-label">外观</span>
      </button>
    </nav>

    <!-- 主工作区：按当前模块动态渲染 -->
    <main class="stage">
      <component :is="currentView" />
    </main>

    <!-- 外观设置（暗色主题 + 自定义壁纸） -->
    <ThemeSettings
      :open="showSettings"
      :wallpaper="wallpaper"
      @close="showSettings = false"
      @setWallpaper="applyWallpaper"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import ChatView from './views/Chat.vue'
import DashboardView from './views/DashboardView.vue'
import MemoryView from './views/MemoryView.vue'
import ThemeSettings from './components/ThemeSettings.vue'
import { loadWallpaper, saveWallpaper, resolveWallpaperBackground } from './utils/wallpaper'

// 小众线性图标（自绘 SVG，stroke 随主题色）：对话 / 数据 / 记忆 / 外观
const ICON_STROKE =
  'fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"'
const ICONS = {
  chat:
    `<svg viewBox="0 0 24 24" ${ICON_STROKE}>` +
    `<path d="M4 5.5A1.5 1.5 0 0 1 5.5 4h13A1.5 1.5 0 0 1 20 5.5v9a1.5 1.5 0 0 1-1.5 1.5H11l-4.4 3.3a.55.55 0 0 1-.88-.43V16H5.5A1.5 1.5 0 0 1 4 14.5z"/>` +
    `<path d="M8.5 8.5h7M8.5 11.5h4"/></svg>`,
  dashboard:
    `<svg viewBox="0 0 24 24" ${ICON_STROKE}>` +
    `<path d="M4.5 19V9"/><path d="M9.5 19V5"/><path d="M14.5 19v-7"/><path d="M19.5 19V3"/></svg>`,
  memory:
    `<svg viewBox="0 0 24 24" ${ICON_STROKE}>` +
    `<path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z"/>` +
    `<path d="M19 15l.7 2.1 2.1.7-2.1.7L19 20.6l-.7-2.1-2.1-.7 2.1-.7z"/></svg>`,
  settings:
    `<svg viewBox="0 0 24 24" ${ICON_STROKE}>` +
    `<path d="M12 3a6.5 6.5 0 0 0 9 9 7.5 7.5 0 1 1-9-9z"/>` +
    `<path d="M19 3v4M17 5h4"/></svg>`,
}
const SETTINGS_ICON = ICONS.settings

// 工作台模块注册表：新增模块只需在这里加一项
const MODULES = [
  { id: 'chat', name: '对话', iconSvg: ICONS.chat, view: ChatView },
  { id: 'dashboard', name: '训练数据', iconSvg: ICONS.dashboard, view: DashboardView },
  { id: 'memory', name: '记忆', iconSvg: ICONS.memory, view: MemoryView },
]

const current = ref<string>('chat')
const currentView = computed(() => MODULES.find((m) => m.id === current.value)?.view ?? ChatView)

// 壁纸铺满整个工作台
const wallpaper = ref<string | null>(loadWallpaper())
const wallpaperStyle = computed(() => resolveWallpaperBackground(wallpaper.value))
const showSettings = ref(false)
function applyWallpaper(stored: string | null) {
  wallpaper.value = stored
  saveWallpaper(stored)
}
</script>

<style scoped>
.workbench {
  display: flex;
  min-height: 100vh;
  background-color: var(--bg);
  background-size: cover;
  background-position: center;
  background-attachment: fixed;
  transition: background 0.2s;
}
.rail {
  width: 72px;
  flex: none;
  height: 100vh;
  position: sticky;
  top: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  padding: 14px 0;
  background: color-mix(in srgb, var(--bg-soft) 80%, transparent);
  backdrop-filter: blur(14px);
  border-right: 1px solid var(--border);
  z-index: 10;
}
.rail-btn {
  width: 56px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  padding: 9px 0;
  border: none;
  border-radius: 12px;
  background: transparent;
  color: var(--muted);
  cursor: pointer;
  transition: background 0.12s, color 0.12s;
}
.rail-btn:hover {
  background: var(--card-hover);
  color: var(--text);
}
.rail-btn.active {
  background: var(--accent-soft);
  color: var(--accent);
}
.rail-icon {
  width: 24px;
  height: 24px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}
.rail-icon :deep(svg) {
  width: 24px;
  height: 24px;
}
.rail-label {
  font-size: 11px;
}
.rail-spacer {
  flex: 1;
}
.stage {
  flex: 1;
  min-width: 0;
  display: flex;
}
</style>
