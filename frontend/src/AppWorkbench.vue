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

      <button class="rail-foot" title="外观设置" @click="showSettings = true">
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
      :theme="theme"
      @close="showSettings = false"
      @setWallpaper="applyWallpaper"
      @setTheme="applyTheme"
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
import { loadWallpaper, loadTheme, saveTheme, saveWallpaper, resolveWallpaperBackground, themeOfWallpaper, applyThemeToDocument, type ThemeMode } from './utils/wallpaper'

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

// 界面明暗：显式保存过就听保存值，否则跟随壁纸自带倾向（首次进入 / 换壁纸）
const theme = ref<ThemeMode>(loadTheme() ?? themeOfWallpaper(wallpaper.value))
applyThemeToDocument(theme.value)

function applyTheme(t: ThemeMode) {
  theme.value = t
  saveTheme(t)
  applyThemeToDocument(t)
}

function applyWallpaper(stored: string | null) {
  wallpaper.value = stored
  saveWallpaper(stored)
  // 浅色壁纸必须配浅色令牌，否则白底上叠深色面板会「脏」；选壁纸即自动切明暗
  applyTheme(themeOfWallpaper(stored))
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
  opacity: var(--ambient-opacity);
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
  background-image: linear-gradient(var(--grid-ink) 1px, transparent 1px),
    linear-gradient(90deg, var(--grid-ink) 1px, transparent 1px);
  background-size: 38px 38px;
  mask-image: radial-gradient(ellipse 80% 70% at 50% 30%, #000 30%, transparent 100%);
  -webkit-mask-image: radial-gradient(ellipse 80% 70% at 50% 30%, #000 30%, transparent 100%);
}

/* ---------- 侧边导航：四个模块入口做成有分量的卡片 ---------- */
.rail {
  position: relative;
  z-index: var(--z-sticky);
  width: var(--rail-w);
  flex: none;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--sp-3);
  padding: var(--sp-4) var(--sp-3) var(--sp-3);
  background: var(--glass);
  backdrop-filter: blur(20px) saturate(150%);
  -webkit-backdrop-filter: blur(20px) saturate(150%);
  border-right: 1px solid var(--line);
}

.brand {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  padding: 2px 0 16px;
  width: 100%;
  border-bottom: 1px solid var(--line);
}
.brand-mark {
  width: 46px;
  height: 46px;
  display: grid;
  place-items: center;
  border-radius: var(--r-lg);
  background: linear-gradient(160deg, rgba(61, 139, 255, 0.2), rgba(42, 212, 200, 0.08));
  border: 1px solid var(--line-2);
  box-shadow: var(--hairline-top), 0 10px 24px -14px rgba(61, 139, 255, 0.8);
}
.brand-mark :deep(svg) {
  width: 27px;
  height: 27px;
}
.brand-name {
  font-size: var(--fs-2xs);
  font-weight: var(--fw-semi);
  letter-spacing: 0.2em;
  text-indent: 0.2em;
  color: var(--ink-3);
}

/* 四个入口均分导轨主体高度（space-evenly），整根导轨都被占满，不再是挤在中间的一小簇 */
.nav {
  flex: 1;
  min-height: 0;
  width: 100%;
  display: flex;
  flex-direction: column;
  justify-content: space-evenly;
  gap: 8px;
}

.nav-btn {
  position: relative;
  width: 100%;
  flex: 0 1 auto;
  height: 108px;
  min-height: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  padding: 12px 6px;
  border-radius: var(--r-lg);
  color: var(--ink-3);
  border: 1px solid transparent;
  transition: color var(--t-base) var(--ease-out),
    background var(--t-base) var(--ease-out), border-color var(--t-base) var(--ease-out),
    box-shadow var(--t-base) var(--ease-out), transform var(--t-base) var(--ease-out);
}
/* 悬停先预告模块色，让「这块属于哪个模块」在点之前就有反馈 */
.nav-btn:hover {
  color: var(--mod);
  background: color-mix(in srgb, var(--mod) 10%, var(--surface-3));
  border-color: color-mix(in srgb, var(--mod) 26%, transparent);
  transform: translateY(-1px);
}
.nav-btn:active {
  transform: translateY(0) scale(0.985);
}

/* 激活态：整卡模块色渐变 + 图标底座实心 + 外发光，「我在哪」一眼可见 */
.nav-btn.active {
  color: var(--mod);
  background: linear-gradient(
    180deg,
    color-mix(in srgb, var(--mod) 22%, transparent),
    color-mix(in srgb, var(--mod) 7%, transparent)
  );
  border-color: color-mix(in srgb, var(--mod) 36%, transparent);
  box-shadow: var(--hairline-top),
    0 12px 28px -16px color-mix(in srgb, var(--mod) 80%, transparent);
}
.nav-btn.active:hover {
  background: linear-gradient(
    180deg,
    color-mix(in srgb, var(--mod) 27%, transparent),
    color-mix(in srgb, var(--mod) 10%, transparent)
  );
}
/* 左缘指示条：贴着导轨左边框 */
.nav-btn.active::before {
  content: '';
  position: absolute;
  left: calc(var(--sp-3) * -1);
  top: 50%;
  transform: translateY(-50%);
  width: 3px;
  height: 40px;
  border-radius: var(--r-full);
  background: var(--mod);
  box-shadow: 0 0 16px color-mix(in srgb, var(--mod) 85%, transparent);
}

/* 图标底座：四个入口共用同一视觉锚点；激活时被模块色实心填充。
   填充色向深色压一档（而不是直接用亮色），保证白色图标在其上可读。 */
.nav-ico {
  width: 48px;
  height: 48px;
  flex: none;
  display: grid;
  place-items: center;
  border-radius: var(--r-md);
  background: color-mix(in srgb, var(--surface-3) 72%, transparent);
  border: 1px solid var(--line);
  box-shadow: var(--hairline-top);
  transition: background var(--t-base) var(--ease-out),
    border-color var(--t-base) var(--ease-out), box-shadow var(--t-base) var(--ease-out),
    color var(--t-base) var(--ease-out);
}
.nav-ico :deep(svg) {
  width: 26px;
  height: 26px;
}
.nav-btn:hover .nav-ico {
  color: var(--mod);
  background: color-mix(in srgb, var(--mod) 13%, var(--surface-4));
  border-color: color-mix(in srgb, var(--mod) 32%, transparent);
}
.nav-btn.active .nav-ico {
  color: #fff;
  background: linear-gradient(
    160deg,
    color-mix(in srgb, var(--mod) 72%, #0b1220 28%),
    color-mix(in srgb, var(--mod) 48%, #0b1220 52%)
  );
  border-color: color-mix(in srgb, var(--mod) 62%, transparent);
  box-shadow: 0 8px 20px -9px color-mix(in srgb, var(--mod) 90%, transparent),
    inset 0 1px 0 rgba(255, 255, 255, 0.32);
}

.nav-txt {
  font-size: var(--fs-sm);
  font-weight: var(--fw-medium);
  letter-spacing: 0.02em;
}
.nav-btn.active .nav-txt {
  font-weight: var(--fw-semi);
}

/* 导轨底部：外观设置（与上方入口同一套零件，但不参与平分高度） */
.rail-foot {
  flex: none;
  width: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 14px 6px 4px;
  border-radius: var(--r-md);
  color: var(--ink-3);
  border-top: 1px solid var(--line);
  transition: color var(--t-base) var(--ease-out), background var(--t-base) var(--ease-out);
}
.rail-foot:hover {
  color: var(--ink);
  background: var(--surface-3);
}
.rail-foot:hover .nav-ico {
  background: var(--surface-4);
  border-color: var(--line-3);
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
