/**
 * Spawn ESLint from inspector/frontend without shell `cd` (Windows cmd fails on
 * `cd inspector/frontend && …` in some lint-staged / husky contexts).
 */
import { spawnSync } from 'node:child_process';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const frontendRoot = path.join(root, 'inspector', 'frontend');
const eslintBin = path.join(frontendRoot, 'node_modules', 'eslint', 'bin', 'eslint.js');

const files = process.argv.slice(2);
if (files.length === 0) {
  process.exit(0);
}

const result = spawnSync(process.execPath, [eslintBin, '--fix', ...files], {
  cwd: frontendRoot,
  stdio: 'inherit',
  shell: false,
});

process.exit(result.status === null ? 1 : result.status);
