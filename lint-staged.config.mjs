import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.dirname(fileURLToPath(import.meta.url));
const frontendRoot = path.join(root, 'inspector', 'frontend');

/** @type {import('lint-staged').Configuration} */
export default {
  'inspector/frontend/**/*.{ts,js,svelte}': (filenames) => {
    if (filenames.length === 0) {
      return [];
    }
    const rel = filenames.map((f) => {
      const abs = path.isAbsolute(f) ? f : path.join(root, f);
      return path.relative(frontendRoot, abs);
    });
    const args = rel.map((r) => JSON.stringify(r)).join(' ');
    return `cd inspector/frontend && npx eslint --fix ${args}`;
  },
};
