// Visibility + microtask helpers for tests that exercise
// document.visibilityState polling or other async-microtask flows.

/** Force document.hidden + document.visibilityState to a desired state. */
export function setVisibility(hidden: boolean): void {
  Object.defineProperty(document, 'hidden', { value: hidden, configurable: true });
  Object.defineProperty(document, 'visibilityState', {
    value: hidden ? 'hidden' : 'visible',
    configurable: true,
  });
}

/** Fire a `visibilitychange` event so listeners react to a prior setVisibility(). */
export function dispatchVisibilityChange(): void {
  document.dispatchEvent(new Event('visibilitychange'));
}

/** Flush queued microtasks without advancing the fake-timer clock. */
export async function flushMicrotasks(): Promise<void> {
  // A handful of awaits drains promise chains created by runOnce()
  // (fetcher + onResult), without triggering the interval timer.
  for (let i = 0; i < 5; i += 1) await Promise.resolve();
}
