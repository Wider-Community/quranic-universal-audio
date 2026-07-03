/**
 * Message-parity gate.
 *
 * Paraglide falls back to `baseLocale` for a missing translation, so a key that
 * exists in `en.json` but not `ar.json` compiles clean and silently renders
 * English — the library enforces message *syntax* and *call-site types*, never
 * key coverage. This test closes that gap: for every message file declared in
 * `project.inlang/settings.json`, each non-base locale must carry exactly the
 * same key set as the base locale (and every file must be valid JSON — a parse
 * throw fails the test). Derived from `settings.json`, so a newly-added area or
 * locale is covered automatically with no edit here.
 */
import { readFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import { describe, expect, it } from 'vitest';

const FRONTEND_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '../../../../');

interface InlangSettings {
    baseLocale: string;
    locales: string[];
    'plugin.inlang.messageFormat': { pathPattern: string[] };
}

const settings: InlangSettings = JSON.parse(
    readFileSync(join(FRONTEND_ROOT, 'project.inlang/settings.json'), 'utf8'),
);
const { baseLocale, locales } = settings;
const patterns = settings['plugin.inlang.messageFormat'].pathPattern;

/** Message ids in a locale file — `$schema` (and any `$`-prefixed metadata) excluded. */
function messageKeys(pattern: string, locale: string): Set<string> {
    const abs = join(FRONTEND_ROOT, pattern.replace('{locale}', locale));
    const parsed = JSON.parse(readFileSync(abs, 'utf8')) as Record<string, unknown>;
    return new Set(Object.keys(parsed).filter((k) => !k.startsWith('$')));
}

describe('i18n message parity', () => {
    for (const pattern of patterns) {
        const area = pattern.replace('./src/', '').replace('/{locale}.json', '');
        const baseKeys = messageKeys(pattern, baseLocale);

        for (const locale of locales) {
            if (locale === baseLocale) continue;
            it(`${area}: '${locale}' key set matches '${baseLocale}'`, () => {
                const keys = messageKeys(pattern, locale);
                const missing = [...baseKeys].filter((k) => !keys.has(k)).sort();
                const extra = [...keys].filter((k) => !baseKeys.has(k)).sort();
                expect({ missing, extra }).toEqual({ missing: [], extra: [] });
            });
        }
    }
});
