<template>
  <div class="workbench" :style="{ ...wallpaperStyle, '--mod': currentHue }">
    <!-- 氛围层：模块专属色晕 + 极淡网格（有壁纸时隐藏，避免叠加浑浊） -->
    <div v-if="!wallpaper" class="ambient" aria-hidden="true">
      <span class="blob b1" />
      <span class="blob b2" />
      <span class="grid-lines" />
    </div>

    <!-- 左侧极窄导航 -->
    <nav class="rail">
      <div class="brand" title="战狼养成计划">
        <span class="brand-mark" v-html="ICONS.brand" />
        <span class="brand-name">战狼</span>
      </div>

      <div class="nav">
        <button
          v-for="m in MODULES"
          :key="m.id"
          class="nav-btn"
          :class="{ active: current === m.id }"
          :style="{ '--mod': m.hue }"
          @click="current = m.id"
        >
          <span class="nav-ico" v-html="m.iconSvg" />
          <span class="nav-txt">{{ m.name }}</span>
        </button>
      </div>

      <button class="nav-btn ghost" title="外观设置" @click="showSettings = true">
        <span class="nav-ico" v-html="ICONS.palette" />
        <span class="nav-txt">外观</span>
      </button>
    </nav>

    <!-- 主工作区：视图切换带淡入上浮过渡，KeepAlive 保留各模块状态 -->
    <main class="stage">
      <Transition name="view" mode="out-in">
        <KeepAlive>
          <component :is="currentView" :key="current" />
        </KeepAlive>
      </Transition>
    </main>

    <ThemeSettings
      :open="showSettings"
      :wallpaper="wallpaper"
      @close="showSettings = false"
      @setWallpaper="applyWallpaper"
    />
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import ChatView from './views/Chat.vue'
import DashboardView from './views/DashboardView.vue'
import MemoryView from './views/MemoryView.vue'
import PlanView from './views/PlanView.vue'
import ThemeSettings from './components/ThemeSettings.vue'
import { loadWallpaper, saveWallpaper, resolveWallpaperBackground } from './utils/wallpaper'

const STROKE =
  'fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"'

const ICONS = {
  brand: `<svg viewBox="0 0 24 24" fill="none"><path d="M13.4 2.2 4.6 13.4h4.9l-1.6 8.4 9.3-11.6h-5z" fill="url(#brandGrad)"/><defs><linearGradient id="brandGrad" x1="4" y1="2" x2="18" y2="22" gradientUnits="userSpaceOnUse"><stop stop-color="#7CC0FF"/><stop offset="1" stop-color="#2AD4C8"/></linearGradient></defs></svg>`,
  chat:
    `<svg viewBox="0 0 24 24" ${STROKE}><path d="M4 6a2 2 0 0 1 2-2h12a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2h-6.6l-4 3.1a.5.5 0 0 1-.8-.4V16H6a2 2 0 0 1-2-2z"/><path d="M8.4 8.7h7.2M8.4 11.6h4.4"/></svg>`,
  activity:
    `<svg viewBox="0 0 24 24" ${STROKE}><path d="M3 12.5h3.6l2.2-6.3 3.6 12.2 2.4-7.1 1.6 3.6H21"/></svg>`,
  calendar:
    `<svg viewBox="0 0 24 24" ${STROKE}><rect x="3.4" y="5" width="17.2" height="15.6" rx="2.6"/><path d="M3.4 10h17.2M8.2 3.4v3.2M15.8 3.4v3.2M8.6 14.2h2.1v2.1H8.6zM13.3 14.2h2.1v2.1h-2.1z"/></svg>`,
  sparkles:
    `<svg viewBox="0 0 24 24" ${STROKE}><path d="M11.6 3.2 13.2 8l4.8 1.6L13.2 11.2 11.6 16 10 11.2 5.2 9.6 10 8z"/><path d="M18.4 14.6l.7 2.1 2.1.7-2.1.7-.7 2.1-.7-2.1-2.1-.7 2.1-.7z"/></svg>`,
  palette:
    `<svg viewBox="0 0 24 24" ${STROKE}><path d="M12 20.5a8.5 8.5 0 1 1 8.5-8.5c0 2.2-1.7 3.2-3.4 3.2h-1.4a1.9 1.9 0 0 0-1.4 3.2 1.6 1.6 0 0 1-1.2 2.1z"/><circle cx="8.4" cy="10.6" r="1.1" fill="currentColor" stroke="none"/><circle cx="12" cy="7.9" r="1.1" fill="currentColor" stroke="none"/><circle cx="15.6" cy="10.2" r="1.1" fill="currentColor" stroke="none"/></svg>`,
}

// 模块注册表：每项带专属色相 --mod，驱动导航高亮与氛围光
const MODULES = [
  { id: 'chat', name: '对话', iconSvg: ICONS.chat, view: ChatView, hue: '#3d8bff' },
  { id: 'dashboard', name: '数据', iconSvg: ICONS.activity, view: DashboardView, hue: '#2ad4c8' },
  { id: 'plan', name: '计划', iconSvg: ICONS.calendar, view: PlanView, hue: '#8b7bff' },
  { id: 'memory', name: '记忆', iconSvg: ICONS.sparkles, view: MemoryView, hue: '#f0b23c' },
]

const current = ref<string>('chat')
const currentHue = computed(() => MODULES.find((m) => m.id === current.value)?.hue ?? '#3d8bff')
const currentView = computed(() => MODULES.find((m) => m.id === current.value)?.view ?? ChatView)

// ---- 模块深链：URL hash 与当前模块双向同步（刷新/分享链接停在原模块） ----
const VALID = new Set(MODULES.map((m) => m.id))
function fromHash(): string {
  const h = (location.hash || '').replace(/^#\/?/, '')
  return VALID.has(h) ? h : 'chat'
}
current.value = fromHash()
function onHashChange() {
  const h = fromHash()
  if (h !== current.value) current.value = h
}
watch(current, (v) => {
  if (location.hash.replace(/^#\/?/, '') !== v) location.hash = '/' + v
})
onMounted(() => window.addEventListener('hashchange', onHashChange))
onBeforeUnmount(() => window.removeEventListener('hashchange', onHashChange))

// 壁纸：铺满整个工作台；未设置时显示默认氛围层
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
  position: relative;
  display: flex;
  height: 100vh;
  overflow: hidden;
  background-color: var(--surface-0);
  background-size: cover;
  background-position: center;
}

/* ---------- 氛围层：两团柔光 + 细网格 ---------- */
.ambient {
  position: absolute;
  inset: 0;
  overflow: hidden;
  pointer-events: none;
  z-index: 0;
}
.blob {
  position: absolute;
  border-radius: 50%;
  filter: blur(90px);
  opacity: 0.5;
  transition: background var(--t-slow) var(--ease-out);
}
.b1 {
  width: 46vw;
  height: 46vw;
  top: -16vw;
  left: 6vw;
  background: radial-gradient(circle, color-mix(in srgb, var(--mod) 30%, transparent), transparent 68%);
}
.b2 {
  width: 38vw;
  height: 38vw;
  right: -10vw;
  bottom: -14vw;
  background: radial-gradient(circle, rgba(42, 212, 200, 0.16), transparent 70%);
}
.grid-lines {
  position: absolute;
  inset: 0;
  background-image: linear-gradient(rgba(255, 255, 255, 0.022) 1px, transparent 1px),
    linear-gradient(90deg, rgba(255, 255, 255, 0.022) 1px, transparent 1px);
  background-size: 38px 38px;
  mask-image: radial-gradient(ellipse 80% 70% at 50% 30%, #000 30%, transparent 100%);
  -webkit-mask-image: radial-gradient(ellipse 80% 70% at 50% 30%, #000 30%, transparent 100%);
}

/* ---------- 侧边导航 ---------- */
.rail {
  position: relative;
  z-index: var(--z-sticky);
  width: var(--rail-w);
  flex: none;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--sp-3);
  padding: var(--sp-4) var(--sp-3);
  background: var(--glass);
  backdrop-filter: blur(20px) saturate(150%);
  -webkit-backdrop-filter: blur(20px) saturate(150%);
  border-right: 1px solid var(--line);
}

.brand {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 5px;
  padding: 4px 0 14px;
  width: 100%;
  border-bottom: 1px solid var(--line);
  margin-bottom: 4px;
}
.brand-mark {
  width: 34px;
  height: 34px;
  display: grid;
  place-items: center;
  border-radius: var(--r-md);
  background: rgba(61, 139, 255, 0.1);
  border: 1px solid var(--line-2);
  box-shadow: var(--hairline-top);
}
.brand-mark :deep(svg) {
  width: 21px;
  height: 21px;
}
.brand-name {
  font-size: 11px;
  font-weight: var(--fw-semi);
  letter-spacing: 0.14em;
  color: var(--ink-3);
}

.nav {
  flex: 1;
  width: 100%;
  display: flex;
  flex-direction: column;
  justify-content: center;
  gap: var(--sp-2);
}

.nav-btn {
  position: relative;
  width: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  padding: 13px 4px 11px;
  border-radius: var(--r-md);
  color: var(--ink-3);
  border: 1px solid transparent;
  transition: color var(--t-base) var(--ease-out),
    background var(--t-base) var(--ease-out), border-color var(--t-base) var(--ease-out);
}
.nav-btn:hover {
  color: var(--ink);
  background: var(--surface-3);
}
/* 激活态：模块色淡染底 + 左侧发光条 */
.nav-btn.active {
  color: var(--mod);
  background: color-mix(in srgb, var(--mod) 13%, transparent);
  border-color: color-mix(in srgb, var(--mod) 30%, transparent);
  box-shadow: var(--hairline-top);
}
.nav-btn.active::before {
  content: '';
  position: absolute;
  left: -13px;
  top: 50%;
  transform: translateY(-50%);
  width: 3px;
  height: 22px;
  border-radius: var(--r-full);
  background: var(--mod);
  box-shadow: 0 0 12px var(--mod);
}
.nav-ico {
  width: 21px;
  height: 21px;
  display: inline-flex;
}
.nav-ico :deep(svg) {
  width: 100%;
  height: 100%;
}
.nav-txt {
  font-size: 12px;
  font-weight: var(--fw-medium);
  letter-spacing: 0.02em;
}
.nav-btn.active .nav-txt {
  font-weight: var(--fw-semi);
}
.ghost {
  flex: none;
  border-top: 1px solid var(--line);
  border-radius: 0 0 var(--r-md) var(--r-md);
  padding-top: 15px;
}

/* ---------- 主工作区 ---------- */
.stage {
  position: relative;
  z-index: var(--z-content);
  flex: 1;
  min-width: 0;
  display: flex;
}

/* 视图切换：淡入 + 轻微上浮 */
.view-enter-active {
  transition: opacity var(--t-base) var(--ease-out),
    transform var(--t-base) var(--ease-out);
}
.view-leave-active {
  transition: opacity 130ms var(--ease-out), transform 130ms var(--ease-out);
}
.view-enter-from {
  opacity: 0;
  transform: translateY(8px);
}
.view-leave-to {
  opacity: 0;
  transform: translateY(-5px);
}
</style>
