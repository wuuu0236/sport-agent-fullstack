<template>
  <div class="memory-view">
    <div class="mem-head">
      <div class="mem-title">记忆</div>
      <div class="mem-sub">长期记忆双存储：关于用户的事实 + 助理笔记（跨会话常驻）</div>
    </div>

    <div class="cards">
      <div class="card">
        <div class="card-title">👤 关于你（USER）</div>
        <div v-if="data.user.length" class="entries">
          <div v-for="(e, i) in data.user" :key="i" class="entry">{{ e }}</div>
        </div>
        <div v-else class="empty">还没有关于你的记忆。对助理说「记住我每周三晨跑」试试</div>
      </div>

      <div class="card">
        <div class="card-title">📝 助理笔记（MEMORY）</div>
        <div v-if="data.memory.length" class="entries">
          <div v-for="(e, i) in data.memory" :key="i" class="entry">{{ e }}</div>
        </div>
        <div v-else class="empty">还没有助理笔记</div>
      </div>
    </div>

    <!-- 冻结快照：注入各 Agent 上下文的实际内容预览 -->
    <div v-if="data.snapshot" class="snapshot">
      <div class="card-title">🧩 注入快照（各 Agent 上下文里的实际内容）</div>
      <pre class="snapshot-body">{{ data.snapshot }}</pre>
    </div>

    <div class="tip">
      记忆由「记住 / 记下 …」触发写入，注入所有子 Agent 的上下文，跨会话常驻。
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { getMemory } from '../api/client'

const data = ref<{ user: string[]; memory: string[]; snapshot: string }>({ user: [], memory: [], snapshot: '' })

onMounted(async () => {
  try {
    data.value = await getMemory()
  } catch {
    data.value = { user: [], memory: [], snapshot: '' }
  }
})
</script>

<style scoped>
.memory-view {
  flex: 1;
  min-width: 0;
  max-width: 1080px;
  margin: 0 auto;
  padding: 28px 32px;
  height: 100vh;
  overflow-y: auto;
  box-sizing: border-box;
  scrollbar-width: thin;
  scrollbar-color: var(--border) transparent;
}
.mem-head {
  margin-bottom: 20px;
}
.mem-title {
  font-size: 24px;
  font-weight: 700;
}
.mem-sub {
  font-size: 13px;
  color: var(--faint);
  margin-top: 4px;
}
.cards {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 14px;
}
.card {
  background: color-mix(in srgb, var(--card) 85%, transparent);
  border: 1px solid var(--border);
  border-radius: 14px;
  padding: 18px;
}
.card-title {
  font-size: 15px;
  font-weight: 600;
  margin-bottom: 12px;
}
.entries {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.entry {
  font-size: 14px;
  color: var(--text-soft);
  background: var(--bg-soft);
  border: 1px solid var(--border-soft);
  border-radius: 8px;
  padding: 9px 12px;
  line-height: 1.55;
}
.empty {
  font-size: 14px;
  color: var(--faint);
  padding: 14px 0;
}
.snapshot {
  margin-top: 14px;
  background: color-mix(in srgb, var(--card) 85%, transparent);
  border: 1px solid var(--border);
  border-radius: 14px;
  padding: 18px;
}
.snapshot-body {
  margin: 0;
  font-size: 13px;
  line-height: 1.6;
  color: var(--text-soft);
  background: var(--bg-soft);
  border: 1px solid var(--border-soft);
  border-radius: 8px;
  padding: 12px;
  white-space: pre-wrap;
  word-break: break-word;
}
.tip {
  margin-top: 14px;
  font-size: 12px;
  color: var(--faint);
}
</style>
