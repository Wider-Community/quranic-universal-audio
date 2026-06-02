/**
 * Accordion-guide read-tracking client.
 *
 * `POST /api/guides/viewed` records that the signed-in user has opened a guide.
 * The backend collapses the category to its stored view key and returns 204 (no
 * body) — so this uses raw `fetch`, not `fetchJson` (which assumes a JSON body).
 *
 * Pure boundary: the caller (in `tabs/segments`) owns the optimistic
 * `currentUser.guides_read` update so this stays free of tab imports. Returns
 * true on success; best-effort — a network/permission failure leaves the guide
 * unread (it just stays badged), never throwing into the modal's open path.
 */

/** Record `category` as read for the current user. Returns true on success. */
export async function recordGuideViewed(category: string): Promise<boolean> {
    try {
        const res = await fetch('/api/guides/viewed', {
            method: 'POST',
            credentials: 'same-origin',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ category }),
        });
        return res.ok;
    } catch {
        return false;
    }
}
