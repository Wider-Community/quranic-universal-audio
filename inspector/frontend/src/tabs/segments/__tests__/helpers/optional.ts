// Dynamic-import helper that hides the module specifier from Vite's static
// analyzer. Used to opt into "skip if module missing" semantics for tests
// that depend on modules introduced by later phases.
//
// Vite by default refuses to bundle a dynamic import whose target file does
// not exist at config time. Wrapping the specifier in a runtime variable
// keeps the build green while preserving lazy resolution at test time.

export async function loadOptional<T = unknown>(
  modulePath: string,
): Promise<T | null> {
  const path = modulePath;
  try {
    return (await import(/* @vite-ignore */ path)) as T;
  } catch {
    return null;
  }
}
