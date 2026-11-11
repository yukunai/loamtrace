import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// 前端通过 /api 反向代理到本地 FastAPI sidecar（计划书 §5.3）。
// 后端默认 127.0.0.1:8000，可用 VITE_API_TARGET 覆盖。
export default defineConfig(({ mode }) => ({
  plugins: [react()],
  base: './',
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: process.env.VITE_API_TARGET || 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
}))
