/// <reference types="vite/client" />

// @Author: RebeccaZhou
// @Description: Vite and Vue SFC ambient type declarations
//              Vite 与 Vue SFC 环境类型声明
declare module '*.vue' {
  import type { DefineComponent } from 'vue'
  const component: DefineComponent<{}, {}, any>
  export default component
}
