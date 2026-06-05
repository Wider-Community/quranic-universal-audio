/**
 * Default fetch stub for the Vitest jsdom env. Import-time modules
 * (e.g. `surah-info.ts`) call `fetch('/api/surah-info')`; without the Flask
 * app, an unmocked fetch rejects and Vitest reports unhandled rejections.
 *
 * Returns 200 `{}` for any URL. Tests that care about the response shape
 * mock at the typed `api/` layer (the correct isolation boundary), so this
 * default just keeps the import graph clean — it never carries assertions.
 */
export {};

function mockFetch(_input: RequestInfo | URL, _init?: RequestInit): Promise<Response> {
  return Promise.resolve(
    new Response('{}', { status: 200, headers: { 'Content-Type': 'application/json' } }),
  );
}

globalThis.fetch = mockFetch as typeof fetch;
