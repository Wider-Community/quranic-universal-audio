/**
 * Submit-recitation intake API client.
 *
 * Posts a new-combination / new-reciter contribution (direct links or a
 * playlist) to ``POST /api/requests/intake`` (any signed-in user). The backend
 * structurally validates; blocking failures return 400 with ``{errors,
 * warnings}``. See ``inspector/routes/claims/requests.py`` + ``services/admin/
 * intake.py``.
 */

import type { IntakeSubmission } from '../types/generated/schemas';

export interface IntakeResult {
    ok: boolean;
    id?: string;
    /** Advisory (missing chapters, dupes, unrecognised host). Non-blocking. */
    warnings: string[];
    /** Blocking validation errors (present only on failure). */
    errors?: string[];
}

export async function submitIntake(payload: IntakeSubmission): Promise<IntakeResult> {
    const res = await fetch('/api/requests/intake', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
    });
    const body = await res.json().catch(() => ({}) as Record<string, unknown>);
    if (!res.ok) {
        return {
            ok: false,
            errors: (body.errors as string[]) ?? [
                (body.error as string) ?? `HTTP ${res.status}`,
            ],
            warnings: (body.warnings as string[]) ?? [],
        };
    }
    return {
        ok: true,
        id: body.id as string | undefined,
        warnings: (body.warnings as string[]) ?? [],
    };
}
