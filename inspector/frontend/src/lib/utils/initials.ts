/**
 * Two-character initials for an avatar, derived from an HF login.
 *
 * Strips non-alphanumerics, takes the first two characters uppercased; falls
 * back to the raw first two characters when the login is all-symbol, and to
 * ``?`` when there's nothing usable. Shared by the Reviews-tab reviewer cell
 * and the combination-picker review-status chip so both render identically.
 */
export function initials(login: string | null | undefined): string {
    if (!login) return '?';
    const trimmed = login.trim();
    if (!trimmed) return '?';
    const chars = trimmed.replace(/[^a-z0-9]/gi, '').slice(0, 2).toUpperCase();
    return chars || trimmed.slice(0, 2).toUpperCase();
}
