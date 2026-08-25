/**
 * Sprint U-20 (Roadmap-Punkt 20, 2026-06-04): React-Router v6 Future-Flags
 * Drift-Schutz.
 */
import { describe, it, expect } from 'vitest';
import { ROUTER_FUTURE_FLAGS } from './routerFlags';


describe('U-20 React-Router Future-Flags', () => {
  it('v7_startTransition is enabled', () => {
    expect(ROUTER_FUTURE_FLAGS.v7_startTransition).toBe(true);
  });

  it('v7_relativeSplatPath is enabled', () => {
    expect(ROUTER_FUTURE_FLAGS.v7_relativeSplatPath).toBe(true);
  });

  it('v7_fetcherPersist is enabled', () => {
    expect(ROUTER_FUTURE_FLAGS.v7_fetcherPersist).toBe(true);
  });

  it('v7_normalizeFormMethod is enabled', () => {
    expect(ROUTER_FUTURE_FLAGS.v7_normalizeFormMethod).toBe(true);
  });

  it('v7_partialHydration is enabled', () => {
    expect(ROUTER_FUTURE_FLAGS.v7_partialHydration).toBe(true);
  });

  it('v7_skipActionErrorRevalidation is enabled', () => {
    expect(ROUTER_FUTURE_FLAGS.v7_skipActionErrorRevalidation).toBe(true);
  });

  it('all 6 future-flags are activated', () => {
    const enabled = Object.values(ROUTER_FUTURE_FLAGS).filter(Boolean);
    expect(enabled.length).toBe(6);
  });

  it('all flag keys follow v7_ naming convention', () => {
    const keys = Object.keys(ROUTER_FUTURE_FLAGS);
    expect(keys.length).toBe(6);
    for (const key of keys) {
      expect(key).toMatch(/^v7_/);
    }
  });
});
