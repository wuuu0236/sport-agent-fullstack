<template>
  <div class="sk" :style="style"></div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

// 骨架屏占位块：宽度/高度/圆角可配，自带流光动效
const props = withDefaults(
  defineProps<{ w?: string; h?: string; r?: string }>(),
  { w: '100%', h: '14px', r: 'var(--r-sm)' },
)

const style = computed(() => ({ width: props.w, height: props.h, borderRadius: props.r }))
</script>

<style scoped>
.sk {
  background: linear-gradient(
    90deg,
    var(--surface-3) 0%,
    var(--surface-4) 40%,
    var(--surface-3) 80%
  );
  background-size: 200% 100%;
  animation: shimmer 1.5s linear infinite;
}
</style>
