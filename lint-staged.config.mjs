import { spawnSync } from 'node:child_process';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.dirname(fileURLToPath(import.meta.url));
const frontendRoot = path.join(root, 'inspector', 'frontend');
const eslintBin = path.join(frontendRoot, 'node_modules', 'eslint', 'bin', 'eslint.js');
const eslintConfig = path.join(frontendRoot, 'eslint.config.js');

/**
 * Resolve how to invoke ruff on this machine, probed once at config load.
 * Interpreter names vary (`python` vs `python3` vs the Windows `py` launcher)
 * and ruff may instead be on PATH as the bare console script (as in CI), so we
 * try each and keep the first that actually runs. Returns the command prefix
 * (e.g. `"python -m ruff"`) or null when ruff is unavailable.
 */
function resolveRuff() {
    const candidates = [
        ['python', '-m', 'ruff'],
        ['python3', '-m', 'ruff'],
        ['py', '-m', 'ruff'],
        ['ruff'],
    ];
    for (const c of candidates) {
        const res = spawnSync(c[0], [...c.slice(1), '--version'], { stdio: 'ignore' });
        if (res.status === 0) return c.join(' ');
    }
    return null;
}

const ruffCmd = resolveRuff();

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
    // Python: ruff lint-autofix + format, mirroring the backend-checks CI job.
    // The set of linted vs excluded paths is owned entirely by ruff.toml (its
    // target dirs + extend-exclude) — NOT re-listed here. `--force-exclude`
    // makes ruff apply those excludes to explicitly-passed files, so a new
    // top-level package is covered automatically and an excluded tree
    // (inspector/frontend, .local, the embedded repos) is skipped with no
    // second list to drift.
    '**/*.py': (filenames) => {
        if (!ruffCmd) {
            console.warn(
                '[lint-staged] ruff not found (tried python/python3/py -m ruff and bare ruff); ' +
                    'skipping Python lint/format. Install ruff to enable the pre-commit check.',
            );
            return [];
        }
        const files = filenames.join(' ');
        return [
            `${ruffCmd} check --fix --force-exclude ${files}`,
            `${ruffCmd} format --force-exclude ${files}`,
        ];
    },
};
