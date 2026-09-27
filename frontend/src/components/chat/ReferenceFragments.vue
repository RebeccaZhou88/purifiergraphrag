<template>
  <div v-if="fragments.length" class="refs">
    <div class="ref-head">
      <el-icon><CollectionTag /></el-icon>
      <span>图谱引用片段（{{ fragments.length }}）</span>
    </div>
    <div class="ref-tags">
      <button
        v-for="f in fragments"
        :key="f.id"
        class="ref-tag"
        :class="{ active: activeId === f.id }"
        @click="toggle(f.id)"
      >
        {{ f.title }}
      </button>
    </div>
    <!-- 一次只展示被点击的那一条，其余隐藏 -->
    <transition name="fade">
      <div v-if="active" class="ref-body">
        <div class="ref-title">{{ active.title }}</div>
        <pre>{{ fmt(active.content) }}</pre>
      </div>
    </transition>
  </div>
</template>

<script setup lang="ts">
// @Author: RebeccaZhou
// @Description: Collapsible reference fragments component
//              参考片段折叠展示组件
import { computed, ref } from 'vue'
import type { Fragment } from '@/stores/chat'

const props = defineProps<{ fragments: Fragment[] }>()
const activeId = ref<string | null>(null) // 默认全部折叠

const active = computed(() => props.fragments.find((f) => f.id === activeId.value) || null)

function toggle(id: string) {
  // 再次点击同一条则收起
  activeId.value = activeId.value === id ? null : id
}

function fmt(c: unknown) {
  if (typeof c === 'string') return c
  try {
    return JSON.stringify(c, null, 2)
  } catch {
    return String(c)
  }
}
</script>

<style scoped>
.refs {
  margin-top: 10px;
  border: 1px solid var(--pg-border);
  border-radius: 8px;
  overflow: hidden;
}
.ref-head {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 10px;
  font-size: 12px;
  color: var(--pg-muted);
  background: #f8fafc;
  border-bottom: 1px solid var(--pg-border);
}
.ref-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  padding: 8px 10px;
}
.ref-tag {
  border: 1px solid #c7d2fe;
  background: #eef2ff;
  color: #4338ca;
  border-radius: 999px;
  padding: 3px 12px;
  font-size: 12px;
  cursor: pointer;
  transition: all 0.15s;
}
.ref-tag:hover {
  background: #e0e7ff;
}
.ref-tag.active {
  background: var(--pg-primary);
  border-color: var(--pg-primary);
  color: #fff;
}
.ref-body {
  border-top: 1px solid var(--pg-border);
  padding: 8px 10px;
}
.ref-title {
  font-size: 12px;
  font-weight: 600;
  color: var(--pg-text);
  margin-bottom: 4px;
}
.ref-body pre {
  margin: 0;
  max-height: 220px;
  overflow: auto;
  background: #0f172a;
  color: #a7f3d0;
  border-radius: 6px;
  padding: 8px 10px;
  font-size: 12px;
  white-space: pre-wrap;
  word-break: break-word;
}
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.15s;
}
.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}
</style>
