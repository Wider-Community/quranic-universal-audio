import js from '@eslint/js';
import prettier from 'eslint-config-prettier';
import importPlugin from 'eslint-plugin-import';
import simpleImportSort from 'eslint-plugin-simple-import-sort';
import sveltePlugin from 'eslint-plugin-svelte';
import tseslint from 'typescript-eslint';

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
        languageOptions: {
            parserOptions: {
                // Parse <script lang="ts"> with the TS parser (required for type syntax).
                parser: tseslint.parser,
            },
        },
        rules: {
            // Type-aware @typescript-eslint rules need parserOptions.project; wiring project
            // on .svelte breaks other rules on Svelte's AST — keep this rule for .ts only.
            '@typescript-eslint/consistent-type-imports': 'off',
            // Reactive `$:` blocks use expression statements; TS rule flags them as unused.
            '@typescript-eslint/no-unused-expressions': 'off',
            // @typescript-eslint/no-unused-vars crashes on Svelte AST (Program:exit); use core rule.
            '@typescript-eslint/no-unused-vars': 'off',
            'no-unused-vars': ['warn', {
                argsIgnorePattern: '^_',
                varsIgnorePattern: '^_',
                caughtErrorsIgnorePattern: '^_',
                destructuredArrayIgnorePattern: '^_',
            }],
            // Typescript resolves symbols; core no-undef false-positives on DOM types etc.
            'no-undef': 'off',
            // Disable import/no-cycle for .svelte — the Svelte compiler generates
            // synthetic imports that confuse the cycle detector.
            'import/no-cycle': 'off',
        },
    },
];
