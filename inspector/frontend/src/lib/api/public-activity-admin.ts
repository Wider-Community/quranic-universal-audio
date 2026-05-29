/**
 * Public-activity owner-only admin actions.
 *
 * The admin notifications rail was retired; this module carries only the
 * remaining moderation surface — the owner-only DELETE that writes a global
 * tombstone for a public-feed card.
 *
 * Backed by ``DELETE /api/public/activity/<audit_id>`` — see
 * ``inspector/routes/admin/activity.py``.
 */

/** Tombstone a public-feed card so it disappears for everyone (owner-only;
 * reason ≥10 chars enforced server-side). */
export async function deletePublicActivity(
    auditId: string,
    reason: string,
): Promise<void> {
    const resp = await fetch(`/api/public/activity/${auditId}`, {
        method: 'DELETE',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ reason }),
    });
    if (!resp.ok) {
        const text = await resp.text();
        throw new Error(
            `DELETE /api/public/activity/${auditId} → HTTP ${resp.status}: ` +
                text.slice(0, 200),
        );
    }
}
