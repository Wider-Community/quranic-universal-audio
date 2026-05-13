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

export function bitrateLabel(d: PublicDelivery): string {
    const mode = (d.bitrate_mode || '').toLowerCase();
    const kbps = d.bitrate_kbps_nominal;
    const modeText = BITRATE_MODE_LABEL[mode] ?? mode.replace(/_/g, ' ');
    if (kbps == null) return modeText || '—';
    if (!modeText) return `${kbps} kbps`;
    return `${kbps} kbps ${modeText}`;
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

/** Compact combination meta line: "Hafs · Murattal · qdc". */
export function combinationShortLabel(d: PublicDelivery): string {
    const parts = [titleCaseSlug(d.riwayah), titleCaseSlug(d.style), titleCaseSlug(d.channel)];
    return parts.filter(Boolean).join(' · ');
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
