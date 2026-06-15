import { vitePreprocess } from '@sveltejs/vite-plugin-svelte';

export default {
    preprocess: vitePreprocess(),
    compilerOptions: {
        // This is an internal editor tool, not a public a11y-audited site.
        // Drop the compiler's a11y hints so they don't surface as svelte-check
        // warnings or clutter the dev console. Honoured by both svelte-check
        // and the vite/build compiler.
        warningFilter: (w) => !w.code.startsWith('a11y'),
    },
};
