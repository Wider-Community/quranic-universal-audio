/**
 * Shared session cache for GET /api/static/catalog.json.
 *
 * Multiple surfaces read the same body — the two Dashboard forms (submit
 * wizard `StepDetails`, `RequestForm` vocab). Funnel them through one
 * module-level in-flight promise so a session fetches the body once instead of
 * each component firing its own `fetch`. The backend serves a 5-min
 * `Cache-Control`, which bounds how long a hard-reload sees stale catalog data,
 * and now also byte-caches the serialized body per db_seq (see
 * `routes/public/static.py`).
 */
import { fetchJson } from '../api';
import type { TsCatalogResponse } from '../types/ts-client';

/** A vocab row from catalog.json (`vocab.{riwayat,styles,recording_contexts}`). */
export interface CatalogVocabRow {
    slug: string;
    short?: string;
    name: string;
}

/** catalog.json superset: the TS-dropdown fields plus the vocab block the
 *  Dashboard forms read (not modelled by the slim {@link TsCatalogResponse}). */
export type CatalogJson = TsCatalogResponse & {
    vocab?: {
        riwayat?: CatalogVocabRow[];
        styles?: CatalogVocabRow[];
        recording_contexts?: CatalogVocabRow[];
    };
};

let _catalog: Promise<CatalogJson> | null = null;

/** Fetch (once per session) the full catalog.json body. */
export function loadCatalogJson(): Promise<CatalogJson> {
    if (!_catalog) {
        _catalog = fetchJson<CatalogJson>('/api/static/catalog.json').catch((e) => {
            _catalog = null; // allow retry on transient failure
            throw e;
        });
    }
    return _catalog;
}

/** Test seam — clears the cached promise. */
export function _resetCatalogJsonForTests(): void {
    _catalog = null;
}
