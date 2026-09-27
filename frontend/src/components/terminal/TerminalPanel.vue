<template>
  <div class="terminal">
    <div class="terminal-head">
      <span class="dot" />
      <span class="title">实时执行日志</span>
      <span class="sub">Semantic Kernel · 检索过程</span>
    </div>
    <div ref="bodyRef" class="terminal-body">
      <div v-for="log in logs" :key="log.id" class="log-line">
        <span class="t">{{ log.time }}</span>
        <span class="step" :class="log.step">{{ log.step }}</span>
        <span class="msg">{{ log.message }}</span>
        <div v-if="log.data && Object.keys(log.data).length" class="data">
          {{ fmt(log.data) }}
        </div>
      </div>
      <div v-if="!logs.length" class="empty">等待提问，将在此实时输出各 Plugin 调用与 Cypher 检索过程…</div>
    </div>
  </div>
</template>

<script setup lang="ts">
// @Author: RebeccaZhou
// @Description: Pipeline step terminal panel component
//              流水线步骤终端面板组件
import { nextTick, ref, watch } from 'vue'
import type { TerminalLog } from '@/stores/chat'

const props = defineProps<{ logs: TerminalLog[] }>()
const bodyRef = ref<HTMLElement>()

function fmt(d: unknown) {
  try {
    return JSON.stringify(d, null, 0)
  } catch {
    return String(d)
  }
}

watch(
  () => props.logs.length,
  async () => {
    await nextTick()
    const el = bodyRef.value
    if (el) el.scrollTop = el.scrollHeight
  },
)
</script>

<style scoped>
.terminal {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: var(--pg-terminal-bg);
  border-radius: 8px;
  overflow: hidden;
}
.terminal-head {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  background: #1e293b;
  color: #cbd5e1;
  font-size: 12px;
}
.terminal-head .dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #22c55e;
}
.terminal-head .title {
  font-weight: 600;
}
.terminal-head .sub {
  color: #64748b;
  margin-left: auto;
}
.terminal-body {
  flex: 1;
  overflow-y: auto;
  padding: 10px 12px;
  font-family: 'Cascadia Code', Consolas, monospace;
  font-size: 12px;
  line-height: 1.7;
  color: var(--pg-terminal-fg);
}
.log-line {
  margin-bottom: 2px;
}
.log-line .t {
  color: #64748b;
  margin-right: 8px;
}
.log-line .step {
  display: inline-block;
  min-width: 128px;
  color: #38bdf8;
}
.log-line .step.error {
  color: #f87171;
}
.log-line .step.pipeline {
  color: #c084fc;
}
.log-line .msg {
  color: #e2e8f0;
}
.log-line .data {
  color: #94a3b8;
  white-space: pre-wrap;
  word-break: break-all;
  padding-left: 96px;
}
.empty {
  color: #475569;
}
</style>
