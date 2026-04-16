import js from '@eslint/js';
import tseslint from 'typescript-eslint';
import prettier from 'eslint-config-prettier';
import simpleImportSort from 'eslint-plugin-simple-import-sort';
import importPlugin from 'eslint-plugin-import';
import sveltePlugin from 'eslint-plugin-svelte';

export default [
    { ignores: ['dist/**', 'node_modules/**', '.vite/**'] },
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
            // when cycles exist.
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
            // Migration tolerance — tightened in final cleanup pass.
            '@typescript-eslint/no-explicit-any': 'off',
            '@typescript-eslint/no-unused-vars': ['warn', {
                argsIgnorePattern: '^_',
                varsIgnorePattern: '^_',
                caughtErrorsIgnorePattern: '^_',
                destructuredArrayIgnorePattern: '^_',
            }],
            '@typescript-eslint/ban-ts-comment': 'warn',
            'no-unused-vars': 'off',
            // Import hygiene rules.
            'simple-import-sort/imports': 'error',
            '@typescript-eslint/consistent-type-imports': ['error', {
                prefer: 'type-imports',
                fixStyle: 'separate-type-imports',
            }],
            // All segments-tab cycles resolved. Ceiling is now 0; any new cycle breaks CI.
            'import/no-cycle': 'error',
        },
    },
    // Svelte-specific config — uses the flat/recommended preset from eslint-plugin-svelte.
    // Covers .svelte files only; TS rules above apply to .ts files.
    ...sveltePlugin.configs['flat/recommended'],
    {
        files: ['**/*.svelte'],
        rules: {
            // Disable import/no-cycle for .svelte — the Svelte compiler generates
            // synthetic imports that confuse the cycle detector.
            'import/no-cycle': 'off',
        },
    },
];
