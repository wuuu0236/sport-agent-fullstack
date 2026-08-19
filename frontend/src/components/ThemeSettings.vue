<template>
  <div v-if="open" class="overlay" @click.self="emit('close')">
    <div class="settings">
      <div class="settings-head">
        <span class="title">🎨 外观设置</span>
        <button class="close" @click="emit('close')">✕</button>
      </div>

      <div class="group">
        <div class="group-title">聊天背景壁纸</div>
        <div class="wallpaper-actions">
          <label class="upload-btn" for="wallpaper-input">📁 上传图片作壁纸</label>
          <input
            id="wallpaper-input"
            type="file"
            accept="image/*"
            hidden
            @change="onUpload"
          />
          <button class="ghost" :disabled="!wallpaper" @click="setWallpaper(null)">
            清除壁纸
          </button>
        </div>
        <div v-if="wallpaper" class="wallpaper-preview">
          <img :src="previewSrc" alt="壁纸预览" />
          <span class="preview-tip">当前壁纸（已压缩保存，刷新不丢）</span>
        </div>
        <div v-else class="wallpaper-empty">
          未设置壁纸，使用暗色纯色背景。上传后自动铺满聊天区域。
        </div>
        <div class="presets">
          <button
            v-for="p in WALLPAPER_PRESETS"
            :key="p.id"
            class="preset"
            :class="{ active: wallpaper === presetToStored(p) }"
            :style="{ background: p.css }"
            :title="p.name"
            @click="setWallpaper(presetToStored(p))"
          ></button>
        </div>
      </div>

      <div class="tip">壁纸仅保存在本机浏览器（localStorage），不上传服务器。</div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { fileToCompressedDataUrl } from '../utils/image'
import { WALLPAPER_PRESETS, presetToStored } from '../utils/wallpaper'

const props = defineProps<{ open: boolean; wallpaper: string | null }>()
const emit = defineEmits<{
  (e: 'close'): void
  (e: 'setWallpaper', stored: string | null): void
}>()

function setWallpaper(stored: string | null) {
  emit('setWallpaper', stored)
}

// 预览图：预设显示其渐变（无 img 标签，直接看底色即可）；自定义图片显示 base64
const previewSrc = computed(() => {
  const w = props.wallpaper
  if (!w || w.startsWith('preset:')) return ''
  return w
})

async function onUpload(e: Event) {
  const f = (e.target as HTMLInputElement).files?.[0]
  ;(e.target as HTMLInputElement).value = ''
  if (!f) return
  try {
    const dataUrl = await fileToCompressedDataUrl(f)
    setWallpaper(dataUrl)
  } catch (err) {
    alert('壁纸处理失败：' + String(err))
  }
}
</script>

<style scoped>
.overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.55);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 100;
}
.settings {
  width: 420px;
  max-width: 92vw;
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 14px;
  padding: 18px;
  box-shadow: 0 18px 50px rgba(0, 0, 0, 0.45);
}
.settings-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}
.title {
  font-weight: 600;
  font-size: 16px;
}
.close {
  background: transparent;
  border: none;
  color: var(--muted);
  font-size: 15px;
  cursor: pointer;
  padding: 4px 8px;
  border-radius: 6px;
}
.close:hover {
  background: var(--card-hover);
  color: var(--text);
}
.group-title {
  font-size: 13px;
  color: var(--muted);
  margin-bottom: 10px;
}
.wallpaper-actions {
  display: flex;
  gap: 8px;
  align-items: center;
}
.upload-btn {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 7px 14px;
  border-radius: 8px;
  background: var(--accent);
  color: #fff;
  font-size: 13px;
  cursor: pointer;
}
.upload-btn:hover {
  background: var(--accent-hover);
}
.ghost {
  padding: 7px 14px;
  border-radius: 8px;
  border: 1px solid var(--border);
  background: transparent;
  color: var(--muted);
  font-size: 13px;
  cursor: pointer;
}
.ghost:hover:not(:disabled) {
  background: var(--card-hover);
  color: var(--text);
}
.ghost:disabled {
  opacity: 0.4;
  cursor: default;
}
.wallpaper-preview {
  margin-top: 12px;
}
.wallpaper-preview img {
  width: 100%;
  max-height: 160px;
  object-fit: cover;
  border-radius: 8px;
  border: 1px solid var(--border);
}
.preview-tip {
  display: block;
  font-size: 11px;
  color: var(--faint);
  margin-top: 6px;
}
.wallpaper-empty {
  margin-top: 12px;
  font-size: 12px;
  color: var(--faint);
  background: var(--bg-soft);
  border: 1px dashed var(--border);
  border-radius: 8px;
  padding: 10px;
}
.presets {
  margin-top: 12px;
  display: flex;
  gap: 10px;
}
.preset {
  width: 44px;
  height: 44px;
  border-radius: 10px;
  border: 2px solid var(--border);
  cursor: pointer;
  transition: transform 0.12s, border-color 0.12s;
}
.preset:hover {
  transform: scale(1.08);
}
.preset.active {
  border-color: var(--accent);
}
.tip {
  margin-top: 14px;
  font-size: 11px;
  color: var(--faint);
}
</style>
