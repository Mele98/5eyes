/**
 * Sprint U-5 (Roadmap-Punkt 5): Tests fuer den Token-Handoff von der
 * Hauptapp 5eyes_v2.html an die Reporting-Sub-App.
 *
 * Deckt die in `consumeHandoffFromUrlFragment` versteckten Edge-Cases ab,
 * die in den vergangenen Sprints zwar implementiert, aber nicht
 * verifiziert wurden:
 *  - Akzeptierte Hash-Pattern (#token=, #/route?token=, #foo=1&token=)
 *  - URL-Cleanup ueber history.replaceState
 *  - Idempotenz (mehrfacher Aufruf, leere Hashes)
 *  - URL-encoded JWT-Padding-Zeichen (.,=,+)
 *  - sessionStorage-Fail (= No-Op, kein Crash)
 *  - history.replaceState-Fail (= Token-Set bleibt erfolgreich)
 *  - Browser-Server-Side ohne window (SSR-Schutz)
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { consumeHandoffFromUrlFragment } from './handoff';

const STORAGE_KEY = '5eyes_token';

function setHash(hash: string): void {
  // Direktes Setzen des Hashes via history.replaceState — sonst loest
  // jsdom in Tests echte Navigations-Events aus.
  const clean = window.location.pathname + window.location.search;
  window.history.replaceState(null, '', clean + hash);
}

describe('consumeHandoffFromUrlFragment — Hash-Patterns', () => {
  beforeEach(() => {
    window.sessionStorage.clear();
    setHash('');
  });

  it('erkennt einfaches #token=abc', () => {
    setHash('#token=abc123');
    const result = consumeHandoffFromUrlFragment();
    expect(result).toEqual({
      consumed: true,
      destination: 'sessionStorage',
    });
    expect(window.sessionStorage.getItem(STORAGE_KEY)).toBe('abc123');
  });

  it('erkennt #foo=1&token=abc (mehrere Hash-Parameter)', () => {
    setHash('#foo=1&token=secrettoken');
    const result = consumeHandoffFromUrlFragment();
    expect(result.consumed).toBe(true);
    expect(window.sessionStorage.getItem(STORAGE_KEY)).toBe('secrettoken');
  });

  it('erkennt #/route?token=abc (route-style)', () => {
    setHash('#/mandates/abc/report?token=routerToken');
    const result = consumeHandoffFromUrlFragment();
    expect(result.consumed).toBe(true);
    expect(window.sessionStorage.getItem(STORAGE_KEY)).toBe('routerToken');
  });

  it('akzeptiert URL-encoded JWT mit . und = und + (encodeURIComponent)', () => {
    // Realistisches JWT mit base64-Padding und Trenn-Punkten.
    const jwt = 'header.payload.signature+padding=';
    const encoded = encodeURIComponent(jwt);
    setHash(`#token=${encoded}`);
    consumeHandoffFromUrlFragment();
    expect(window.sessionStorage.getItem(STORAGE_KEY)).toBe(jwt);
  });

  it('ignoriert Hash ohne token-Parameter', () => {
    setHash('#foo=bar&baz=qux');
    const result = consumeHandoffFromUrlFragment();
    expect(result).toEqual({ consumed: false, destination: null });
    expect(window.sessionStorage.getItem(STORAGE_KEY)).toBeNull();
  });

  it('No-Op bei leerem Hash', () => {
    setHash('');
    const result = consumeHandoffFromUrlFragment();
    expect(result.consumed).toBe(false);
    expect(window.sessionStorage.getItem(STORAGE_KEY)).toBeNull();
  });

  it('Leeres token= wird ignoriert, NICHT als gueltige Konsumtion gewertet', () => {
    setHash('#token=');
    const result = consumeHandoffFromUrlFragment();
    expect(result.consumed).toBe(false);
    expect(window.sessionStorage.getItem(STORAGE_KEY)).toBeNull();
  });
});

describe('consumeHandoffFromUrlFragment — URL-Cleanup', () => {
  beforeEach(() => {
    window.sessionStorage.clear();
    setHash('');
  });

  it('entfernt #token=... aus window.location nach Konsumtion', () => {
    setHash('#token=abc');
    consumeHandoffFromUrlFragment();
    expect(window.location.hash).toBe('');
  });

  it('Hash-Cleanup laeuft auch wenn replaceState fehlschlaegt', () => {
    setHash('#token=abc');
    const spy = vi
      .spyOn(window.history, 'replaceState')
      .mockImplementation(() => {
        throw new Error('History API blocked.');
      });
    const result = consumeHandoffFromUrlFragment();
    // Token wurde TROTZDEM in sessionStorage geschrieben
    expect(result.consumed).toBe(true);
    expect(window.sessionStorage.getItem(STORAGE_KEY)).toBe('abc');
    spy.mockRestore();
  });
});

describe('consumeHandoffFromUrlFragment — Idempotenz', () => {
  beforeEach(() => {
    window.sessionStorage.clear();
    setHash('');
  });

  it('zweiter Aufruf nach erfolgreicher Konsumtion ist No-Op', () => {
    setHash('#token=once');
    const first = consumeHandoffFromUrlFragment();
    expect(first.consumed).toBe(true);
    // Nach Cleanup ist Hash leer -> zweiter Aufruf darf nichts mehr tun.
    const second = consumeHandoffFromUrlFragment();
    expect(second).toEqual({ consumed: false, destination: null });
    // Token bleibt erhalten
    expect(window.sessionStorage.getItem(STORAGE_KEY)).toBe('once');
  });

  it('mehrfacher Aufruf ohne Hash ist No-Op', () => {
    setHash('');
    consumeHandoffFromUrlFragment();
    consumeHandoffFromUrlFragment();
    consumeHandoffFromUrlFragment();
    expect(window.sessionStorage.getItem(STORAGE_KEY)).toBeNull();
  });
});

describe('consumeHandoffFromUrlFragment — Robustheit', () => {
  beforeEach(() => {
    window.sessionStorage.clear();
    setHash('');
  });

  it('sessionStorage-Schreibfehler -> consumed=false, kein Crash', () => {
    setHash('#token=will-fail');
    const spy = vi
      .spyOn(Storage.prototype, 'setItem')
      .mockImplementation(() => {
        throw new DOMException('QuotaExceeded', 'QuotaExceededError');
      });
    const result = consumeHandoffFromUrlFragment();
    expect(result).toEqual({ consumed: false, destination: null });
    spy.mockRestore();
  });

  it('typeof window === "undefined" (SSR) -> consumed=false', () => {
    // Wir simulieren das, indem wir per Record-Cast das `window`
    // temporaer aushebeln. In Echt: kein SSR in der Sub-App, aber
    // der Defensive-Check soll funktionieren.
    const original = globalThis.window;
    const g = globalThis as Record<string, unknown>;
    delete g.window;
    try {
      const result = consumeHandoffFromUrlFragment();
      expect(result).toEqual({ consumed: false, destination: null });
    } finally {
      g.window = original;
    }
  });
});
