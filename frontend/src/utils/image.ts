// 图片工具：把本地图片压缩为 base64 DataURL（用于聊天背景壁纸）
// localStorage 约 5MB 上限，原图（几 MB~几十 MB）直接转 base64 会超限，
// 这里用 canvas 缩到合理尺寸 + JPEG 压缩，一般几百 KB 以内。

const MAX_WIDTH = 1920
const JPEG_QUALITY = 0.8

export function fileToCompressedDataUrl(file: File, maxWidth = MAX_WIDTH, quality = JPEG_QUALITY): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onerror = () => reject(new Error('读取文件失败'))
    reader.onload = () => {
      const img = new Image()
      img.onerror = () => reject(new Error('图片解码失败'))
      img.onload = () => {
        // 等比缩放：宽度超限则按比例缩小，保持长宽比
        let { width, height } = img
        if (width > maxWidth) {
          height = Math.round((height * maxWidth) / width)
          width = maxWidth
        }
        const canvas = document.createElement('canvas')
        canvas.width = width
        canvas.height = height
        const ctx = canvas.getContext('2d')
        if (!ctx) {
          reject(new Error('Canvas 不可用'))
          return
        }
        ctx.drawImage(img, 0, 0, width, height)
        resolve(canvas.toDataURL('image/jpeg', quality))
      }
      img.src = reader.result as string
    }
    reader.readAsDataURL(file)
  })
}
