import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5174,
    strictPort: true,
    proxy: { '/api': 'http://127.0.0.1:8001' },
  },
  build: {
    outDir: '../backend/frontend_build',  // Django serves the site from here
    emptyOutDir: true,
  },
})