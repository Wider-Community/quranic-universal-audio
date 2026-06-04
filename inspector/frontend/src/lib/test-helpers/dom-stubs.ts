// Shared DOM stubs for vitest tests.
//
// jsdom doesn't ship IntersectionObserver; any component using it
// (ValidationPanel virtualizer, MissingWordsCard context block) needs the
// stub before render.

export class FakeIntersectionObserver {
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
}
