import js from '@eslint/js';
import prettier from 'eslint-config-prettier';
import importPlugin from 'eslint-plugin-import';
import simpleImportSort from 'eslint-plugin-simple-import-sort';
import sveltePlugin from 'eslint-plugin-svelte';
import tseslint from 'typescript-eslint';

export default [
    {
        ignores: [
            'dist/**',
            'node_modules/**',
            '.vite/**',
            // Codegen output owned by `inspector/scripts/regen_fe_types.py`.
            // `lint --fix` was stripping the file's `eslint-disable` header as
            // "unused", which then made `schema-codegen-check` fail on every
            // push that ran autofix. Treat the dir as off-limits to ESLint.
            'src/lib/types/generated/**',
        ],
    },
    js.configs.recommended,
    ...tseslint.configs.recommended,
    prettier,
    {
        plugins: {
            'simple-import-sort': simpleImportSort,
            'import': importPlugin,
        },
        settings: {
            // `import/no-cycle` silently reports zero findings without BOTH
            // the TS resolver AND the `import/parsers` map.
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
            '@typescript-eslint/no-explicit-any': 'off',
            '@typescript-eslint/no-unused-vars': ['warn', {
                argsIgnorePattern: '^_',
                varsIgnorePattern: '^_',
                caughtErrorsIgnorePattern: '^_',
                destructuredArrayIgnorePattern: '^_',
            }],
            '@typescript-eslint/ban-ts-comment': 'warn',
            'no-unused-vars': 'off',
            'simple-import-sort/imports': 'off',
            '@typescript-eslint/consistent-type-imports': ['error', {
                prefer: 'type-imports',
                fixStyle: 'separate-type-imports',
            }],
            'import/no-cycle': 'error',
        },
    },
    ...sveltePlugin.configs['flat/recommended'],
    {
        files: ['**/*.svelte'],
        languageOptions: {
            parserOptions: {
                parser: tseslint.parser,
            },
        },
        rules: {
            // Wiring parserOptions.project on .svelte breaks other rules; keep type-imports for .ts only.
            '@typescript-eslint/consistent-type-imports': 'off',
            // Reactive `$:` blocks are expression statements; the TS rule flags them.
            '@typescript-eslint/no-unused-expressions': 'off',
            // The TS variant crashes on Svelte AST; the core rule is safe.
            '@typescript-eslint/no-unused-vars': 'off',
            'no-unused-vars': ['warn', {
                argsIgnorePattern: '^_',
                varsIgnorePattern: '^_',
                caughtErrorsIgnorePattern: '^_',
                destructuredArrayIgnorePattern: '^_',
            }],
            // TS resolves symbols; the core rule false-positives on DOM globals.
            'no-undef': 'off',
            // Svelte's synthetic imports confuse the cycle detector.
            'import/no-cycle': 'off',
        },
    },
];
