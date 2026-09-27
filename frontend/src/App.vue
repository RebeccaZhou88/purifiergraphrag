<template>
  <div class="app-shell">
    <header class="app-header">
      <div class="brand">
        PurifierGraph
        <small>净水器售后知识图谱 GraphRAG 助手</small>
      </div>
      <el-menu mode="horizontal" :router="true" :default-active="$route.path" class="nav-menu">
        <el-menu-item index="/chat">
          <el-icon><ChatDotRound /></el-icon>
          <span>智能问答</span>
        </el-menu-item>
        <el-menu-item index="/graph">
          <el-icon><Share /></el-icon>
          <span>知识图谱</span>
        </el-menu-item>
        <el-menu-item index="/eval">
          <el-icon><DataAnalysis /></el-icon>
          <span>评估面板</span>
        </el-menu-item>
      </el-menu>
    </header>
    <main class="app-body">
      <router-view />
    </main>
  </div>
</template>

<script setup lang="ts">
// @Author: RebeccaZhou
// @Description: Root application component (navigation layout)
//              应用根组件（导航布局）
</script>

<style scoped>
.nav-menu {
  border-bottom: none !important;
  flex: 1;
}
.brand .el-icon {
  vertical-align: -2px;
}
</style>
