import js from '@eslint/js';
import tseslint from 'typescript-eslint';
import prettier from 'eslint-config-prettier';
import simpleImportSort from 'eslint-plugin-simple-import-sort';
import importPlugin from 'eslint-plugin-import';

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
            'import/no-cycle': 'error',
        },
    },
];
