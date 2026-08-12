import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// 前端 dev server 在 5173，/api 代理到 Spring Boot(8080)，再由它调 Python agent-service(8001)
export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8080',
        changeOrigin: true,
      },
      // 只读的训练记录展示：直连 Python agent-service(8001) 的 /sessions，
      // 避免为展示型小功能重编译 Spring Boot 网关
      '/agent': {
        target: 'http://127.0.0.1:8001',
        changeOrigin: true,
        rewrite: (p) => p.replace(/^\/agent/, ''),
      },
    },
  },
})
