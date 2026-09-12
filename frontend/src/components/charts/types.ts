// 图表共用类型（SFC 的 <script setup> 不能 export，故独立成文件）
export interface LinePoint {
  /** X 轴标签（如 MM-DD） */
  label: string
  /** 数值 */
  value: number
  /** 悬停提示里的补充说明（如完整日期） */
  sub?: string
}
