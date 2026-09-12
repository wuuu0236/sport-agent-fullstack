// 子 Agent 目录：中文名 + 一句话职责 + 线性图标
// 用途：多 Agent 协作时间轴（ThinkingTrace）、消息气泡上的 agent 标识
// 与后端 AGENT_CATALOG 的 name 字段一一对应

const STROKE =
  'fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"'

const svg = (inner: string) => `<svg viewBox="0 0 24 24" ${STROKE}>${inner}</svg>`

export interface AgentMeta {
  label: string
  role: string
  icon: string
  hue: string
}

export const AGENTS: Record<string, AgentMeta> = {
  coach: {
    label: '教练 · 谭成义',
    role: '以铁馆老炮视角直接给训练建议',
    hue: '#ff7a45',
    icon: svg('<path d="M5 8.5c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2v7c0 1.1-.9 2-2 2H7c-1.1 0-2-.9-2-2z"/><path d="M6.5 6V5a1.5 1.5 0 0 1 1.5-1.5h8A1.5 1.5 0 0 1 17.5 5v1"/><path d="M9 13.5h6"/>'),
  },
  supervisor: {
    label: '主 Agent',
    role: '拆解任务、派发子 Agent、综合收口',
    hue: '#3d8bff',
    icon: svg('<path d="M12 3.5 20 9v6l-8 5.5-8-5.5V9z"/><path d="M12 12v8.5M12 12 20 9M12 12 4 9"/>'),
  },
  recorder: {
    label: '记录',
    role: '把训练数据解析入暂存区',
    hue: '#35d18a',
    icon: svg('<path d="M5 4.5h14v15H5z"/><path d="M8.5 9h7M8.5 12.5h7M8.5 16h4"/>'),
  },
  analyst: {
    label: '分析',
    role: '统计本地训练数据并给客观结论',
    hue: '#2ad4c8',
    icon: svg('<path d="M4 19V11M9.3 19V6M14.7 19v-5M20 19V9"/>'),
  },
  searcher: {
    label: '搜索',
    role: '检索最新训练方法与资料',
    hue: '#4ea1ff',
    icon: svg('<circle cx="11" cy="11" r="6"/><path d="M15.5 15.5 20 20"/>'),
  },
  planner: {
    label: '计划编排',
    role: '生成周期计划并综合各步产出',
    hue: '#8b7bff',
    icon: svg('<rect x="3.6" y="5" width="16.8" height="15.4" rx="2.4"/><path d="M3.6 10h16.8M8.2 3.4v3.2M15.8 3.4v3.2"/>'),
  },
  clinician: {
    label: '康复排查',
    role: '从运动医学角度排查伤痛风险',
    hue: '#ff5f56',
    icon: svg('<path d="M12 4.5v15M4.5 12h15"/>'),
  },
  expert: {
    label: '运动科学',
    role: '运动生理与营养专业视角',
    hue: '#f0b23c',
    icon: svg('<path d="M6 3.5h9l4 4v13H6z"/><path d="M14.5 3.5V8H19"/><path d="M9 12.5h6M9 16h4"/>'),
  },
  writer: {
    label: '润色',
    role: '把结果整理成易读成稿',
    hue: '#c08bff',
    icon: svg('<path d="M4.5 19.5 5.6 15 15.8 4.8a2 2 0 0 1 2.8 2.8L8.4 18.4z"/><path d="M14.2 6.4l3.4 3.4"/>'),
  },
  memory: {
    label: '记忆',
    role: '读写 USER / MEMORY 长期记忆',
    hue: '#a9b4c4',
    icon: svg('<path d="M12 3.5 13.9 9.3 19.6 11l-5.7 1.7L12 18.5l-1.9-5.8L4.4 11l5.7-1.7z"/>'),
  },
  scheduler: {
    label: '日程',
    role: '安排推送与训练提醒',
    hue: '#5ea3ff',
    icon: svg('<circle cx="12" cy="12" r="8"/><path d="M12 7.6V12l3 2"/>'),
  },
  reviewer: {
    label: '评审',
    role: '对产出做数据/安全/完整性校验',
    hue: '#f0b23c',
    icon: svg('<path d="M12 4.2 19 7v5.2c0 3.4-2.7 6.1-7 7.6-4.3-1.5-7-4.2-7-7.6V7z"/><path d="M9.2 12.2l2 2 3.6-3.8"/>'),
  },
  general: {
    label: '通用',
    role: '未命中专业角色时的兜底回答',
    hue: '#77839a',
    icon: svg('<circle cx="12" cy="12" r="8"/><path d="M12 9.2v.2M12 12v3.4"/>'),
  },
}

export function agentMeta(name?: string): AgentMeta {
  if (!name) return AGENTS.general
  return AGENTS[name] ?? { label: name, role: '', hue: '#77839a', icon: AGENTS.general.icon }
}
