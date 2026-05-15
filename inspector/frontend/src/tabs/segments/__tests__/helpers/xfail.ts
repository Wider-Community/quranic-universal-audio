// xfail helper for vitest.
//
// Wraps a test body and inverts pass/fail: if the body throws, the test
// passes (the expected-failure case). If the body completes without
// throwing, the wrapper throws to surface a "surprise pass" — the
// xfail marker should be removed at the corresponding phase commit.
//
// Usage:
//   it('uses uid first', xfail('phase-6', () => {
//     expect(resolveIssue(...)).toBe(...);
//   }));

export function xfail(reason: string, fn: () => void | Promise<void>) {
  return async () => {
    let passed = false;
    try {
      await fn();
      passed = true;
    } catch {
      return;
    }
    if (passed) {
      throw new Error(
        `xfail expected to fail (${reason}) but passed; remove the xfail marker.`,
      );
    }
  };
}
