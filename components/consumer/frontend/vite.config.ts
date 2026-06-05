/// <reference types="vitest" />
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

/**
 * Vite configuration for the HAMq Consumer SPA.
 *
 * Dev server listens on port 3001.
 * API calls proxied to the backend running on port 8001 so CORS is not
 * needed during local development.
 * Production build output goes to ../backend/static so the Dockerfile
 * can copy it in one COPY instruction.
 */
export default defineConfig({
  plugins: [react()],

  server: {
    port: 3001,
    proxy: {
      // Proxy all /api and /metrics requests to the FastAPI backend.
      '/api': {
        target: 'http://localhost:8001',
        changeOrigin: true,
      },
      '/metrics': {
        target: 'http://localhost:8001',
        changeOrigin: true,
      },
      // WebSocket proxy for real-time status stream.
      '/ws': {
        target: 'ws://localhost:8001',
        ws: true,
        changeOrigin: true,
      },
    },
  },

  build: {
    // Outputs to backend/static — picked up by FastAPI StaticFiles and
    // copied into the Docker image by the multi-stage Dockerfile.
    outDir: '../backend/static',
    emptyOutDir: true,
  },

  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
  },
})
