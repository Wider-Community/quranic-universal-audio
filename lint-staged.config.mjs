import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.dirname(fileURLToPath(import.meta.url));
const frontendRoot = path.join(root, 'inspector', 'frontend');

/** @type {import('lint-staged').Configuration} */
export default {
    'inspector/frontend/**/*.{ts,js,svelte}': (filenames) => {
        // lint-staged runs each command's first token as a binary with NO shell,
        // so `cd … &&` is impossible. `npm --prefix` resolves on PATH and runs the
        // subpackage script with the frontend dir as cwd (local eslint on PATH).
        const rel = filenames
            .map((f) => path.relative(frontendRoot, path.isAbsolute(f) ? f : path.join(root, f)))
            .filter((r) => r && !r.startsWith('..'))
            .map((r) => r.split(path.sep).join('/'));
        if (rel.length === 0) return [];
        return `npm --prefix inspector/frontend run lint:fix -- ${rel.map((r) => `"${r}"`).join(' ')}`;
    },
};
