import { fileURLToPath, URL } from 'node:url'
import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vitest/config'

export default defineConfig({
  plugins: [vue()],
  resolve: { alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) } },
  server: { port: 5102, proxy: { '/api': { target: 'http://127.0.0.1:8002', changeOrigin: true, rewrite: path => path.replace(/^\/api/, '') } } },
  test: { environment: 'jsdom', exclude: ['e2e/**', 'node_modules/**', 'dist/**'] },
})
