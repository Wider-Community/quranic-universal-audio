/**
 * Which riwayat Universal Audio supports, and how their slugs map to the SDK.
 *
 * The backend owns this table (`qua_shared/riwayat.py`); the two slug unions
 * below are generated from it via `qua_shared/schemas/config/riwayat.py`. The
 * runtime map is mirrored here — and typed as `Record<InspectorRiwayah, …>`, so
 * adding a fifth riwayah backend-side breaks `npm run check` until this file
 * catches up rather than silently shipping a stale list.
 *
 * Compare against these, never against a bare `short === 'hafs'`: `short` is a
 * third slug space (the vocab display abbreviation) and is not the identity the
 * pipeline keys on.
 */

import type { RiwayahSupport } from './types/generated/schemas';

/** Inspector vocabulary slug — the `riwayahs.slug` column. */
export type InspectorRiwayah = RiwayahSupport['inspector_slug'];

/** The matching `qua_domain` / `qua_sdk` slug. */
export type SdkRiwayah = RiwayahSupport['sdk_slug'];

/** Product order — the order the aligner app offers them in. */
export const SUPPORTED_RIWAYAT: Record<InspectorRiwayah, SdkRiwayah> = {
    hafs_an_asim: 'hafs',
    warsh_an_nafi: 'warsh',
    qalon_an_nafi: 'qalun',
    shubah_an_asim: 'shuba',
};

export const DEFAULT_RIWAYAH: InspectorRiwayah = 'hafs_an_asim';
export const DEFAULT_SDK_RIWAYAH: SdkRiwayah = 'hafs';

/** True iff the pipeline can align, review, time and publish this riwayah. */
export function isSupportedRiwayah(slug: string | null | undefined): slug is InspectorRiwayah {
    return !!slug && slug in SUPPORTED_RIWAYAT;
}

/** True iff `slug` is Hafs — the branch that keeps the DigitalKhatt display path. */
export function isHafs(slug: string | null | undefined): boolean {
    return slug === DEFAULT_RIWAYAH;
}

/** The SDK slug for an Inspector slug, or `null` when unsupported. */
export function toSdkSlug(slug: string | null | undefined): SdkRiwayah | null {
    return isSupportedRiwayah(slug) ? SUPPORTED_RIWAYAT[slug] : null;
}
