<template>
  <div
    class="dropzone"
    :class="{ over: dragOver }"
    @click="emit('pick')"
    @dragover.prevent="dragOver = true"
    @dragleave.prevent="dragOver = false"
    @drop.prevent="onDrop"
  >
    <span v-if="!uploading">把训练截图拖到这里，或点击选择图片（本地 OCR，不上传）</span>
    <span v-else>正在识别截图…</span>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'

defineProps<{ uploading: boolean }>()
const emit = defineEmits<{
  (e: 'pick'): void
  (e: 'dropFile', file: File): void
}>()

const dragOver = ref(false)

function onDrop(e: DragEvent) {
  dragOver.value = false
  const f = e.dataTransfer?.files?.[0]
  if (f) emit('dropFile', f)
}
</script>

<style scoped>
.dropzone {
  border: 1.5px dashed var(--border);
  border-radius: 12px;
  padding: 14px;
  text-align: center;
  font-size: 13px;
  color: var(--muted);
  cursor: pointer;
  transition: background 0.15s, border-color 0.15s;
  margin-bottom: 4px;
  background: color-mix(in srgb, var(--bg-soft) 60%, transparent);
}
.dropzone:hover {
  border-color: var(--accent);
  background: var(--card-hover);
}
.dropzone.over {
  border-color: var(--accent);
  background: var(--accent-soft);
}
</style>
