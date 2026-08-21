<template>
  <div class="workbench" :style="wallpaperStyle">
    <!-- 左侧图标导航 -->
    <nav class="rail">
      <div class="rail-modules">
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
      </div>
      <button class="rail-btn rail-settings" title="外观设置" @click="showSettings = true">
        <span class="rail-icon" v-html="SETTINGS_ICON"></span>
        <span class="rail-label">外观</span>
      </button>
    </nav>

    <!-- 主工作区：按当前模块动态渲染，并染上该模块专属浅灰白底色 -->
    <main class="stage" :class="'stage-' + current">
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
import PlanView from './views/PlanView.vue'
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
  plan:
    `<svg viewBox="0 0 24 24" ${ICON_STROKE}>` +
    `<path d="M5 4h14a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2z"/><path d="M16 2v4M8 2v4M4 10h16M8 14h2v2H8zM12 14h2v2h-2zM16 14h2v2h-2z"/></svg>`,
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
  { id: 'plan', name: '计划', iconSvg: ICONS.plan, view: PlanView },
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
  width: 244px;
  flex: none;
  height: 100vh;
  position: sticky;
  top: 0;
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 24px 16px;
  background: color-mix(in srgb, var(--bg-soft) 80%, transparent);
  backdrop-filter: blur(14px);
  border-right: 1px solid var(--border);
  z-index: 10;
  align-items: stretch;
}
/* 4 个主模块在侧边栏纵向居中，彼此保持较大间距 */
.rail-modules {
  flex: 1;
  display: flex;
  flex-direction: column;
  justify-content: center;
  gap: 32px;
}
.rail-settings {
  flex: none;
}
.rail-btn {
  width: 100%;
  display: flex;
  flex-direction: row;
  align-items: center;
  gap: 14px;
  padding: 20px 18px;
  border: 1px solid var(--border);
  border-radius: 18px;
  background: color-mix(in srgb, var(--bg) 72%, transparent);
  color: var(--muted);
  cursor: pointer;
  font-weight: 600;
  transition: background 0.12s, color 0.12s, border-color 0.12s, box-shadow 0.12s;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.03);
}
.rail-btn:hover {
  background: var(--card-hover);
  color: var(--text);
  border-color: color-mix(in srgb, var(--text) 35%, var(--border));
}
.rail-btn.active {
  background: var(--bg);
  color: var(--text);
  border-color: var(--text);
  box-shadow: 0 2px 6px rgba(0, 0, 0, 0.06);
}
.rail-btn.active .rail-label {
  font-weight: 700;
}
.rail-icon {
  width: 28px;
  height: 28px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex: none;
}
.rail-icon :deep(svg) {
  width: 28px;
  height: 28px;
}
.rail-label {
  font-size: 18px;
  font-weight: 600;
  letter-spacing: 0.01em;
}
.stage {
  flex: 1;
  min-width: 0;
  display: flex;
  transition: background-color 0.25s ease;
}
/* 各模块专属深黑灰底色：同属黑灰系、仅色相微差，点击切换即凸显差异 */
.stage-chat {
  background-color: #1e2230;
}
.stage-dashboard {
  background-color: #1d2622;
}
.stage-plan {
  background-color: #251f2e;
}
.stage-memory {
  background-color: #2a231a;
}
</style>
