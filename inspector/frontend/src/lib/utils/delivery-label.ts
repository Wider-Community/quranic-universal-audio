/**
 * Display-name helpers for catalog vocab slugs.
 * Centralized so slugs never leak to the UI.
 */
import type { PublicDelivery } from '../types/public-state';

const TITLE_CASE_OVERRIDES: Record<string, string> = {
    mp3quran: 'mp3quran',
    quranicaudio: 'quranicaudio',
    qul: 'qul',
    archive_org: 'archive.org',
    tvquran: 'tvquran',
    everyayah: 'everyayah',
    tarteel: 'tarteel',
};

export function titleCaseSlug(slug: string | null | undefined): string {
    if (!slug) return '';
    const override = TITLE_CASE_OVERRIDES[slug];
    if (override) return override;
    return slug
        .split(/[_-]/)
        .map((p) => p.charAt(0).toUpperCase() + p.slice(1))
        .join(' ');
}

const BITRATE_MODE_LABEL: Record<string, string> = {
    cbr: 'cbr',
    vbr: 'vbr',
    abr: 'abr',
    mostly_cbr: 'mostly cbr',
    mostly_vbr: 'mostly vbr',
    mixed: 'mixed',
    unknown: '',
};

/** Field separator used across all combination display surfaces. */
export const SEP = ' · ';

export function bitrateLabel(d: PublicDelivery): string {
    const mode = (d.bitrate_mode || '').toLowerCase();
    const kbps = d.bitrate_kbps_nominal;
    const modeText = BITRATE_MODE_LABEL[mode] ?? mode.replace(/_/g, ' ');
    if (kbps == null) return modeText || '—';
    if (!modeText) return `${kbps} kbps`;
    return `${kbps} kbps${SEP}${modeText}`;
}

/** Compact coverage badge for the picker — "Full" or "47/114". */
export function compactCoverageLabel(d: PublicDelivery): string {
    if (d.coverage_kind === 'full') return 'Full';
    return `${d.chapter_count}/114`;
}

/** Compact hours badge for the picker — "3.5h", "45m", or "—". */
export function compactHoursLabel(d: PublicDelivery): string {
    if (d.total_duration_sec == null) return '—';
    const h = d.total_duration_sec / 3600;
    if (h < 1) return `${Math.round(h * 60)}m`;
    return `${h.toFixed(1)}h`;
}

/** "x ayahs" if by_ayah, "x surahs" if by_surah. */
export function coverageLabel(d: PublicDelivery): string {
    if (d.audio_category === 'by_ayah') {
        const n = d.chapter_count;
        return `${n} ${n === 1 ? 'ayah' : 'ayahs'}`;
    }
    const n = d.chapter_count;
    return `${n} ${n === 1 ? 'surah' : 'surahs'}`;
}

export function categoryLabel(d: PublicDelivery): string {
    return d.audio_category === 'by_ayah' ? 'Ayah' : 'Surah';
}

export function channelDisplay(d: PublicDelivery): string {
    return d.channel_name || titleCaseSlug(d.channel);
}

/** Total hours from total_duration_sec. */
export function totalHoursLabel(d: PublicDelivery): string {
    const s = d.total_duration_sec;
    if (s == null || s <= 0) return '—';
    const totalMin = Math.round(s / 60);
    const h = Math.floor(totalMin / 60);
    const m = totalMin % 60;
    if (h === 0) return `${m}m`;
    return `${h}h ${m.toString().padStart(2, '0')}m`;
}

/**
 * Compact one-line combination label for the bottom-player chip.
 * "Hafs · Murattal · QDC Official"
 */
export function combinationCompact(d: PublicDelivery): string {
    return [titleCaseSlug(d.riwayah), titleCaseSlug(d.style), channelDisplay(d)]
        .filter(Boolean)
        .join(SEP);
}

/**
 * Two-line combination label for the player's combination-switcher dropup.
 * line 1: Riwayah · Style · [Context ·] Channel
 * line 2: Coverage · Bitrate · [Hours]
 */
export function combinationStandard(d: PublicDelivery): { line1: string; line2: string } {
    const line1Parts: string[] = [titleCaseSlug(d.riwayah), titleCaseSlug(d.style)];
    if (d.recording_context) line1Parts.push(titleCaseSlug(d.recording_context));
    line1Parts.push(channelDisplay(d));

    const line2Parts: string[] = [coverageLabel(d), bitrateLabel(d)];
    const hours = totalHoursLabel(d);
    if (hours && hours !== '—') line2Parts.push(hours);

    return {
        line1: line1Parts.filter(Boolean).join(SEP),
        line2: line2Parts.filter(Boolean).join(SEP),
    };
}

/** ISO-2 → country display name. Falls back to the code when unknown. */
let _countryDisplay: Intl.DisplayNames | null | undefined = undefined;
function countryDisplayInstance(): Intl.DisplayNames | null {
    if (_countryDisplay !== undefined) return _countryDisplay;
    try {
        _countryDisplay = new Intl.DisplayNames(['en'], { type: 'region' });
    } catch {
        _countryDisplay = null;
    }
    return _countryDisplay;
}
export function countryName(iso2: string | null | undefined): string {
    if (!iso2) return '';
    const dn = countryDisplayInstance();
    if (!dn) return iso2.toUpperCase();
    try {
        return dn.of(iso2.toUpperCase()) ?? iso2.toUpperCase();
    } catch {
        return iso2.toUpperCase();
    }
}

/**
 * Render an ISO-3166-1 alpha-2 country code as its flag emoji using the
 * Regional Indicator Symbols code-point trick (A=0x1F1E6). Returns an
 * empty string when the code is missing or not a 2-letter shape, so the
 * UI can decide whether to fall back to text. */
export function countryFlag(iso2: string | null | undefined): string {
    if (!iso2) return '';
    const code = iso2.trim().toUpperCase();
    if (code.length !== 2) return '';
    const A = 0x1F1E6;
    const baseA = 'A'.charCodeAt(0);
    if (code.charCodeAt(0) < baseA || code.charCodeAt(0) > baseA + 25) return '';
    if (code.charCodeAt(1) < baseA || code.charCodeAt(1) > baseA + 25) return '';
    return String.fromCodePoint(
        A + code.charCodeAt(0) - baseA,
        A + code.charCodeAt(1) - baseA,
    );
}
