## Post-Stage-1 deferred work

### Timestamps tab — apply segments' registration/injection pattern to break circular imports

**Status:** DEFERRED — flagged by the post-Stage-1 structure critique (2026-04).

Five files in `inspector/frontend/src/timestamps/` still carry `// NOTE: circular dependency` comments where a sibling imports `./index`:
- `timestamps/waveform.ts:11`
- `timestamps/validation.ts:10`
- `timestamps/unified-display.ts:14`
- `timestamps/animation.ts:16`
- `timestamps/keyboard.ts:14`

These are function-level cycles that work at runtime because calls only happen after all modules have loaded, but they are timing footguns and ESLint `import/no-cycle` (being added in this cleanup pass) will flag them.

The segments tab solved the same problem in Phases 3–6 via registration / injection (`setClassifyFn`, `registerEditModes`, `registerEditDrawFns`, `registerWaveformHandlers`, `registerHandler`, `registerKeyboardHandler` — all typed through `src/segments/registry.ts`). Timestamps never received that treatment because the tab isn't an editor and the cycles are lighter.

**When to do this**: fold into Stage 2 (Svelte migration), since any component extraction will force the coupling question anyway. Estimated effort: 2-3 hours.

**What to do**:
1. Identify the 5 function calls that cross the cycle (each sibling calls something in `timestamps/index.ts`).
2. Create `timestamps/registry.ts` typing each function with a `Ts*Fn` signature.
3. Replace each `import { foo } from './index'` in the siblings with a registry lookup.
4. Have `timestamps/index.ts` register the functions at module init.
5. Verify typecheck and that all five `// NOTE: circular dependency` comments can be removed cleanly.
