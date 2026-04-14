import js from '@eslint/js';
import tseslint from 'typescript-eslint';
import prettier from 'eslint-config-prettier';
import simpleImportSort from 'eslint-plugin-simple-import-sort';
import importPlugin from 'eslint-plugin-import';

export default [
    // TODO: wave 11 — enable svelte lint rules via eslint-plugin-svelte once all .svelte
    // components are stable. For now, ignore .svelte files to avoid import/no-cycle
    // false-positives from the Svelte template compiler's generated imports.
    { ignores: ['dist/**', 'node_modules/**', '.vite/**', '**/*.svelte'] },
    js.configs.recommended,
    ...tseslint.configs.recommended,
    prettier,
    {
        plugins: {
            'simple-import-sort': simpleImportSort,
            'import': importPlugin,
        },
        settings: {
            // eslint-plugin-import needs both a TS resolver (to follow
            // extensionless `./foo` → `./foo.ts`) AND an `import/parsers`
            // setting that maps `.ts` to `@typescript-eslint/parser` so the
            // plugin can parse the import graph. Without BOTH, the
            // `import/no-cycle` rule silently reports zero findings even
            // when cycles exist. The project-setup discovery happened
            // during Wave 1's Item 3 end-to-end verification.
            'import/resolver': {
                typescript: {
                    project: './tsconfig.json',
                },
                node: true,
            },
            'import/parsers': {
                '@typescript-eslint/parser': ['.ts', '.tsx'],
            },
        },
        rules: {
            // Stage 1 migration tolerance — tightened in Phase 7 cleanup.
            '@typescript-eslint/no-explicit-any': 'off',
            '@typescript-eslint/no-unused-vars': ['warn', {
                argsIgnorePattern: '^_',
                varsIgnorePattern: '^_',
                caughtErrorsIgnorePattern: '^_',
                destructuredArrayIgnorePattern: '^_',
            }],
            '@typescript-eslint/ban-ts-comment': 'warn',
            'no-unused-vars': 'off',
            // Import hygiene rules (added in post-Stage-1 cleanup pass).
            'simple-import-sort/imports': 'error',
            '@typescript-eslint/consistent-type-imports': ['error', {
                prefer: 'type-imports',
                fixStyle: 'separate-type-imports',
            }],
            // Downgraded to `warn` in Wave 1 of Stage 2 after enabling the
            // TS resolver surfaced ~22 pre-existing segments-tab cycles
            // (see stage2-bugs.md S2-B06). Those are the same runtime-safe
            // cycles the segments `register*` pattern was built to handle;
            // they dissolve in Waves 5-10 as the segments tab migrates to
            // Svelte. Wave 11 re-promotes this rule to `error` once zero
            // cycles remain (see stage2-decisions.md S2-D24).
            'import/no-cycle': 'warn',
        },
    },
];
