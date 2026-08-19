import MarkdownIt from 'markdown-it'

// Markdown 渲染：把 LLM 输出的 Markdown（#、**、表格、--- 等）渲染成富文本
// html:false 会转义原始 HTML，避免 LLM 输出里的标签造成 XSS
export const md = new MarkdownIt({ html: false, linkify: true, breaks: true })

export function renderMarkdown(text: string): string {
  if (!text) return ''
  try {
    return md.render(text)
  } catch {
    return text
  }
}
