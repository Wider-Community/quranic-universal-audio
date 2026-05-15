import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import { svelte } from '@sveltejs/vite-plugin-svelte';
import { defineConfig } from 'vite';

const here = fileURLToPath(new URL('.', import.meta.url));

// Two-stack mode: run a second parallel dev stack by overriding these:
//   INSPECTOR_VITE_PORT     — dev server port (default 5173)
//   INSPECTOR_BACKEND_PORT  — Flask port the proxy points at (default 5000)
// e.g. `INSPECTOR_VITE_PORT=5174 INSPECTOR_BACKEND_PORT=5001 npm run dev`
const VITE_PORT = Number(process.env.INSPECTOR_VITE_PORT) || 5173;
const BACKEND_PORT = Number(process.env.INSPECTOR_BACKEND_PORT) || 5000;
const BACKEND_TARGET = `http://127.0.0.1:${BACKEND_PORT}`;

export default defineConfig(({ mode }) => ({
  root: here,
  publicDir: 'public',
  plugins: [svelte()],
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    sourcemap: mode === 'development',
    target: 'es2022',
    rollupOptions: {
      input: resolve(here, 'index.html'),
      output: {
        manualChunks(id) {
          if (id.includes('chart.js') || id.includes('chartjs-plugin-annotation')) {
            return 'charts';
          }
        },
      },
    },
  },
  server: {
    port: VITE_PORT,
    strictPort: true,
    proxy: {
      '/api': { target: BACKEND_TARGET, changeOrigin: false },
      '/audio': { target: BACKEND_TARGET, changeOrigin: false },
    },
  },
}));
