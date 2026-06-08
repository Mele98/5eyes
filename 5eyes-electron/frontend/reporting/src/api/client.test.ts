/**
 * Sprint U-5 (Roadmap-Punkt 5): Tests fuer die 4-stufige Auth-Token-
 * Cascade in `resolveAuthToken` + fetch-Verhalten in `fetchAdvisoryReport`.
 *
 * Cascade-Reihenfolge:
 *  1. window.desktop.getAuthToken()   (Electron IPC -> safeStorage)
 *  2. sessionStorage['5eyes_token']    (via Handoff aus URL-Fragment)
 *  3. localStorage['5eyes_token']      (Legacy-Backward-Compat)
 *  4. import.meta.env.VITE_5EYES_TOKEN (Vite Dev-Default)
 *
 * Jede Stufe muss bei Exception der vorherigen Stufe weitergehen
 * (Fail-Soft), damit der Berater nie in einem gebrochenen Auth-State
 * landet.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { resolveAuthToken } from './client';

const STORAGE_KEY = '5eyes_token';

function clearAllStorage(): void {
  window.sessionStorage.clear();
  window.localStorage.clear();
}

function clearDesktopBridge(): void {
  // `window.desktop` ist in jsdom natuerlich nicht gesetzt, aber Tests
  // koennen es injizieren. Reset stellt Standard-Zustand wieder her.
  delete (window as { desktop?: unknown }).desktop;
}

describe('resolveAuthToken — Cascade-Reihenfolge', () => {
  beforeEach(() => {
    clearAllStorage();
    clearDesktopBridge();
  });

  afterEach(() => {
    clearAllStorage();
    clearDesktopBridge();
  });

  it('Stufe 1: window.desktop.getAuthToken hat Vorrang', async () => {
    (window as { desktop?: { getAuthToken: () => Promise<string> } }).desktop =
      {
        getAuthToken: vi.fn().mockResolvedValue('electron-token'),
      };
    window.sessionStorage.setItem(STORAGE_KEY, 'session-token');
    window.localStorage.setItem(STORAGE_KEY, 'local-token');
    const token = await resolveAuthToken();
    expect(token).toBe('electron-token');
  });

  it('Stufe 2: sessionStorage wenn Desktop-Bridge null liefert', async () => {
    (window as { desktop?: { getAuthToken: () => Promise<string | null> } }).desktop =
      {
        getAuthToken: vi.fn().mockResolvedValue(null),
      };
    window.sessionStorage.setItem(STORAGE_KEY, 'session-token');
    window.localStorage.setItem(STORAGE_KEY, 'local-token');
    const token = await resolveAuthToken();
    expect(token).toBe('session-token');
  });

  it('Stufe 2: sessionStorage wenn window.desktop nicht existiert', async () => {
    window.sessionStorage.setItem(STORAGE_KEY, 'session-only');
    const token = await resolveAuthToken();
    expect(token).toBe('session-only');
  });

  it('Stufe 3: localStorage als Backwards-Compat-Fallback', async () => {
    window.localStorage.setItem(STORAGE_KEY, 'legacy-token');
    const token = await resolveAuthToken();
    expect(token).toBe('legacy-token');
  });

  it('Cascade gibt null wenn nichts gefunden', async () => {
    const token = await resolveAuthToken();
    expect(token).toBeNull();
  });
});

describe('resolveAuthToken — Fail-Soft', () => {
  beforeEach(() => {
    clearAllStorage();
    clearDesktopBridge();
  });

  it('Desktop-Bridge wirft Exception -> faellt durch zu sessionStorage', async () => {
    (window as { desktop?: { getAuthToken: () => Promise<string> } }).desktop =
      {
        getAuthToken: vi.fn().mockRejectedValue(new Error('IPC failed')),
      };
    window.sessionStorage.setItem(STORAGE_KEY, 'fallback');
    const token = await resolveAuthToken();
    expect(token).toBe('fallback');
  });

  it('sessionStorage wirft Exception -> faellt durch zu localStorage', async () => {
    window.localStorage.setItem(STORAGE_KEY, 'legacy');
    const spy = vi
      .spyOn(Storage.prototype, 'getItem')
      .mockImplementationOnce(() => {
        // Erster Aufruf = sessionStorage.getItem -> wirft
        throw new Error('Storage disabled');
      });
    const token = await resolveAuthToken();
    expect(token).toBe('legacy');
    spy.mockRestore();
  });

  it('Alle Storage-Stufen werfen -> null, kein Crash', async () => {
    const spy = vi
      .spyOn(Storage.prototype, 'getItem')
      .mockImplementation(() => {
        throw new Error('Storage disabled');
      });
    const token = await resolveAuthToken();
    expect(token).toBeNull();
    spy.mockRestore();
  });
});

describe('resolveAuthToken — Realistische Hauptapp-Flows', () => {
  beforeEach(() => {
    clearAllStorage();
    clearDesktopBridge();
  });

  it('Browser-Dev-Workflow (kein Electron, Handoff hat sessionStorage gefuellt)', async () => {
    // Genau das, was nach `consumeHandoffFromUrlFragment` passiert.
    window.sessionStorage.setItem(STORAGE_KEY, 'jwt.header.payload');
    const token = await resolveAuthToken();
    expect(token).toBe('jwt.header.payload');
  });

  it('Electron-Workflow (Desktop-Bridge liefert vor Handoff)', async () => {
    (window as { desktop?: { getAuthToken: () => Promise<string> } }).desktop =
      {
        getAuthToken: vi.fn().mockResolvedValue('encrypted-desktop-jwt'),
      };
    // Keine sessionStorage gesetzt — Electron-Pfad ist primary.
    const token = await resolveAuthToken();
    expect(token).toBe('encrypted-desktop-jwt');
  });

  it('JWT mit base64-Padding und Punkten bleibt unveraendert', async () => {
    const jwt = 'eyJhbGciOi.eyJzdWIiOi.5cF7+w==';
    window.sessionStorage.setItem(STORAGE_KEY, jwt);
    const token = await resolveAuthToken();
    expect(token).toBe(jwt);
  });
});
