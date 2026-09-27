<template>
  <div class="page graph-page">
    <div class="panel toolbar">
      <div class="left">
        <el-select v-model="label" placeholder="全部实体" clearable size="small" style="width: 160px" @change="load">
          <el-option v-for="l in labels" :key="l" :label="l" :value="l" />
        </el-select>
        <el-button size="small" type="primary" :loading="loading" @click="load">加载图谱</el-button>
      </div>
      <div class="legend">
        <span v-for="l in labels" :key="l" class="legend-item">
          <i :style="{ background: colors[l] || '#94a3b8' }" />
          {{ l }}
        </span>
      </div>
    </div>

    <div class="panel canvas-wrap" v-loading="loading">
      <GraphCanvas v-if="nodes.length" :nodes="nodes" :edges="edges" />
      <el-empty v-else description="暂无数据，请确认后端与 Neo4j 已启动并已导入种子数据" />
    </div>

    <div class="panel schema">
      <div class="schema-title">关系 Schema（{{ relationships.length }}）</div>
      <div class="chips">
        <el-tag v-for="r in relationships" :key="r.type" size="small" effect="plain" class="chip">
          {{ r.source }} —{{ r.type }}→ {{ r.target }}
        </el-tag>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
// @Author: RebeccaZhou
// @Description: Knowledge graph view
//              知识图谱视图
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import GraphCanvas from '@/components/graph/GraphCanvas.vue'
import { fetchGraph, fetchSchema, type GraphEdgeDTO, type GraphNodeDTO } from '@/api/client'

const label = ref<string>('')
const labels = ref<string[]>([])
const relationships = ref<{ source: string; type: string; target: string; desc: string }[]>([])
const nodes = ref<GraphNodeDTO[]>([])
const edges = ref<GraphEdgeDTO[]>([])
const loading = ref(false)

const colors: Record<string, string> = {
  Model: '#2563eb',
  Filter: '#16a34a',
  Fault: '#dc2626',
  Cause: '#f59e0b',
  Solution: '#7c3aed',
  Customer: '#0891b2',
  Order: '#64748b',
  Batch: '#db2777',
}

async function load() {
  loading.value = true
  try {
    const g = await fetchGraph(label.value || undefined)
    nodes.value = g.nodes
    edges.value = g.edges
  } catch (e) {
    ElMessage.error(`加载图谱失败：${(e as Error).message}`)
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  try {
    const s = await fetchSchema()
    labels.value = s.nodes
    relationships.value = s.relationships
  } catch {
    labels.value = ['Model', 'Filter', 'Fault', 'Cause', 'Solution', 'Customer', 'Order', 'Batch']
  }
  await load()
})
</script>

<style scoped>
.graph-page {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.panel {
  background: #fff;
  border: 1px solid var(--pg-border);
  border-radius: 10px;
  padding: 10px 14px;
}
.toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.toolbar .left {
  display: flex;
  gap: 8px;
}
.legend {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
}
.legend-item {
  display: inline-flex;
  align-items: center;
  font-size: 12px;
  color: var(--pg-muted);
}
.legend-item i {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  display: inline-block;
  margin-right: 4px;
}
.canvas-wrap {
  flex: 1;
  min-height: 380px;
  padding: 0;
  position: relative;
  overflow: hidden;
}
.schema-title {
  font-size: 13px;
  font-weight: 600;
  margin-bottom: 8px;
}
.chips {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.chip {
  font-family: Consolas, monospace;
}
</style>
