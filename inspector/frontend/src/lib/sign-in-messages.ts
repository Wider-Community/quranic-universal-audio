export interface SignInMessage {
    title: string;
    body: string;
}

export const SIGN_IN_MESSAGES = {
    /** Clicking any gated edit button (split, trim, merge, delete, etc.) while unauthenticated */
    edit: {
        title: 'Sign in to edit',
        body: 'Editing segments requires a Hugging Face account. Sign in to claim this reciter and start contributing.',
    },
    /** Clicking the Claim button while anonymous */
    claim: {
        title: 'Sign in to claim',
        body: 'Claiming a reciter requires a Hugging Face account. Sign in to start contributing.',
    },
    /** Clicking "Request" on reciter detail while anonymous */
    request: {
        title: 'Sign in to request',
        body: 'Submitting a recitation request requires a Hugging Face account.',
    },
    /** Save returns 401 — session expired mid-edit */
    save: {
        title: 'Session expired',
        body: 'Your session expired before changes could be saved. Sign in again to continue.',
    },
    /** Claim API returns 401 — session expired */
    claimExpired: {
        title: 'Sign in to continue',
        body: 'Your session expired. Sign in again to continue claiming reciters.',
    },
} satisfies Record<string, SignInMessage>;
