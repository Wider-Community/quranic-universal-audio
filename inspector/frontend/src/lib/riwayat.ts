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

const SDK_TO_INSPECTOR = Object.fromEntries(
    Object.entries(SUPPORTED_RIWAYAT).map(([inspector, sdk]) => [sdk, inspector]),
) as Record<SdkRiwayah, InspectorRiwayah>;

/**
 * The Inspector slug for an SDK slug, or `null` when unsupported.
 *
 * Needed because the two vocabularies meet in the browser: a shard's
 * `_meta.riwayah` is the SDK slug, while the font and reference-bundle routes
 * are keyed by the Inspector slug (the `riwayahs.slug` column).
 */
export function toInspectorSlug(slug: string | null | undefined): InspectorRiwayah | null {
    return slug && slug in SDK_TO_INSPECTOR ? SDK_TO_INSPECTOR[slug as SdkRiwayah] : null;
}

/** U+06DD ARABIC END OF AYAH — the ornament Digital Khatt expects around a number. */
export const AYAH_END_ORNAMENT = '۝';

/**
 * Glyph to put before an Arabic-Indic verse number, keyed by **SDK** slug.
 *
 * Mirrors the server's `services.reference.quran_refs.verse_marker_prefix`, and
 * exists separately because the Timestamps tab reads its edition off the shard
 * rather than off the Segments reference bundle that carries the same field.
 * The three packaged QPC fonts decorate the digits themselves, so sending the
 * ornament as well renders two nested circles.
 */
export function verseMarkerPrefix(sdkSlug: string | null | undefined): string {
    return !sdkSlug || sdkSlug === DEFAULT_SDK_RIWAYAH ? AYAH_END_ORNAMENT : '';
}
