<template>
  <div
    class="chat-module"
    @dragover.prevent="onDragEnter"
    @dragleave.prevent="onDragLeave"
    @drop.prevent="onDrop"
  >
    <!-- 左：会话列表 -->
    <SessionList
      :sessions="sessions"
      :currentId="currentId"
      @new="createNew"
      @select="select"
      @delete="remove"
    />

    <!-- 中：会话主区 -->
    <main class="col">
      <div ref="scrollRef" class="scroll">
        <div class="inner">
          <ChatHeader :conn="conn" :connText="connText" />

          <!-- 空会话：欢迎态 + 推荐提问 -->
          <section v-if="!messages.length" class="welcome">
            <span class="w-ava" v-html="COACH_ICON" />
            <h2 class="w-title">今天练什么？</h2>
            <p class="w-desc">
              我是谭成义。跑步、减脂、增肌、练部位、伤痛排查都能聊；
              也可以直接发训练截图，我帮你记进训练库。
            </p>
            <div class="chips">
              <button v-for="s in SUGGESTIONS" :key="s.text" class="chip" @click="send(s.text)">
                <span class="c-ico" v-html="s.icon" />
                <span class="c-tx">{{ s.text }}</span>
              </button>
            </div>
          </section>

          <!-- 消息流 -->
          <div v-else class="stream">
            <MessageBubble v-for="(m, i) in messages" :key="i" :msg="m" />
            <PendingCommitCard
              v-if="pendingCommit"
              :count="pendingCommit.count"
              :records="pendingCommit.records"
              @confirm="commit"
              @dismiss="dismissCommit"
            />
          </div>
        </div>
      </div>

      <!-- 底部输入区 -->
      <div class="dock">
        <div class="dock-inner">
          <ChatComposer
            :busy="busy || uploading"
            :orchestrating="orchestrating"
            :placeholder="
              uploading ? '正在识别截图…' : '记录一次训练、问训练问题，或让我生成周报…'
            "
            @send="send"
            @orchestrate="orchestrateNow"
            @pickFile="pickFile"
            @pasteImage="handleImage"
          />
          <p class="foot-hint">
            本地优先：训练数据与记忆都存在本机，OCR 也在本地跑，不上传第三方
          </p>
        </div>
      </div>

      <!-- 拖拽导入遮罩 -->
      <DropOverlay :active="dragging" />
    </main>

    <!-- 右：用户画像 -->
    <ProfilePanel :entries="profile" @reload="loadProfile" />

    <input ref="fileInput" type="file" accept="image/*" hidden @change="onFileChange" />
  </div>
</template>

<script setup lang="ts">
import { nextTick, onMounted, ref, watch } from 'vue'
import SessionList from '../components/chat/SessionList.vue'
import ChatHeader from '../components/chat/ChatHeader.vue'
import MessageBubble from '../components/chat/MessageBubble.vue'
import ChatComposer from '../components/chat/ChatComposer.vue'
import ProfilePanel from '../components/chat/ProfilePanel.vue'
import PendingCommitCard from '../components/chat/PendingCommitCard.vue'
import DropOverlay from '../components/chat/DropOverlay.vue'
import { useSessions } from '../composables/useSessions'
import { useAgentChat } from '../composables/useAgentChat'

// 会话与对话逻辑分别收在 composable 里，视图只负责组装与布局
const { sessions, currentId, messages, ensure, createNew, select, remove, renameCurrent } =
  useSessions()

const {
  busy,
  uploading,
  orchestrating,
  conn,
  connText,
  pendingCommit,
  profile,
  refreshConn,
  loadProfile,
  send,
  orchestrateNow,
  importFile,
  commit,
  dismissCommit,
} = useAgentChat({
  messages,
  onFirstMessage: (text) => renameCurrent(text),
})

const STROKE =
  'fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"'
const COACH_ICON = `<svg viewBox="0 0 24 24" ${STROKE}><path d="M5 8.5c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2v7c0 1.1-.9 2-2 2H7c-1.1 0-2-.9-2-2z"/><path d="M6.5 6V5a1.5 1.5 0 0 1 1.5-1.5h8A1.5 1.5 0 0 1 17.5 5v1"/><path d="M9 13.5h6"/></svg>`

// 推荐提问：覆盖记录 / 报告 / 伤痛 / 分析四条主路径
const SUGGESTIONS = [
  {
    text: '记录一下今天卧推 4 组 × 8 次，60 公斤',
    icon: `<svg viewBox="0 0 24 24" ${STROKE}><path d="M5 4.6h14v14.8H5z"/><path d="M8.6 9.2h6.8M8.6 12.6h6.8M8.6 16h3.8"/></svg>`,
  },
  {
    text: '帮我生成本周训练周报',
    icon: `<svg viewBox="0 0 24 24" ${STROKE}><path d="M6 4.4h9l3.6 3.6v11.6H6z"/><path d="M14.4 4.4V8h3.6M9 12.4h6M9 15.6h4"/></svg>`,
  },
  {
    text: '跑步时膝盖疼，这个动作还能练吗',
    icon: `<svg viewBox="0 0 24 24" ${STROKE}><path d="M12 4.6 20 18.8H4z"/><path d="M12 10v3.4M12 16.2v.2"/></svg>`,
  },
  {
    text: '看看我最近的跑量和负荷趋势',
    icon: `<svg viewBox="0 0 24 24" ${STROKE}><path d="M4 19V11M9.3 19V6M14.7 19v-5M20 19V9"/></svg>`,
  },
]

// ---------- 滚动跟随 ----------
const scrollRef = ref<HTMLElement | null>(null)
watch(
  () => [messages.value.length, JSON.stringify(messages.value.at(-1)?.thinking?.steps ?? [])],
  async () => {
    await nextTick()
    const el = scrollRef.value
    if (el) el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' })
  },
)

// ---------- 图片：选择 / 拖拽 ----------
const fileInput = ref<HTMLInputElement | null>(null)
function pickFile() {
  fileInput.value?.click()
}
function onFileChange(e: Event) {
  const f = (e.target as HTMLInputElement).files?.[0]
  ;(e.target as HTMLInputElement).value = ''
  if (f) handleImage(f)
}
function handleImage(file: File) {
  importFile(file)
}

// dragenter/dragleave 会在子元素间反复触发，用计数器避免遮罩闪烁
const dragging = ref(false)
let dragDepth = 0
function onDragEnter(e: DragEvent) {
  if (!e.dataTransfer?.types?.includes('Files')) return
  dragDepth++
  dragging.value = true
}
function onDragLeave() {
  dragDepth = Math.max(0, dragDepth - 1)
  if (!dragDepth) dragging.value = false
}
function onDrop(e: DragEvent) {
  dragDepth = 0
  dragging.value = false
  const f = e.dataTransfer?.files?.[0]
  if (f) handleImage(f)
}

onMounted(() => {
  ensure()
  refreshConn()
  loadProfile()
})
</script>

<style scoped>
.chat-module {
  position: relative;
  display: flex;
  flex: 1;
  min-width: 0;
  height: 100vh;
}

/* 中间列：滚动区 + 固定底部输入 */
.col {
  position: relative;
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  height: 100vh;
}
.scroll {
  flex: 1;
  overflow-y: auto;
  scroll-behavior: smooth;
}
.inner {
  width: 100%;
  max-width: var(--content-max);
  margin: 0 auto;
  padding: 0 var(--sp-6) var(--sp-4);
  display: flex;
  flex-direction: column;
  min-height: 100%;
}

/* ---------- 欢迎态 ---------- */
.welcome {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
  padding: var(--sp-6) 0 var(--sp-8);
  animation: fade-up var(--t-slow) var(--ease-out) both;
}
.w-ava {
  width: 62px;
  height: 62px;
  display: grid;
  place-items: center;
  border-radius: var(--r-xl);
  color: #ffb08a;
  background: linear-gradient(180deg, rgba(255, 122, 69, 0.2), rgba(255, 122, 69, 0.07));
  border: 1px solid rgba(255, 122, 69, 0.32);
  box-shadow: var(--hairline-top), var(--shadow-2);
  margin-bottom: var(--sp-4);
}
.w-ava :deep(svg) {
  width: 30px;
  height: 30px;
}
.w-title {
  font-size: var(--fs-xl);
  font-weight: var(--fw-bold);
  letter-spacing: -0.02em;
  background: linear-gradient(180deg, var(--ink), #a8b6c8);
  -webkit-background-clip: text;
  background-clip: text;
  -webkit-text-fill-color: transparent;
}
.w-desc {
  margin-top: 10px;
  max-width: 470px;
  font-size: var(--fs-sm);
  color: var(--ink-3);
  line-height: var(--lh-loose);
}

.chips {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--sp-3);
  margin-top: var(--sp-6);
  width: 100%;
  max-width: 620px;
}
.chip {
  display: flex;
  align-items: center;
  gap: 11px;
  padding: 13px 15px;
  border-radius: var(--r-md);
  background: color-mix(in srgb, var(--surface-2) 82%, transparent);
  border: 1px solid var(--line);
  box-shadow: var(--hairline-top);
  color: var(--ink-2);
  text-align: left;
  transition: transform var(--t-base) var(--ease-out),
    border-color var(--t-base) var(--ease-out), background var(--t-base) var(--ease-out);
}
.chip:hover {
  transform: translateY(-2px);
  border-color: color-mix(in srgb, var(--accent) 40%, transparent);
  background: var(--surface-3);
  color: var(--ink);
}
.c-ico {
  width: 17px;
  height: 17px;
  flex: none;
  color: var(--accent-hi);
  display: inline-flex;
}
.c-ico :deep(svg) {
  width: 100%;
  height: 100%;
}
.c-tx {
  font-size: var(--fs-sm);
}

/* ---------- 消息流 ---------- */
.stream {
  display: flex;
  flex-direction: column;
  gap: var(--sp-5);
  padding-top: var(--sp-2);
}

/* ---------- 底部输入区 ---------- */
.dock {
  flex: none;
  padding: 0 var(--sp-6) var(--sp-5);
  /* 半透明渐隐：有壁纸时也不糊成一块黑板 */
  background: linear-gradient(
    180deg,
    transparent,
    color-mix(in srgb, var(--surface-0) 86%, transparent) 62%
  );
}
.dock-inner {
  width: 100%;
  max-width: var(--content-max);
  margin: 0 auto;
}
.foot-hint {
  margin-top: 9px;
  text-align: center;
  font-size: 11px;
  color: var(--ink-4);
}
</style>
