import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5174,
    strictPort: true,
    // Forward /api to Django so cookies (login session + CSRF) just work.
    proxy: { '/api': 'http://127.0.0.1:8001' },
  },
})
