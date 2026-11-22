import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
const t = { target: 'http://127.0.0.1:8000', changeOrigin: true }
export default defineConfig({ plugins: [react()], test: { environment: 'jsdom', testTimeout: 90000 }, server: { port: 5173, proxy: { '/api': t, '/media': t } } })
