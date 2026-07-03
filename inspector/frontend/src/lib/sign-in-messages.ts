/**
 * Centralized sign-in prompt copy, keyed by trigger (edit / claim / request /
 * save / claimExpired). The object-key contract is the lookup API consumed by
 * `openSignInModal` call sites; the literal strings are sourced from Paraglide
 * so the copy is localized.
 *
 * Each entry exposes `title`/`body` as getters that call the per-message
 * Paraglide functions at *access* time, so the modal snapshots the copy in the
 * current ambient locale when it opens. Strings live under `common_signin_*` in
 * `src/lib/i18n/messages/common/{en,ar}.json`.
 */
import { common_signin_claim_body } from '$lib/paraglide/messages/common_signin_claim_body';
import { common_signin_claim_expired_body } from '$lib/paraglide/messages/common_signin_claim_expired_body';
import { common_signin_claim_expired_title } from '$lib/paraglide/messages/common_signin_claim_expired_title';
import { common_signin_claim_title } from '$lib/paraglide/messages/common_signin_claim_title';
import { common_signin_edit_body } from '$lib/paraglide/messages/common_signin_edit_body';
import { common_signin_edit_title } from '$lib/paraglide/messages/common_signin_edit_title';
import { common_signin_request_body } from '$lib/paraglide/messages/common_signin_request_body';
import { common_signin_request_title } from '$lib/paraglide/messages/common_signin_request_title';
import { common_signin_save_body } from '$lib/paraglide/messages/common_signin_save_body';
import { common_signin_save_title } from '$lib/paraglide/messages/common_signin_save_title';

export interface SignInMessage {
    title: string;
    body: string;
}

export const SIGN_IN_MESSAGES = {
    /** Clicking any gated edit button (split, trim, merge, delete, etc.) while unauthenticated */
    edit: {
        get title() {
            return common_signin_edit_title();
        },
        get body() {
            return common_signin_edit_body();
        },
    },
    /** Clicking the Claim button while anonymous */
    claim: {
        get title() {
            return common_signin_claim_title();
        },
        get body() {
            return common_signin_claim_body();
        },
    },
    /** Clicking "Request" on reciter detail while anonymous */
    request: {
        get title() {
            return common_signin_request_title();
        },
        get body() {
            return common_signin_request_body();
        },
    },
    /** Save returns 401 — session expired mid-edit */
    save: {
        get title() {
            return common_signin_save_title();
        },
        get body() {
            return common_signin_save_body();
        },
    },
    /** Claim API returns 401 — session expired */
    claimExpired: {
        get title() {
            return common_signin_claim_expired_title();
        },
        get body() {
            return common_signin_claim_expired_body();
        },
    },
} satisfies Record<string, SignInMessage>;
