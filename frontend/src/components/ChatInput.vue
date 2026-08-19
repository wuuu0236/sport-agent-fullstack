<template>
  <div class="input">
    <textarea
      v-model="text"
      @keyup.enter.exact.prevent="send"
      @paste="onPaste"
      placeholder="说点什么，比如「我昨天跑了 5 公里」"
    ></textarea>
    <button @click="send" :disabled="busy">发送</button>
    <button class="orchestrate" @click="orchestrate" :disabled="orchestrating">
      {{ orchestrating ? '协作中…' : '多 Agent 协作' }}
    </button>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'

const props = defineProps<{
  busy: boolean
  orchestrating: boolean
}>()
const emit = defineEmits<{
  (e: 'send', text: string): void
  (e: 'orchestrate', text: string): void
  (e: 'pasteImage', file: File): void
}>()

const text = ref('')

function send() {
  const t = text.value.trim()
  if (!t || props.busy) return
  emit('send', t)
  text.value = ''
}

function orchestrate() {
  if (props.orchestrating) return
  const t = text.value.trim()
  emit('orchestrate', t)
  text.value = ''
}

// Ctrl+V 粘贴图片：从剪贴板取图片直接 OCR 导入
function onPaste(e: ClipboardEvent) {
  const items = e.clipboardData?.items
  if (!items) return
  for (const it of items) {
    if (it.type.startsWith('image/')) {
      const f = it.getAsFile()
      if (f) {
        e.preventDefault()
        emit('pasteImage', f)
      }
      break
    }
  }
}
</script>

<style scoped>
.input {
  display: flex;
  gap: 8px;
  margin-top: 10px;
}
textarea {
  flex: 1;
  height: 60px;
  resize: none;
  padding: 10px 12px;
  border: 1px solid var(--border);
  border-radius: 10px;
  font-family: inherit;
  font-size: 15px;
  background: var(--bg-soft);
  color: var(--text);
  outline: none;
  transition: border-color 0.12s;
}
textarea:focus {
  border-color: var(--accent);
}
textarea::placeholder {
  color: var(--faint);
}
button {
  padding: 0 22px;
  border: none;
  border-radius: 10px;
  background: var(--accent);
  color: #fff;
  cursor: pointer;
  font-size: 15px;
  transition: background 0.12s;
}
button:hover:not(:disabled) {
  background: var(--accent-hover);
}
button.orchestrate {
  background: var(--ok);
}
button.orchestrate:hover:not(:disabled) {
  filter: brightness(1.1);
}
button:disabled {
  opacity: 0.5;
  cursor: default;
}
</style>
