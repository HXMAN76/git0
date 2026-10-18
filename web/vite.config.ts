import path from 'node:path'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { defineConfig } from 'vitest/config'

// https://vite.dev/config/
// `vitest/config` re-exports Vite's defineConfig and types the `test` key.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: { '@': path.resolve(import.meta.dirname, './src') },
  },
  server: {
    // Dev only: the FastAPI backend runs on :8000; /api and /mcp are proxied so the
    // browser sees one origin (no CORS). SSE streams pass through the proxy.
    proxy: { '/api': 'http://localhost:8000', '/mcp': 'http://localhost:8000' },
  },
  build: {
    // Two pages: the existing app at /, and the relay IDE at /ide/ (dist/ide/index.html).
    rollupOptions: {
      input: {
        main: path.resolve(import.meta.dirname, 'index.html'),
        ide: path.resolve(import.meta.dirname, 'ide/index.html'),
      },
    },
  },
  test: {
    environment: 'jsdom',
  },
})
