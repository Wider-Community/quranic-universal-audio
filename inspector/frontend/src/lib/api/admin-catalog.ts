import type { AdminDelivery } from '../types/generated/schemas';

export type ReciterCatalogEdit = Partial<{
    name_en: string | null;
    name_ar: string | null;
    country: string | null;
    notes: string | null;
}>;

export type DeliveryCatalogEdit = Partial<{
    riwayah: string | null;
    style: string | null;
    recording_context: string | null;
    recording_year: number | null;
    variant_label: string | null;
    source: string | null;
    channel: string | null;
    source_url: string | null;
    audio_category: string | null;
    chapter_count: number | null;
    codec: string | null;
    container: string | null;
    sample_rate_hz: number | null;
    channels: number | null;
    bitrate_mode: string | null;
    bitrate_kbps_nominal: number | null;
    total_duration_sec: number | null;
}>;

async function patchJson<T>(url: string, body: Record<string, unknown>): Promise<T> {
    const response = await fetch(url, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
    });
    if (!response.ok) {
        let message = `HTTP ${response.status}`;
        try {
            const payload = (await response.json()) as { error?: string };
            if (payload.error) message = payload.error;
        } catch {
            /* Keep the status fallback for non-JSON errors. */
        }
        throw new Error(message);
    }
    return (await response.json()) as T;
}

export async function editReciterCatalog(
    reciterId: string,
    fields: ReciterCatalogEdit,
): Promise<{ reciter: Record<string, unknown> }> {
    return patchJson(`/api/admin/catalog/reciter/${encodeURIComponent(reciterId)}`, fields);
}

export async function editDeliveryCatalog(
    slug: string,
    fields: DeliveryCatalogEdit,
): Promise<{ delivery: AdminDelivery }> {
    return patchJson(`/api/admin/catalog/delivery/${encodeURIComponent(slug)}`, fields);
}
