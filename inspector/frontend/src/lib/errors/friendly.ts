/**
 * Translates a backend error envelope into plain, user-facing copy.
 *
 * The backend returns `{ error, code?, context?, details? }`. `error` is
 * developer-grammar prose we must NOT show a user (it leaks internal state
 * tokens / capability IDs). Instead we map the stable `code` to friendly copy,
 * falling back to a status-based message, then a generic one. The raw
 * `body.error` is kept only for `console.error` / telemetry — never surfaced.
 *
 * Keep the codes here in lockstep with `services/errors.py::Codes`.
 */

export interface ApiErrorBody {
    error?: string;
    code?: string;
    context?: Record<string, unknown> | null;
    details?: Record<string, unknown> | null;
    // Claim-conflict (409) carries its own fields; handled by claims-client,
    // intentionally NOT mapped here.
    existing_claim?: string;
}

type CopyEntry = string | ((ctx: Record<string, unknown> | null | undefined) => string);

function stateLabel(ctx: Record<string, unknown> | null | undefined): string | null {
    const label = ctx?.state_label;
    return typeof label === 'string' && label ? label : null;
}

const CODE_COPY: Record<string, CopyEntry> = {
    // Auth / permission
    AUTH_REQUIRED: 'Please sign in to continue.',
    FORBIDDEN_CAPABILITY: "You don't have permission for this action.",
    NOT_AUTHORIZED: "You don't have permission for this action.",

    // Edit-lock gates
    NOT_EDITABLE_STATE: (ctx) => {
        const s = stateLabel(ctx);
        return s
            ? `This reciter isn't editable right now (it's ${s}).`
            : "This reciter isn't in an editable state right now.";
    },
    MARKED_READY_FROZEN:
        'This reciter is marked ready for publish and is locked. ' +
        'Choose “Continue editing” to make changes.',
    VISIBILITY_BLOCKED: "This reciter isn't available for editing.",
    NOT_CLAIM_HOLDER: 'You need an active claim on this reciter to edit it.',

    // State machine
    STATE_PRECONDITION: (ctx) => {
        const s = stateLabel(ctx);
        return s
            ? `That action isn't available while the reciter is ${s}.`
            : "That action isn't available from the reciter's current state.";
    },
    RELEASE_BLOCKED_MARKED_READY:
        'Unmark ready before releasing this reciter, or ask an admin to send it back.',
    REASON_REQUIRED: (ctx) => {
        const n = ctx?.min_chars;
        return typeof n === 'number'
            ? `Please provide a reason (at least ${n} characters).`
            : 'Please provide a reason.';
    },

    // Mark-ready family
    MARK_READY_CHECKLIST: 'Complete every checklist item before marking ready.',
    MARK_READY_BLOCKING_COUNTS:
        'Resolve the remaining blocking validation issues before marking ready.',
    MARK_READY_PAYLOAD: 'Your mark-ready submission was incomplete. Please review and resubmit.',
    MARK_READY_NO_SEGMENTS: "Can't mark ready — this reciter has no saved segments yet.",

    // Admin / structural
    LAST_OWNER: "You can't remove the last owner — promote another owner first.",
    UNKNOWN_RECITER: "That reciter couldn't be found.",

    // Storage
    READ_ONLY: "This instance is read-only; changes aren't saved.",
};

const STATUS_FALLBACK: Record<number, string> = {
    401: 'Please sign in to continue.',
    403: "You don't have permission for this action.",
    404: "That couldn't be found.",
    409: 'That action conflicts with the current state.',
    500: 'Something went wrong on our end. Please try again.',
};

/**
 * Friendly user-facing message for a failed API response.
 * Fallback chain: `code` → HTTP status → generic. Never returns `body.error`.
 */
export function friendlyError(body: ApiErrorBody | undefined, status: number): string {
    const code = body?.code;
    const entry = code ? CODE_COPY[code] : undefined;
    if (entry !== undefined) {
        return typeof entry === 'function' ? entry(body?.context) : entry;
    }
    return STATUS_FALLBACK[status] ?? 'Something went wrong. Please try again.';
}
