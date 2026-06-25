import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import { svelte } from '@sveltejs/vite-plugin-svelte';
import { defineConfig } from 'vite';

const here = fileURLToPath(new URL('.', import.meta.url));

// Two-stack mode: run a second parallel dev stack by overriding these:
//   INSPECTOR_VITE_PORT     — dev server port (default 5173)
//   INSPECTOR_BACKEND_PORT  — Flask port the proxy points at (default 5000)
//   INSPECTOR_BACKEND_HOST  — Flask host (default 127.0.0.1). Override when the
//     dev server runs in WSL2 but the backend runs on Windows: WSL2 NAT can't
//     reach Windows via 127.0.0.1, so pass the host gateway IP
//     (`ip route show default | grep -oP 'via \K[0-9.]+'`).
// e.g. `INSPECTOR_VITE_PORT=5174 INSPECTOR_BACKEND_PORT=5001 npm run dev`
const VITE_PORT = Number(process.env.INSPECTOR_VITE_PORT) || 5173;
const BACKEND_PORT = Number(process.env.INSPECTOR_BACKEND_PORT) || 5000;
const BACKEND_HOST = process.env.INSPECTOR_BACKEND_HOST || '127.0.0.1';
const BACKEND_TARGET = `http://${BACKEND_HOST}:${BACKEND_PORT}`;
// Render-harness / inspection mode: point the `/api` proxy at a remote origin
// (e.g. the dev Space) so the analysis-render harness can fetch shards without a
// local Flask. `INSPECTOR_API_TARGET=https://hetchyy-quranic-inspector-dev.hf.space`.
const API_TARGET = process.env.INSPECTOR_API_TARGET || BACKEND_TARGET;
const API_REMOTE = Boolean(process.env.INSPECTOR_API_TARGET);

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
      '/api': { target: API_TARGET, changeOrigin: API_REMOTE, secure: true },
      '/audio': { target: API_TARGET, changeOrigin: API_REMOTE, secure: true },
    },
  },
}));
