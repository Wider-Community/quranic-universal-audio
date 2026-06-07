import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.dirname(fileURLToPath(import.meta.url));
const frontendRoot = path.join(root, 'inspector', 'frontend');
const eslintBin = path.join(frontendRoot, 'node_modules', 'eslint', 'bin', 'eslint.js');
const eslintConfig = path.join(frontendRoot, 'eslint.config.js');

/** @type {import('lint-staged').Configuration} */
export default {
    'inspector/frontend/**/*.{ts,js,svelte}': (filenames) => {
        const abs = filenames
            .map((f) => (path.isAbsolute(f) ? f : path.join(root, f)))
            .filter((f) => {
                const rel = path.relative(frontendRoot, f);
                if (!rel || rel.startsWith('..')) return false;
                // Codegen output (scripts/codegen/regen_fe_types.py). eslint --fix
                // strips its `eslint-disable` banner, breaking schema-codegen-check.
                // eslint.config.js ignores this dir, but that pattern is
                // frontend-relative and lint-staged runs from the repo root, so the
                // ignore misses — enforce the skip here.
                const norm = rel.split(path.sep).join('/');
                return !norm.startsWith('src/lib/types/generated/');
            });
        if (abs.length === 0) return [];
        return `node ${eslintBin} --config ${eslintConfig} --fix ${abs.join(' ')}`;
    },
};
