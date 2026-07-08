/**
 * Tests für den CRM-API-Client (Track #66).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  deleteClient,
  fetchClient,
  fetchNationalities,
  listClients,
  updateClient,
} from './crm';

const fetchMock = vi.fn();
const STORAGE_KEY = '5eyes_token';

function jsonResponse(body: unknown, init: { ok?: boolean; status?: number } = {}): Response {
  return {
    ok: init.ok ?? true,
    status: init.status ?? 200,
    json: async () => body,
  } as unknown as Response;
}

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

describe('listClients', () => {
  it('GETtet /clients ohne Query bei leerer Suche + setzt Bearer', async () => {
    window.sessionStorage.setItem(STORAGE_KEY, 'jwt-6');
    fetchMock.mockResolvedValue(jsonResponse([{ id: 'c1' }]));
    await listClients();
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe('/clients');
    expect((init.headers as Record<string, string>).Authorization).toBe('Bearer jwt-6');
  });

  it('hängt den Suchbegriff als Query an', async () => {
    fetchMock.mockResolvedValue(jsonResponse([]));
    await listClients({ search: 'Muster' });
    expect(fetchMock.mock.calls[0][0]).toBe('/clients?search=Muster');
  });

  it('liefert [] bei Nicht-Array', async () => {
    fetchMock.mockResolvedValue(jsonResponse({}));
    expect(await listClients()).toEqual([]);
  });
});

describe('fetchClient / updateClient', () => {
  it('fetchClient GETtet /clients/{id}', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ id: 'c1', last_name: 'Muster' }));
    const rec = await fetchClient('c1');
    expect(rec.last_name).toBe('Muster');
    expect(fetchMock.mock.calls[0][0]).toBe('/clients/c1');
  });

  it('updateClient PUTtet /clients/{id}', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ id: 'c1' }));
    await updateClient('c1', { first_name: 'Max' });
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe('/clients/c1');
    expect(init.method).toBe('PUT');
    expect(JSON.parse(init.body).first_name).toBe('Max');
  });

  it('flacht 422-Array zu ApiError.detail', async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({ detail: [{ msg: 'first_name required' }] }, { ok: false, status: 422 }),
    );
    await expect(updateClient('c1', {})).rejects.toMatchObject({ status: 422, detail: 'first_name required' });
  });
});

describe('deleteClient', () => {
  it('löst bei 204 auf', async () => {
    const noBody = {
      ok: true,
      status: 204,
      json: async () => {
        throw new Error('kein Body');
      },
    } as unknown as Response;
    fetchMock.mockResolvedValue(noBody);
    await expect(deleteClient('c1')).resolves.toBeUndefined();
    expect(fetchMock.mock.calls[0][1].method).toBe('DELETE');
  });
});

describe('fetchNationalities', () => {
  it('GETtet /clients/{id}/nationalities', async () => {
    fetchMock.mockResolvedValue(jsonResponse([{ id: 'n1', country_code: 'CH' }]));
    const rows = await fetchNationalities('c1');
    expect(rows[0].country_code).toBe('CH');
    expect(fetchMock.mock.calls[0][0]).toBe('/clients/c1/nationalities');
  });
});
