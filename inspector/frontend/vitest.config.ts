import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import { svelte } from '@sveltejs/vite-plugin-svelte';
import { defineConfig } from 'vitest/config';

const here = fileURLToPath(new URL('.', import.meta.url));

export default defineConfig({
  root: here,
  plugins: [svelte({ hot: false })],
  test: {
    environment: 'happy-dom',
    globals: true,
    include: ['src/**/*.{test,spec}.ts'],
    setupFiles: ['./vitest.setup.ts'],
    coverage: {
      provider: 'v8',
      reporter: ['text', 'html', 'json'],
      reportsDirectory: './coverage',
      all: true,
      include: ['src/**/*.{ts,svelte}'],
      exclude: [
        'src/**/*.{test,spec}.ts',
        'src/**/__tests__/**',
        'src/lib/types/generated/**',
        'src/lib/paraglide/**',
        'src/**/*.d.ts',
        'vitest.setup.ts',
        '**/*.config.{ts,js,cjs,mjs}',
      ],
      thresholds: undefined,
    },
  },
  resolve: {
    alias: {
      '@fixtures': resolve(here, '../tests/fixtures/segments'),
      $lib: resolve(here, 'src/lib'),
    },
    conditions: ['browser'],
  },
});
