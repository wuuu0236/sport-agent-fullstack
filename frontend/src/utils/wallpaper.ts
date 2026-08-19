// 壁纸预设与存储键（ThemeSettings 与 ChatView 共用，单一数据源）
export interface WallpaperPreset {
  id: string
  name: string
  css: string
}

export const WALLPAPER_KEY = 'sport-wallpaper'

export const WALLPAPER_PRESETS: WallpaperPreset[] = [
  {
    id: 'ocean',
    name: '深蓝渐变',
    css: 'linear-gradient(160deg, #0b1526 0%, #12203a 45%, #1b3a5c 100%)',
  },
  {
    id: 'violet',
    name: '暮紫渐变',
    css: 'linear-gradient(160deg, #150f26 0%, #261b3f 50%, #3b2d5e 100%)',
  },
  {
    id: 'forest',
    name: '墨绿渐变',
    css: 'linear-gradient(160deg, #0c1613 0%, #14231d 50%, #1d352a 100%)',
  },
  {
    id: 'ember',
    name: '暖橙渐变',
    css: 'linear-gradient(160deg, #170f0c 0%, #2a1a10 50%, #4a2c14 100%)',
  },
]

// 预设 id -> 'preset:<id>' 存储值 -> CSS 背景
export function presetToStored(p: WallpaperPreset): string {
  return 'preset:' + p.id
}

export function resolveWallpaperBackground(stored: string | null): Record<string, string> {
  if (!stored) return {}
  if (stored.startsWith('preset:')) {
    const p = WALLPAPER_PRESETS.find((x) => presetToStored(x) === stored)
    return p ? { background: p.css } : {}
  }
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
