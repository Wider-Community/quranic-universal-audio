import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.dirname(fileURLToPath(import.meta.url));
const frontendRoot = path.join(root, 'inspector', 'frontend');

/** @type {import('lint-staged').Configuration} */
export default {
    'inspector/frontend/**/*.{ts,js,svelte}': (filenames) => {
        const rel = filenames
            .map((f) => path.relative(frontendRoot, path.isAbsolute(f) ? f : path.join(root, f)))
            .filter((r) => r && !r.startsWith('..'));
        if (rel.length === 0) return [];
        return `cd inspector/frontend && eslint --fix ${rel.map((r) => `'${r}'`).join(' ')}`;
    },
};
