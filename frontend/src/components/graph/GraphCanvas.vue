<template>
  <div ref="containerRef" class="graph-canvas" />
</template>

<script setup lang="ts">
// @Author: RebeccaZhou
// @Description: Knowledge graph canvas component
//              知识图谱画布组件
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { DataSet } from 'vis-data'
import { Network } from 'vis-network'
import type { GraphEdgeDTO, GraphNodeDTO } from '@/api/client'

const props = defineProps<{ nodes: GraphNodeDTO[]; edges: GraphEdgeDTO[] }>()
const containerRef = ref<HTMLElement>()
let network: Network | null = null

const LABEL_COLORS: Record<string, string> = {
  Model: '#2563eb',
  Filter: '#16a34a',
  Fault: '#dc2626',
  Cause: '#f59e0b',
  Solution: '#7c3aed',
  Customer: '#0891b2',
  Order: '#64748b',
  Batch: '#db2777',
}

function render() {
  if (!containerRef.value) return
  const dsNodes = new DataSet(
    props.nodes.map((n) => ({
      id: n.id,
      label: n.title || n.label,
      title: `${n.label}\n${JSON.stringify(n.properties, null, 2)}`,
      color: { background: LABEL_COLORS[n.label] || '#94a3b8', font: { color: '#fff' } },
      shape: 'dot',
      size: 16,
      font: { color: '#1f2937', size: 13 },
    })),
  )
  const dsEdges = new DataSet(
    props.edges.map((e, i) => ({
      id: `e${i}`,
      from: e.source,
      to: e.target,
      label: e.type,
      arrows: 'to',
      font: { size: 9, color: '#64748b', strokeWidth: 0 },
      color: { color: '#cbd5e1' },
    })),
  )
  network = new Network(
    containerRef.value,
    { nodes: dsNodes, edges: dsEdges },
    {
      interaction: { hover: true, tooltipDelay: 100 },
      physics: { stabilization: { iterations: 120 }, barnesHut: { gravitationalConstant: -6000 } },
      nodes: { shapeProperties: { borderRadius: 6 } },
    },
  )
}

onMounted(render)
watch(
  () => [props.nodes.length, props.edges.length],
  () => render(),
)
onBeforeUnmount(() => network?.destroy())
</script>

<style scoped>
.graph-canvas {
  width: 100%;
  height: 100%;
  background: #fff;
  border-radius: 8px;
}
</style>
