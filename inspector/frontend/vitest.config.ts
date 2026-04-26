import { svelte } from '@sveltejs/vite-plugin-svelte';
import { defineConfig } from 'vitest/config';
import { fileURLToPath } from 'node:url';

const here = fileURLToPath(new URL('.', import.meta.url));

export default defineConfig({
  root: here,
  plugins: [svelte({ hot: false })],
  test: {
    environment: 'happy-dom',
    globals: true,
    include: ['src/**/*.{test,spec}.ts'],
  },
  resolve: {
    // Ensure Svelte's browser condition wins so component tests pick up
    // client-side exports (SSR exports would skip the DOM effects).
    conditions: ['browser'],
  },
});
