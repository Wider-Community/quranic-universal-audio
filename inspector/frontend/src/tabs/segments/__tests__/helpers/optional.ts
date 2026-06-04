// Dynamic-import helper that hides the module specifier from Vite's static
// analyzer. Returns null only when the module genuinely cannot be resolved
// (module-not-found); any other error — compile failure, runtime exception
// in the module's top-level, circular-import deadlock — is re-thrown so the
// test fails loudly instead of being silently skipped by ``describe.skipIf``.

export async function loadOptional<T = unknown>(
  modulePath: string,
): Promise<T | null> {
  const path = modulePath;
  try {
    return (await import(/* @vite-ignore */ path)) as T;
  } catch (err) {
    const code = (err as { code?: string } | null)?.code;
    const message = err instanceof Error ? err.message : String(err);
    const isNotFound =
      code === 'ERR_MODULE_NOT_FOUND' ||
      code === 'MODULE_NOT_FOUND' ||
      message.includes('Failed to resolve') ||
      message.includes('Cannot find module');
    if (isNotFound) return null;
    throw err;
  }
}
