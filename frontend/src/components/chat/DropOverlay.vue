<template>
  <Transition name="drop">
    <div v-if="active" class="overlay">
      <div class="box">
        <span class="ico" v-html="IMAGE_ICON" />
        <p class="t">松开导入训练截图</p>
        <p class="d">本地 OCR 识别后进入暂存区，确认才入库</p>
      </div>
    </div>
  </Transition>
</template>

<script setup lang="ts">
defineProps<{ active: boolean }>()

const IMAGE_ICON =
  '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><rect x="3.6" y="4.8" width="16.8" height="14.4" rx="2.4"/><circle cx="9" cy="10" r="1.5"/><path d="M4.4 16.6l4.3-4.1a1.6 1.6 0 0 1 2.2 0l4 3.9M14.4 15.2l1.5-1.4a1.6 1.6 0 0 1 2.2 0l2 1.9"/></svg>'
</script>

<style scoped>
.overlay {
  position: absolute;
  inset: 0;
  z-index: var(--z-overlay);
  display: grid;
  place-items: center;
  background: rgba(9, 13, 19, 0.72);
  backdrop-filter: blur(6px);
}
.box {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 9px;
  padding: 34px 46px;
  border-radius: var(--r-xl);
  border: 2px dashed color-mix(in srgb, var(--accent) 60%, transparent);
  background: rgba(61, 139, 255, 0.07);
  box-shadow: var(--shadow-3), 0 0 44px -12px rgba(61, 139, 255, 0.5);
  animation: pop-in var(--t-base) var(--ease-out) both;
}
.ico {
  width: 34px;
  height: 34px;
  color: var(--accent-hi);
  display: inline-flex;
}
.ico :deep(svg) {
  width: 100%;
  height: 100%;
}
.t {
  font-size: var(--fs-md);
  font-weight: var(--fw-semi);
  color: var(--ink);
}
.d {
  font-size: var(--fs-xs);
  color: var(--ink-3);
}

.drop-enter-active,
.drop-leave-active {
  transition: opacity var(--t-base) var(--ease-out);
}
.drop-enter-from,
.drop-leave-to {
  opacity: 0;
}
</style>
