/**
 * Safe localStorage restore helper.
 *
 * Wraps localStorage.getItem with a user-supplied parser, guarding against
 * missing keys, null returns, and parser exceptions. Returns undefined on any
 * failure, letting callers fall back to a default without try/catch noise.
 */

/**
 * Read a localStorage entry and parse it.
 *
 * @param key    - localStorage key to read
 * @param parser - pure function that converts the raw string to T
 * @returns parsed value, or undefined if the key is absent or parsing throws
 */
export function lsRestore<T>(key: string, parser: (s: string) => T): T | undefined {
    try {
        const raw = localStorage.getItem(key);
        if (raw === null) return undefined;
        return parser(raw);
    } catch {
        return undefined;
    }
}
