/**
 * Import-time modules (e.g. `surah-info.ts`) call `fetch('/api/surah-info')`.
 * Without the Flask app, that rejects and Vitest reports unhandled rejections.
 */
export {};

function mockFetch(input: RequestInfo | URL, _init?: RequestInit): Promise<Response> {
  const url =
    typeof input === 'string'
      ? input
      : input instanceof Request
        ? input.url
        : String(input);
  if (url.includes('surah-info')) {
    return Promise.resolve(
      new Response('{}', {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    );
  }
  return Promise.resolve(
    new Response('{}', { status: 200, headers: { 'Content-Type': 'application/json' } }),
  );
}

globalThis.fetch = mockFetch as typeof fetch;
