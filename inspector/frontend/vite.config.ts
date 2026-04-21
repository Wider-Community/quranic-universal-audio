import { svelte } from '@sveltejs/vite-plugin-svelte';
import { defineConfig } from 'vite';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = fileURLToPath(new URL('.', import.meta.url));

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
    port: 5173,
    strictPort: true,
    proxy: {
      '/api': { target: 'http://127.0.0.1:5000', changeOrigin: false },
      '/audio': { target: 'http://127.0.0.1:5000', changeOrigin: false },
    },
  },
}));
