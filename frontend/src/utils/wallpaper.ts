// 壁纸预设与存储键（ThemeSettings 与 AppWorkbench 共用，单一数据源）
export type ThemeMode = 'dark' | 'light'

export interface WallpaperPreset {
  id: string
  name: string
  /** 该壁纸适配的界面明暗：浅色壁纸配浅色令牌，否则面板与背景会打架 */
  theme: ThemeMode
  css: string
}

export const WALLPAPER_KEY = 'sport-wallpaper'
export const THEME_KEY = 'sport-theme'

export const WALLPAPER_PRESETS: WallpaperPreset[] = [
  /* ---------- 深色系：适合夜间 / 暗环境 ---------- */
  {
    id: 'ocean',
    name: '深蓝渐变',
    theme: 'dark',
    css: 'linear-gradient(160deg, #0b1526 0%, #12203a 45%, #1b3a5c 100%)',
  },
  {
    id: 'violet',
    name: '暮紫渐变',
    theme: 'dark',
    css: 'linear-gradient(160deg, #150f26 0%, #261b3f 50%, #3b2d5e 100%)',
  },
  {
    id: 'forest',
    name: '墨绿渐变',
    theme: 'dark',
    css: 'linear-gradient(160deg, #0c1613 0%, #14231d 50%, #1d352a 100%)',
  },
  {
    id: 'ember',
    name: '暖橙渐变',
    theme: 'dark',
    css: 'linear-gradient(160deg, #170f0c 0%, #2a1a10 50%, #4a2c14 100%)',
  },

  /* ---------- 灰白系：白天 / 强光下长时间阅读更省眼 ---------- */
  {
    id: 'cloud',
    name: '云白',
    theme: 'light',
    css: 'linear-gradient(160deg, #ffffff 0%, #f4f6fa 46%, #e6ecf4 100%)',
  },
  {
    id: 'mist',
    name: '雾灰',
    theme: 'light',
    css: 'linear-gradient(160deg, #f7f8fa 0%, #ebedf2 48%, #dadee6 100%)',
  },
  {
    id: 'linen',
    name: '米白',
    theme: 'light',
    css: 'linear-gradient(160deg, #fbfaf6 0%, #f3efe6 50%, #e5ded0 100%)',
  },
  {
    id: 'graphite',
    name: '石墨',
    theme: 'light',
    css: 'linear-gradient(160deg, #eef0f4 0%, #dfe3ea 48%, #c7cdd7 100%)',
  },
]

export const DARK_PRESETS = WALLPAPER_PRESETS.filter((p) => p.theme === 'dark')
export const LIGHT_PRESETS = WALLPAPER_PRESETS.filter((p) => p.theme === 'light')

// 预设 id -> 'preset:<id>' 存储值 -> CSS 背景
export function presetToStored(p: WallpaperPreset): string {
  return 'preset:' + p.id
}

/** 存储值 -> 预设对象（自定义图片或空值返回 null） */
export function presetOf(stored: string | null | undefined): WallpaperPreset | null {
  if (!stored || !stored.startsWith('preset:')) return null
  return WALLPAPER_PRESETS.find((x) => presetToStored(x) === stored) ?? null
}

/** 壁纸自带的明暗倾向；自定义图片无法判断，回落到深色（面板对比更稳） */
export function themeOfWallpaper(stored: string | null | undefined): ThemeMode {
  return presetOf(stored)?.theme ?? 'dark'
}

export function resolveWallpaperBackground(stored: string | null): Record<string, string> {
  if (!stored) return {}
  const p = presetOf(stored)
  if (p) return { background: p.css }
  // 自定义上传图片（base64 DataURL）
  return {
    backgroundImage: `url(${stored})`,
    backgroundSize: 'cover',
    backgroundPosition: 'center',
    backgroundAttachment: 'fixed',
  }
}

export function loadWallpaper(): string | null {
  try {
    return localStorage.getItem(WALLPAPER_KEY)
  } catch {
    return null
  }
}

export function saveWallpaper(stored: string | null): void {
  try {
    if (stored) {
      localStorage.setItem(WALLPAPER_KEY, stored)
    } else {
      localStorage.removeItem(WALLPAPER_KEY)
    }
  } catch {
    /* localStorage 已满等场景忽略 */
  }
}

/** 读取显式保存的明暗偏好；从未手动设置过时返回 null（表示跟随壁纸） */
export function loadTheme(): ThemeMode | null {
  try {
    const t = localStorage.getItem(THEME_KEY)
    return t === 'light' || t === 'dark' ? t : null
  } catch {
    return null
  }
}

export function saveTheme(theme: ThemeMode): void {
  try {
    localStorage.setItem(THEME_KEY, theme)
  } catch {
    /* 忽略 */
  }
}

/** 把明暗写到 <html> 上，令牌层用 :root[data-theme='light'] 接管 */
export function applyThemeToDocument(theme: ThemeMode): void {
  document.documentElement.dataset.theme = theme
  const meta = document.querySelector('meta[name="theme-color"]')
  if (meta) meta.setAttribute('content', theme === 'light' ? '#e8ecf2' : '#0d1015')
}
