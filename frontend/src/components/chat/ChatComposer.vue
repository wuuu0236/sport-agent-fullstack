<template>
  <div class="composer" :class="{ focus, busy }">
    <textarea
      ref="ta"
      v-model="text"
      class="input"
      rows="1"
      :placeholder="placeholder"
      spellcheck="false"
      @focus="focus = true"
      @blur="focus = false"
      @keydown="onKeydown"
      @paste="onPaste"
      @input="resize"
    />

    <div class="bar">
      <div class="left">
        <button class="icon-btn" title="导入训练截图（本地 OCR）" @click="emit('pickFile')">
          <span v-html="IMAGE_ICON" />
        </button>
        <span class="hint">
          <kbd>Enter</kbd> 发送 · <kbd>Shift</kbd>+<kbd>Enter</kbd> 换行 · 可粘贴截图
        </span>
      </div>

      <div class="right">
        <AppButton
          variant="subtle"
          size="sm"
          :busy="orchestrating"
          :disabled="busy"
          :icon="FLOW_ICON"
          @click="emit('orchestrate', text)"
        >
          多 Agent 编排
        </AppButton>
        <AppButton
          variant="primary"
          size="sm"
          :busy="busy"
          :disabled="!text.trim() && !busy"
          :icon="SEND_ICON"
          @click="submit"
        >
          发送
        </AppButton>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { nextTick, ref } from 'vue'
import AppButton from '../ui/AppButton.vue'

const props = withDefaults(
  defineProps<{ busy?: boolean; orchestrating?: boolean; placeholder?: string }>(),
  { busy: false, orchestrating: false, placeholder: '记录一次训练、问训练问题，或让我生成周报…' },
)
const emit = defineEmits<{
  send: [text: string]
  orchestrate: [text: string]
  pickFile: []
  pasteImage: [file: File]
}>()

const STROKE =
  'fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"'
const IMAGE_ICON = `<svg viewBox="0 0 24 24" ${STROKE}><rect x="3.6" y="4.8" width="16.8" height="14.4" rx="2.4"/><circle cx="9" cy="10" r="1.5"/><path d="M4.4 16.6l4.3-4.1a1.6 1.6 0 0 1 2.2 0l4 3.9M14.4 15.2l1.5-1.4a1.6 1.6 0 0 1 2.2 0l2 1.9"/></svg>`
const SEND_ICON = `<svg viewBox="0 0 24 24" ${STROKE}><path d="M4.5 12 20 5l-6.6 15-1.4-6z"/></svg>`
const FLOW_ICON = `<svg viewBox="0 0 24 24" ${STROKE}><circle cx="6" cy="6.5" r="2.2"/><circle cx="18" cy="12" r="2.2"/><circle cx="6" cy="17.5" r="2.2"/><path d="M8.2 6.5h4.3a2 2 0 0 1 2 2v1.3M8.2 17.5h4.3a2 2 0 0 0 2-2v-1.3"/></svg>`

const text = ref('')
const focus = ref(false)
const ta = ref<HTMLTextAreaElement | null>(null)

function resize() {
  const el = ta.value
  if (!el) return
  el.style.height = 'auto'
  el.style.height = Math.min(el.scrollHeight, 168) + 'px'
}

function submit() {
  const t = text.value.trim()
  if (!t || props.busy) return
  emit('send', t)
  text.value = ''
  nextTick(resize)
}

function onKeydown(e: KeyboardEvent) {
  // Enter 发送；Shift+Enter 换行；输入法组合中不拦截
  if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
    e.preventDefault()
    submit()
  }
}

function onPaste(e: ClipboardEvent) {
  const items = e.clipboardData?.items
  if (!items) return
  for (const it of items) {
    if (it.type.startsWith('image/')) {
      const f = it.getAsFile()
      if (f) {
        e.preventDefault()
        emit('pasteImage', f)
        return
      }
    }
  }
}
</script>

<style scoped>
.composer {
  border-radius: var(--r-lg);
  background: color-mix(in srgb, var(--surface-2) 92%, transparent);
  border: 1px solid var(--line-2);
  box-shadow: var(--hairline-top), var(--shadow-2);
  backdrop-filter: blur(14px);
  padding: 10px 12px 9px;
  transition: border-color var(--t-base) var(--ease-out),
    box-shadow var(--t-base) var(--ease-out);
}
.composer.focus {
  border-color: color-mix(in srgb, var(--accent) 50%, transparent);
  box-shadow: var(--hairline-top), var(--shadow-2), 0 0 0 3px rgba(61, 139, 255, 0.12);
}
.busy {
  opacity: 0.85;
}

.input {
  display: block;
  width: 100%;
  max-height: 168px;
  resize: none;
  border: none;
  outline: none;
  background: none;
  color: var(--ink);
  font-size: var(--fs-base);
  line-height: var(--lh-normal);
  padding: 5px 3px 9px;
}
.input::placeholder {
  color: var(--ink-4);
}

.bar {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
  flex-wrap: wrap;
}
.left {
  display: flex;
  align-items: center;
  gap: 9px;
  min-width: 0;
}
.right {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: var(--sp-2);
}

.icon-btn {
  width: 30px;
  height: 30px;
  flex: none;
  display: grid;
  place-items: center;
  border-radius: var(--r-sm);
  color: var(--ink-3);
  border: 1px solid var(--line);
  background: var(--surface-3);
  transition: color var(--t-fast) var(--ease-out), border-color var(--t-fast) var(--ease-out);
}
.icon-btn:hover {
  color: var(--accent-hi);
  border-color: color-mix(in srgb, var(--accent) 42%, transparent);
}
.icon-btn :deep(svg) {
  width: 15px;
  height: 15px;
}

.hint {
  font-size: 11px;
  color: var(--ink-4);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
kbd {
  font-family: var(--font-sans);
  font-size: 10px;
  padding: 1px 4px;
  border-radius: var(--r-xs);
  background: var(--surface-4);
  border: 1px solid var(--line);
  color: var(--ink-3);
}
@media (max-width: 1180px) {
  .hint {
    display: none;
  }
}
</style>
