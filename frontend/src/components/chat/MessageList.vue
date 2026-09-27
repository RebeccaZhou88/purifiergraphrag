<template>
  <div ref="listRef" class="msg-list">
    <div v-if="!messages.length" class="welcome">
      <el-icon :size="40"><MagicStick /></el-icon>
      <p>净水器售后知识图谱助手</p>
      <ul class="suggest">
        <li @click="$emit('pick', 'PG-A100 能用哪些滤芯？')">PG-A100 能用哪些滤芯？</li>
        <li @click="$emit('pick', 'PG-A200 漏水怎么排查？')">PG-A200 漏水怎么排查？</li>
        <li @click="$emit('pick', 'BATCH-2024C 召回影响哪些客户？')">BATCH-2024C 召回影响哪些客户？</li>
      </ul>
    </div>

    <div v-for="m in messages" :key="m.id" class="msg-row" :class="m.role">
      <div class="avatar">{{ m.role === 'user' ? '我' : 'AI' }}</div>
      <div class="bubble" :class="m.role">
        <!-- 机器人回复默认展开：内容始终直接可见 -->
        <div class="content">
          <span>{{ m.content }}</span>
          <span v-if="m.streaming" class="cursor" />
        </div>
        <ReferenceFragments v-if="m.role === 'assistant' && m.fragments?.length" :fragments="m.fragments!" />
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
// @Author: RebeccaZhou
// @Description: Chat message list component
//              聊天消息列表组件
import { nextTick, ref, watch } from 'vue'
import type { ChatMessage } from '@/stores/chat'
import ReferenceFragments from './ReferenceFragments.vue'

const props = defineProps<{ messages: ChatMessage[] }>()
defineEmits<{ (e: 'pick', q: string): void }>()
const listRef = ref<HTMLElement>()

watch(
  () => props.messages.map((m) => m.content).join('|') + props.messages.length,
  async () => {
    await nextTick()
    const el = listRef.value
    if (el) el.scrollTop = el.scrollHeight
  },
)
</script>

<style scoped>
.msg-list {
  height: 100%;
  overflow-y: auto;
  padding: 20px;
}
.welcome {
  height: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  color: var(--pg-muted);
  gap: 8px;
}
.welcome .suggest {
  margin-top: 12px;
  padding: 0;
  list-style: none;
  text-align: center;
  font-size: 13px;
  line-height: 2;
}
.welcome .suggest li {
  cursor: pointer;
  border-radius: 6px;
  padding: 0 12px;
}
.welcome .suggest li:hover {
  background: #eef2ff;
  color: var(--pg-primary);
}
.msg-row {
  display: flex;
  gap: 10px;
  margin-bottom: 18px;
}
.msg-row.user {
  flex-direction: row-reverse;
}
.avatar {
  width: 34px;
  height: 34px;
  border-radius: 50%;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 13px;
  font-weight: 600;
  color: #fff;
  background: var(--pg-primary);
}
.msg-row.user .avatar {
  background: #0ea5e9;
}
.bubble {
  max-width: 72%;
  padding: 10px 14px;
  border-radius: 10px;
  line-height: 1.7;
  font-size: 14px;
  white-space: pre-wrap;
  word-break: break-word;
}
.bubble.assistant {
  background: #fff;
  border: 1px solid var(--pg-border);
  border-top-left-radius: 2px;
}
.bubble.user {
  background: var(--pg-primary);
  color: #fff;
  border-top-right-radius: 2px;
}
.content {
  min-height: 20px;
}
.cursor {
  display: inline-block;
  width: 7px;
  height: 15px;
  background: var(--pg-primary);
  margin-left: 2px;
  vertical-align: -2px;
  animation: blink 1s steps(2) infinite;
}
@keyframes blink {
  0%,
  100% {
    opacity: 1;
  }
  50% {
    opacity: 0;
  }
}
</style>
