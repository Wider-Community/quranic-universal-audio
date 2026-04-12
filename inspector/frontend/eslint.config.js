import js from '@eslint/js';
import tseslint from 'typescript-eslint';
import prettier from 'eslint-config-prettier';

export default [
    { ignores: ['dist/**', 'node_modules/**', '.vite/**'] },
    js.configs.recommended,
    ...tseslint.configs.recommended,
    prettier,
    {
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
        },
    },
];
