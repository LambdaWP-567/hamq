import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    port: 3000,
    proxy: {
      // Proxy REST API calls to the backend during development
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
      // Proxy WebSocket connections to the backend during development
      '/ws': {
        target: 'ws://localhost:8000',
        ws: true,
        changeOrigin: true,
      },
    },
  },
  build: {
    // Output directory: the backend's static/ folder so the multi-stage
    // Docker build can COPY the files into the Python image.
    outDir: '../backend/static',
    // Clear the output directory before each build to avoid stale files
    emptyOutDir: true,
  },
})
