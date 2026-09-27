<template>
  <div class="page chat-page">
    <div class="chat-main">
      <!-- 中间：消息 + 输入 -->
      <section class="chat-center panel">
        <MessageList :messages="chat.messages" @pick="onAsk" />

        <div class="input-panel">
          <!-- 输入区顶部：左侧模型选择，右上角操作按钮 -->
          <div class="input-bar">
            <el-select
              v-model="chat.selectedModel"
              size="small"
              class="model-select"
              :disabled="chat.loading"
            >
              <el-option v-for="m in chat.models" :key="m.id" :label="m.name" :value="m.id" />
            </el-select>

            <div class="bar-actions">
              <el-button size="small" :icon="Refresh" @click="onRefresh">刷新指标</el-button>
              <el-button size="small" type="danger" plain :icon="Delete" @click="onClear">
                清空对话
              </el-button>
            </div>
          </div>

          <div class="input-row">
            <el-input
              v-model="question"
              type="textarea"
              :rows="2"
              resize="none"
              placeholder="请输入售后问题，回车发送，Shift+回车换行"
              @keydown.enter.exact.prevent="onSend"
            />
            <el-button
              type="primary"
              class="send-btn"
              :loading="chat.loading"
              :icon="Promotion"
              @click="onSend"
            >
              发送
            </el-button>
          </div>
        </div>
      </section>

      <!-- 右侧：实时终端 -->
      <aside class="chat-terminal panel">
        <TerminalPanel :logs="chat.logs" />
      </aside>
    </div>
  </div>
</template>

<script setup lang="ts">
// @Author: RebeccaZhou
// @Description: Intelligent Q&A view
//              智能问答视图
import { onMounted, ref } from 'vue'
import { Delete, Promotion, Refresh } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { useChatStore } from '@/stores/chat'
import MessageList from '@/components/chat/MessageList.vue'
import TerminalPanel from '@/components/terminal/TerminalPanel.vue'

const chat = useChatStore()
const question = ref('')

onMounted(() => {
  chat.loadModels()
})

function onAsk(q: string) {
  if (!q || chat.loading) return
  chat.ask(q)
}

async function onSend() {
  const q = question.value
  if (!q.trim() || chat.loading) return
  question.value = ''
  await chat.ask(q)
}

function onClear() {
  chat.clearConversation()
  ElMessage.success('对话与日志已清空')
}

async function onRefresh() {
  await chat.refreshMetrics()
  ElMessage.success(`已刷新，当前模型：${chat.selectedModel}`)
}
</script>

<style scoped>
.chat-page {
  display: flex;
}
.chat-main {
  flex: 1;
  display: flex;
  gap: 12px;
  min-width: 0;
}
.panel {
  background: var(--pg-panel);
  border: 1px solid var(--pg-border);
  border-radius: 10px;
  overflow: hidden;
}
.chat-center {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
}
.chat-terminal {
  width: 400px;
  flex-shrink: 0;
  padding: 8px;
}
.input-panel {
  border-top: 1px solid var(--pg-border);
  padding: 10px 14px;
  background: #fbfdff;
}
.input-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}
.model-select {
  width: 200px;
}
.bar-actions {
  display: flex;
  gap: 8px;
  margin-left: auto;
}
.input-row {
  display: flex;
  gap: 10px;
  align-items: stretch;
}
.send-btn {
  align-self: stretch;
}
</style>
