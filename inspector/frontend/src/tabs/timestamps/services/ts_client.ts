/**
 * Timestamps tab — client-side shard-fetch data layer.
 *
 * The implementation moved to `lib/recitation-data/ts-source.ts` so non-tab
 * surfaces (the dashboard now-reciting section) can consume it without a
 * cross-tab import. This barrel preserves the historical
 * `./services/ts_client` import path for the timestamps tab and its tests.
 */

export * from '../../../lib/recitation-data/ts-source';
