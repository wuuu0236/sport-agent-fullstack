<template>
  <div class="mem">
    <div class="wrap">
      <SectionTitle title="记忆" :desc="'长期记忆双存储：关于你的事实 + 助理笔记，跨会话常驻并注入子 Agent 上下文'">
        <AppButton variant="subtle" size="sm" :icon="REFRESH_ICON" :busy="loading" @click="load">
          刷新
        </AppButton>
      </SectionTitle>

      <div class="cards">
        <!-- USER：关于用户的事实 -->
        <AppCard>
          <template #extra>
            <AppPill tone="accent" size="sm">{{ data.user.length }} 条</AppPill>
          </template>
          <div class="col-head">
            <span class="col-ico" :style="{ '--h': '#3d8bff' }" v-html="USER_ICON" />
            <div>
              <h3 class="col-title">关于你</h3>
              <p class="col-sub">身份 / 偏好 / 身体基线 · <code>USER.md</code></p>
            </div>
          </div>

          <ul v-if="data.user.length" class="entries">
            <li v-for="(e, i) in data.user" :key="i" class="entry">
              <span class="idx num">{{ String(i + 1).padStart(2, '0') }}</span>
              <span class="tx">{{ e }}</span>
            </li>
          </ul>
          <p v-else class="empty">
            还没有关于你的记忆。对助理说「记住我每周三晨跑」试试。
          </p>
        </AppCard>

        <!-- MEMORY：助理笔记 -->
        <AppCard>
          <template #extra>
            <AppPill tone="energy" size="sm">{{ data.memory.length }} 条</AppPill>
          </template>
          <div class="col-head">
            <span class="col-ico" :style="{ '--h': '#f0b23c' }" v-html="NOTE_ICON" />
            <div>
              <h3 class="col-title">助理笔记</h3>
              <p class="col-sub">陪练经验与约定 · <code>MEMORY.md</code></p>
            </div>
          </div>

          <ul v-if="data.memory.length" class="entries">
            <li v-for="(e, i) in data.memory" :key="i" class="entry">
              <span class="idx num">{{ String(i + 1).padStart(2, '0') }}</span>
              <span class="tx">{{ e }}</span>
            </li>
          </ul>
          <p v-else class="empty">还没有助理笔记。</p>
        </AppCard>
      </div>

      <!-- 注入快照 -->
      <AppCard v-if="data.snapshot" class="snap">
        <template #extra>
          <AppButton variant="ghost" size="sm" @click="toggleSnap">
            {{ snapOpen ? '收起' : '展开' }}
          </AppButton>
        </template>
        <div class="col-head">
          <span class="col-ico" :style="{ '--h': '#2ad4c8' }" v-html="SNAP_ICON" />
          <div>
            <h3 class="col-title">注入快照</h3>
            <p class="col-sub">各子 Agent 上下文里实际看到的记忆内容</p>
          </div>
        </div>
        <pre v-if="snapOpen" class="snap-body num">{{ data.snapshot }}</pre>
        <p v-else class="snap-fold num">{{ preview }}</p>
      </AppCard>

      <p class="tip">
        记忆由「记住 / 记下 …」这类指令触发写入，存在本机；写入前会做长度上限校验，超限会被拒绝并如实告知，不会静默截断。
      </p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import AppCard from '../components/ui/AppCard.vue'
import AppPill from '../components/ui/AppPill.vue'
import AppButton from '../components/ui/AppButton.vue'
import SectionTitle from '../components/ui/SectionTitle.vue'
import { getMemory } from '../api/client'

const STROKE =
  'fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"'
const REFRESH_ICON = `<svg viewBox="0 0 24 24" ${STROKE}><path d="M19.5 12a7.5 7.5 0 1 1-2.3-5.4"/><path d="M19.9 4.6v4.2h-4.2"/></svg>`
const USER_ICON = `<svg viewBox="0 0 24 24" ${STROKE}><circle cx="12" cy="8.4" r="3.6"/><path d="M4.8 19.6a7.2 7.2 0 0 1 14.4 0"/></svg>`
const NOTE_ICON = `<svg viewBox="0 0 24 24" ${STROKE}><path d="M6 3.8h8.6L19 8.2v12H6z"/><path d="M14.2 3.8v4.6H19"/><path d="M9 12.4h6.4M9 15.6h4.4"/></svg>`
const SNAP_ICON = `<svg viewBox="0 0 24 24" ${STROKE}><path d="M12 3.6 20 8.4v7.2L12 20.4 4 15.6V8.4z"/><path d="M12 12v8.4M12 12l8-3.6M12 12 4 8.4"/></svg>`

const data = ref<{ user: string[]; memory: string[]; snapshot: string }>({
  user: [],
  memory: [],
  snapshot: '',
})
const loading = ref(false)
const snapOpen = ref(false)

const preview = computed(() => {
  const s = data.value.snapshot || ''
  // 只取真正的首几条内容：跳过 § 分隔符与空行
  const lines = s
    .split('\n')
    .map((l) => l.trim())
    .filter((l) => l && l !== '§')
  return lines.length > 3 ? lines.slice(0, 3).join('\n') + '\n…' : lines.join('\n')
})

function toggleSnap() {
  snapOpen.value = !snapOpen.value
}

async function load() {
  loading.value = true
  try {
    data.value = await getMemory()
  } catch {
    data.value = { user: [], memory: [], snapshot: '' }
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.mem {
  flex: 1;
  min-width: 0;
  height: 100vh;
  overflow-y: auto;
}
.wrap {
  max-width: 1080px;
  margin: 0 auto;
  padding: var(--sp-6) var(--sp-7) var(--sp-8);
}

.cards {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--sp-4);
}
@media (max-width: 1000px) {
  .cards {
    grid-template-columns: minmax(0, 1fr);
  }
}

.col-head {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
  padding-bottom: var(--sp-3);
  margin-bottom: var(--sp-3);
  border-bottom: 1px solid var(--line);
}
.col-ico {
  width: 30px;
  height: 30px;
  flex: none;
  display: grid;
  place-items: center;
  border-radius: var(--r-sm);
  color: var(--h);
  background: color-mix(in srgb, var(--h) 14%, transparent);
  border: 1px solid color-mix(in srgb, var(--h) 28%, transparent);
}
.col-ico :deep(svg) {
  width: 16px;
  height: 16px;
}
.col-title {
  font-size: var(--fs-md);
  font-weight: var(--fw-semi);
  color: var(--ink);
}
.col-sub {
  margin-top: 2px;
  font-size: var(--fs-xs);
  color: var(--ink-4);
}
.col-sub code {
  font-family: var(--font-mono);
  font-size: 10.5px;
  padding: 1px 4px;
  border-radius: var(--r-xs);
  background: var(--surface-4);
  border: 1px solid var(--line);
}

.entries {
  display: flex;
  flex-direction: column;
  gap: 7px;
}
.entry {
  display: flex;
  gap: 11px;
  align-items: flex-start;
  padding: 10px 12px;
  border-radius: var(--r-md);
  background: var(--surface-1);
  border: 1px solid var(--line);
  transition: border-color var(--t-base) var(--ease-out);
}
.entry:hover {
  border-color: var(--line-3);
}
.idx {
  font-size: 10.5px;
  color: var(--ink-4);
  padding-top: 2px;
  flex: none;
}
.tx {
  font-size: var(--fs-sm);
  color: var(--ink-2);
  line-height: var(--lh-normal);
}

.empty {
  font-size: var(--fs-sm);
  color: var(--ink-4);
  padding: var(--sp-4) 0;
}

.snap {
  margin-top: var(--sp-4);
}
.snap-body {
  margin-top: var(--sp-2);
  padding: var(--sp-4);
  border-radius: var(--r-md);
  background: var(--pre-bg);
  border: 1px solid var(--line);
  font-family: var(--font-mono);
  font-size: var(--fs-xs);
  line-height: 1.75;
  color: var(--ink-2);
  max-height: 340px;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-word;
}
.snap-fold {
  margin-top: var(--sp-2);
  padding: var(--sp-3) var(--sp-4);
  border-radius: var(--r-md);
  background: var(--surface-1);
  border: 1px dashed var(--line-2);
  font-family: var(--font-mono);
  font-size: var(--fs-xs);
  line-height: 1.7;
  color: var(--ink-4);
  white-space: pre-wrap;
}

.tip {
  margin-top: var(--sp-5);
  font-size: var(--fs-xs);
  color: var(--ink-4);
  line-height: var(--lh-normal);
}
</style>
