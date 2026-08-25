/**
 * Tests für den Target-Allocation-API-Client (Track #67).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  fetchCurrentAllocation,
  flattenDetail,
  generateAllocation,
  runSensitivity,
  saveTargetAllocation,
} from './allocation';
import type { TargetAllocationCreatePayload } from './types';

const fetchMock = vi.fn();
const STORAGE_KEY = '5eyes_token';

function jsonResponse(body: unknown, init: { ok?: boolean; status?: number } = {}): Response {
  return {
    ok: init.ok ?? true,
    status: init.status ?? 200,
    json: async () => body,
  } as unknown as Response;
}

const PAYLOAD: TargetAllocationCreatePayload = {
  target_equities_bps: 4000,
  target_bonds_bps: 3000,
  target_real_estate_bps: 1000,
  target_alternatives_bps: 1000,
  target_liquidity_bps: 1000,
  band_equities_min_bps: 3000,
  band_equities_max_bps: 5000,
  band_bonds_min_bps: 2000,
  band_bonds_max_bps: 4000,
  band_real_estate_min_bps: 0,
  band_real_estate_max_bps: 2000,
  band_alternatives_min_bps: 0,
  band_alternatives_max_bps: 2000,
  band_liquidity_min_bps: 0,
  band_liquidity_max_bps: 2000,
  policy_id: 'pol-1',
};

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal('fetch', fetchMock);
  window.sessionStorage.clear();
  window.localStorage.clear();
  delete (window as { desktop?: unknown }).desktop;
});

afterEach(() => {
  vi.unstubAllGlobals();
  window.sessionStorage.clear();
});

describe('flattenDetail', () => {
  it('gibt String unverändert zurück', () => {
    expect(flattenDetail('boom')).toBe('boom');
  });
  it('flacht ein 422-Array über .msg', () => {
    expect(flattenDetail([{ msg: 'a' }, { msg: 'b' }])).toBe('a; b');
  });
});

describe('fetchCurrentAllocation', () => {
  it('liefert den Record + setzt Bearer-Header', async () => {
    window.sessionStorage.setItem(STORAGE_KEY, 'jwt-9');
    fetchMock.mockResolvedValue(jsonResponse({ id: 'ta1', policy_id: 'pol-1' }));
    const rec = await fetchCurrentAllocation('m1');
    expect(rec.id).toBe('ta1');
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe('/mandates/m1/target-allocation/current');
    expect((init.headers as Record<string, string>).Authorization).toBe('Bearer jwt-9');
  });

  it('wirft ApiError(404) wenn keine SOLL existiert', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ detail: 'Keine Soll-Allokation gefunden' }, { ok: false, status: 404 }));
    await expect(fetchCurrentAllocation('m1')).rejects.toMatchObject({ status: 404 });
  });

  it('wirft ApiError(0) bei Netzwerk-Fehler', async () => {
    fetchMock.mockRejectedValue(new TypeError('Failed to fetch'));
    await expect(fetchCurrentAllocation('m1')).rejects.toMatchObject({ status: 0 });
  });
});

describe('saveTargetAllocation', () => {
  it('POSTet den Payload und gibt den Record zurück', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ id: 'ta2', version: 2 }, { status: 201 }));
    const rec = await saveTargetAllocation('m1', PAYLOAD);
    expect(rec.version).toBe(2);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe('/mandates/m1/target-allocation');
    expect(init.method).toBe('POST');
    expect(JSON.parse(init.body).target_equities_bps).toBe(4000);
  });

  it('flacht ein 422-Detail-Array zu ApiError.detail', async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({ detail: [{ msg: 'Allokation muss 10000 BP ergeben' }] }, { ok: false, status: 422 }),
    );
    await expect(saveTargetAllocation('m1', PAYLOAD)).rejects.toMatchObject({
      status: 422,
      detail: 'Allokation muss 10000 BP ergeben',
    });
  });
});

describe('generateAllocation', () => {
  it('POSTet auf /generate mit preferences:null', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ target_allocation: { id: 'ta3' }, expected_return_bps: 350 }));
    const res = await generateAllocation('m1');
    expect(res.expected_return_bps).toBe(350);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe('/mandates/m1/target-allocation/generate');
    expect(JSON.parse(init.body)).toEqual({ preferences: null });
  });
});

describe('runSensitivity', () => {
  it('POSTet goal_id + delta auf /sensitivity', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ goal_id: 'g1', delta_pct: 10 }));
    const res = await runSensitivity('m1', { goal_id: 'g1', target_delta_pct: 10 });
    expect(res.delta_pct).toBe(10);
    expect(fetchMock.mock.calls[0][0]).toBe('/mandates/m1/target-allocation/sensitivity');
  });
});
