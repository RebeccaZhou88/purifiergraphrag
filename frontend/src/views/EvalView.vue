<template>
  <div class="page eval-page">
    <div class="panel toolbar">
      <el-select v-model="store.selectedModel" size="small" style="width: 200px" :disabled="store.running">
        <el-option v-for="m in store.models" :key="m.id" :label="m.name" :value="m.id" />
      </el-select>
      <el-select v-model="store.scenario" size="small" style="width: 160px" :disabled="store.running" clearable
        placeholder="全部场景">
        <el-option label="滤芯兼容" value="filter_compatibility" />
        <el-option label="故障排查" value="fault_diagnosis" />
        <el-option label="批次召回" value="batch_recall" />
      </el-select>
      <el-button type="primary" size="small" :loading="store.running" :icon="VideoPlay" @click="store.run()">
        {{ store.running ? '评估中…' : '运行评估' }}
      </el-button>
      <el-progress v-if="store.running || store.results.length" :percentage="progress" class="prog" />
    </div>

    <div class="metrics">
      <el-card shadow="never" class="metric-card">
        <div class="m-label">多跳准确率</div>
        <div class="m-value" :class="accOk ? 'good' : 'bad'">
          {{ ((store.summary?.accuracy ?? 0) * 100).toFixed(1) }}%
        </div>
        <div class="m-sub">目标 ≥ 85%</div>
      </el-card>
      <el-card shadow="never" class="metric-card">
        <div class="m-label">P95 响应时间</div>
        <div class="m-value" :class="p95Ok ? 'good' : 'bad'">{{ store.summary?.p95_ms ?? 0 }} ms</div>
        <div class="m-sub">目标 &lt; 2000 ms</div>
      </el-card>
      <el-card shadow="never" class="metric-card">
        <div class="m-label">通过 / 总数</div>
        <div class="m-value">{{ store.summary?.passed ?? 0 }} / {{ store.summary?.total ?? 0 }}</div>
        <div class="m-sub">{{ store.caseTotal || '—' }} 条用例 · {{ store.scenarioCount || '—' }} 类场景</div>
      </el-card>
    </div>

    <div class="panel table-wrap">
      <el-table :data="store.rankedResults" size="small" stripe height="100%">
        <el-table-column prop="rank" label="排名" width="70" sortable :sort-by="'rank'" />
        <el-table-column prop="case_id" label="用例" width="90" />
        <el-table-column label="场景" width="110">
          <template #default="{ row }">
            <el-tag size="small" :type="scenarioType(row.scenario)">{{ scenarioName(row.scenario) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="question" label="问题" min-width="220" show-overflow-tooltip />
        <el-table-column label="结果" width="80">
          <template #default="{ row }">
            <el-tag size="small" :type="row.passed ? 'success' : 'danger'">
              {{ row.passed ? '通过' : '未过' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="latency_ms" label="耗时(ms)" width="100" sortable :sort-by="'latency_ms'" />
        <el-table-column type="expand">
          <template #default="{ row }">
            <div class="detail">
              <div><b>期望关键词：</b>{{ row.expected_keywords.join('、') }}</div>
              <div class="ans"><b>模型回答：</b>{{ row.answer || '（空）' }}</div>
            </div>
          </template>
        </el-table-column>
      </el-table>
    </div>
  </div>
</template>

<script setup lang="ts">
// @Author: RebeccaZhou
// @Description: Evaluation panel view
//              评估面板视图
import { computed, onMounted } from 'vue'
import { VideoPlay } from '@element-plus/icons-vue'
import { useEvalStore } from '@/stores/eval'

const store = useEvalStore()

onMounted(() => {
  store.loadModels()
  store.loadCases()
})

const progress = computed(() =>
  store.summary ? 100
    : store.caseTotal ? Math.min(99, Math.round((store.results.length / store.caseTotal) * 100))
    : 0,
)
const accOk = computed(() => (store.summary?.accuracy ?? 0) >= 0.85)
const p95Ok = computed(() => (store.summary?.p95_ms ?? 0) < 2000 && (store.summary?.p95_ms ?? 0) > 0)

function scenarioName(s: string) {
  return { filter_compatibility: '滤芯兼容', fault_diagnosis: '故障排查', batch_recall: '批次召回' }[s] || s
}
function scenarioType(s: string): 'primary' | 'warning' | 'danger' {
  return ({ filter_compatibility: 'primary', fault_diagnosis: 'warning', batch_recall: 'danger' } as const)[
    s as 'filter_compatibility' | 'fault_diagnosis' | 'batch_recall'
  ] || 'primary'
}
</script>

<style scoped>
.eval-page {
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
  gap: 10px;
}
.prog {
  flex: 1;
  max-width: 300px;
}
.metrics {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 12px;
}
.metric-card :deep(.el-card__body) {
  padding: 14px 18px;
}
.m-label {
  font-size: 13px;
  color: var(--pg-muted);
}
.m-value {
  font-size: 28px;
  font-weight: 700;
  margin: 4px 0;
}
.m-value.good {
  color: #16a34a;
}
.m-value.bad {
  color: #dc2626;
}
.m-sub {
  font-size: 12px;
  color: var(--pg-muted);
}
.table-wrap {
  flex: 1;
  min-height: 320px;
  padding: 6px;
}
.detail {
  padding: 8px 16px;
  font-size: 13px;
  line-height: 1.8;
  color: #374151;
}
.detail .ans {
  white-space: pre-wrap;
  word-break: break-word;
}
</style>
