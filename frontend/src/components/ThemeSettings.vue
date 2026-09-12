<template>
  <Transition name="overlay">
    <div v-if="open" class="overlay" @click.self="emit('close')">
      <aside class="panel" role="dialog" aria-label="外观设置">
        <header class="head">
          <div>
            <h2 class="h">外观设置</h2>
            <p class="hs">背景与氛围，仅保存在本机</p>
          </div>
          <button class="x" aria-label="关闭" @click="emit('close')">
            <span v-html="CLOSE_ICON" />
          </button>
        </header>

        <div class="body">
          <!-- 背景选择 -->
          <section class="group">
            <h3 class="gt">背景</h3>
            <div class="tiles">
              <button
                class="tile"
                :class="{ on: !wallpaper }"
                @click="setWallpaper(null)"
              >
                <span class="swatch tile-default" />
                <span class="tn">默认</span>
              </button>
              <button
                v-for="p in WALLPAPER_PRESETS"
                :key="p.id"
                class="tile"
                :class="{ on: wallpaper === presetToStored(p) }"
                @click="setWallpaper(presetToStored(p))"
              >
                <span class="swatch" :style="{ background: p.css }" />
                <span class="tn">{{ p.name }}</span>
              </button>
            </div>
          </section>

          <!-- 自定义图片 -->
          <section class="group">
            <h3 class="gt">自定义图片</h3>
            <div v-if="isCustom" class="preview">
              <img :src="previewSrc" alt="当前壁纸预览" />
              <div class="pv-side">
                <span class="pv-tag">已启用</span>
                <button class="pv-clear" @click="setWallpaper(null)">移除</button>
              </div>
            </div>
            <label class="upload">
              <span class="up-ico" v-html="UPLOAD_ICON" />
              <span class="up-txt">
                <b>选择图片</b>
                <i>自动压缩后存本地，刷新不丢</i>
              </span>
              <input type="file" accept="image/*" hidden @change="onUpload" />
            </label>
            <p v-if="err" class="err">{{ err }}</p>
          </section>

          <p class="tip">
            壁纸只写入浏览器 localStorage，不上传服务器；启用壁纸后氛围光自动隐藏，避免背景浑浊。
          </p>
        </div>
      </aside>
    </div>
  </Transition>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { WALLPAPER_PRESETS, presetToStored } from '../utils/wallpaper'
import { fileToCompressedDataUrl } from '../utils/image'

const props = defineProps<{ open: boolean; wallpaper: string | null }>()
const emit = defineEmits<{
  (e: 'close'): void
  (e: 'setWallpaper', stored: string | null): void
}>()

const STROKE =
  'fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"'
const CLOSE_ICON = `<svg viewBox="0 0 24 24" ${STROKE}><path d="M6.5 6.5l11 11M17.5 6.5l-11 11"/></svg>`
const UPLOAD_ICON =
  `<svg viewBox="0 0 24 24" ${STROKE}><path d="M12 16.5V4.6M7.8 8.8 12 4.5l4.2 4.3"/><path d="M4.5 15.4v2.6a1.9 1.9 0 0 0 1.9 1.9h11.2a1.9 1.9 0 0 0 1.9-1.9v-2.6"/></svg>`

const err = ref('')

function setWallpaper(stored: string | null) {
  err.value = ''
  emit('setWallpaper', stored)
}

// 自定义上传的壁纸是 base64 DataURL；预设是 'preset:<id>'
const isCustom = computed(() => !!props.wallpaper && !props.wallpaper.startsWith('preset:'))
const previewSrc = computed(() => (isCustom.value ? (props.wallpaper as string) : ''))

async function onUpload(e: Event) {
  const f = (e.target as HTMLInputElement).files?.[0]
  ;(e.target as HTMLInputElement).value = ''
  if (!f) return
  if (!f.type.startsWith('image/')) {
    err.value = '请选择图片文件'
    return
  }
  try {
    // 原图动辄数 MB，localStorage 仅约 5MB：先压缩再存
    const dataUrl = await fileToCompressedDataUrl(f)
    err.value = ''
    emit('setWallpaper', dataUrl)
  } catch (e2) {
    err.value = '图片处理失败：' + String(e2)
  }
}
</script>

<style scoped>
.overlay {
  position: fixed;
  inset: 0;
  z-index: var(--z-modal);
  display: flex;
  justify-content: flex-end;
  background: rgba(6, 9, 13, 0.5);
  backdrop-filter: blur(3px);
}

/* 右侧抽屉 */
.panel {
  width: 380px;
  max-width: 92vw;
  height: 100%;
  display: flex;
  flex-direction: column;
  background: var(--surface-1);
  border-left: 1px solid var(--line-2);
  box-shadow: var(--shadow-3);
  animation: slide-in var(--t-slow) var(--ease-out) both;
}
@keyframes slide-in {
  from {
    opacity: 0.4;
    transform: translateX(26px);
  }
  to {
    opacity: 1;
    transform: none;
  }
}

.head {
  display: flex;
  align-items: flex-start;
  gap: var(--sp-4);
  padding: var(--sp-5) var(--sp-5) var(--sp-4);
  border-bottom: 1px solid var(--line);
}
.h {
  font-size: var(--fs-md);
  font-weight: var(--fw-semi);
  color: var(--ink);
}
.hs {
  margin-top: 3px;
  font-size: var(--fs-xs);
  color: var(--ink-4);
}
.x {
  margin-left: auto;
  width: 30px;
  height: 30px;
  flex: none;
  display: grid;
  place-items: center;
  border-radius: var(--r-sm);
  color: var(--ink-3);
  border: 1px solid var(--line);
  transition: color var(--t-fast) var(--ease-out), background var(--t-fast) var(--ease-out);
}
.x:hover {
  color: var(--ink);
  background: var(--surface-3);
}
.x :deep(svg) {
  width: 15px;
  height: 15px;
}

.body {
  flex: 1;
  overflow-y: auto;
  padding: var(--sp-5);
  display: flex;
  flex-direction: column;
  gap: var(--sp-6);
}

.gt {
  font-size: var(--fs-sm);
  font-weight: var(--fw-semi);
  color: var(--ink-2);
  margin-bottom: var(--sp-3);
  letter-spacing: 0.02em;
}

.tiles {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: var(--sp-3);
}
.tile {
  display: flex;
  flex-direction: column;
  gap: 7px;
  padding: 7px;
  border-radius: var(--r-md);
  border: 1px solid var(--line);
  background: var(--surface-2);
  transition: border-color var(--t-base) var(--ease-out),
    transform var(--t-base) var(--ease-out), box-shadow var(--t-base) var(--ease-out);
}
.tile:hover {
  transform: translateY(-1px);
  border-color: var(--line-3);
}
.tile.on {
  border-color: var(--accent);
  box-shadow: var(--ring-accent);
}
.swatch {
  display: block;
  height: 52px;
  border-radius: var(--r-sm);
  border: 1px solid var(--line);
}
.tile-default {
  background: radial-gradient(circle at 30% 20%, rgba(61, 139, 255, 0.32), transparent 60%),
    radial-gradient(circle at 80% 90%, rgba(42, 212, 200, 0.2), transparent 62%),
    var(--surface-0);
}
.tn {
  font-size: var(--fs-xs);
  color: var(--ink-3);
  text-align: center;
}
.tile.on .tn {
  color: var(--accent-hi);
  font-weight: var(--fw-semi);
}

.preview {
  display: flex;
  gap: var(--sp-3);
  padding: var(--sp-3);
  border-radius: var(--r-md);
  background: var(--surface-2);
  border: 1px solid var(--line);
  margin-bottom: var(--sp-3);
}
.preview img {
  width: 116px;
  height: 70px;
  object-fit: cover;
  border-radius: var(--r-sm);
  border: 1px solid var(--line-2);
}
.pv-side {
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
  justify-content: center;
}
.pv-tag {
  font-size: var(--fs-xs);
  color: var(--ok);
  font-weight: var(--fw-semi);
}
.pv-clear {
  align-self: flex-start;
  font-size: var(--fs-xs);
  color: var(--ink-3);
  padding: 3px 9px;
  border-radius: var(--r-full);
  border: 1px solid var(--line-2);
  transition: color var(--t-fast) var(--ease-out), border-color var(--t-fast) var(--ease-out);
}
.pv-clear:hover {
  color: var(--danger);
  border-color: rgba(255, 95, 86, 0.45);
}

.upload {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
  padding: var(--sp-4);
  border-radius: var(--r-md);
  border: 1px dashed var(--line-3);
  background: var(--surface-2);
  cursor: pointer;
  transition: border-color var(--t-base) var(--ease-out),
    background var(--t-base) var(--ease-out);
}
.upload:hover {
  border-color: var(--accent);
  background: var(--surface-3);
}
.up-ico {
  width: 22px;
  height: 22px;
  color: var(--accent-hi);
  flex: none;
  display: inline-flex;
}
.up-ico :deep(svg) {
  width: 100%;
  height: 100%;
}
.up-txt {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.up-txt b {
  font-size: var(--fs-sm);
  font-weight: var(--fw-semi);
  color: var(--ink);
}
.up-txt i {
  font-style: normal;
  font-size: var(--fs-xs);
  color: var(--ink-4);
}

.err {
  margin-top: var(--sp-2);
  font-size: var(--fs-xs);
  color: var(--danger);
}

.tip {
  font-size: var(--fs-xs);
  color: var(--ink-4);
  line-height: var(--lh-normal);
  padding-top: var(--sp-4);
  border-top: 1px solid var(--line);
}

.overlay-enter-active,
.overlay-leave-active {
  transition: opacity var(--t-base) var(--ease-out);
}
.overlay-enter-from,
.overlay-leave-to {
  opacity: 0;
}
</style>
