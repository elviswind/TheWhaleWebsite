import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// When running `vite` on its own (port 5173), proxy /api calls to a locally
// running `vercel dev` (port 3000) so the Python function is reachable.
// If you just run `vercel dev`, it serves both the SPA and /api on one port
// and this proxy is harmless.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': 'http://localhost:3000',
    },
  },
})
