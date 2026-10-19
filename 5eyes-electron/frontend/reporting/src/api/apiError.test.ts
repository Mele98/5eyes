/**
 * RISK-OVERRIDE-WRITE-BOUNDARY-001 (CIO-Entscheid 2026-10-19, PR #657):
 * strukturierte 409/422-Details `{reason_code, message}` werden ZENTRAL als
 * `message [reason_code]` angezeigt -- identisch zum Monolithen -- statt als
 * nacktes "HTTP 409". Gilt fuer jeden API-Client, weil alle denselben
 * Handler (`apiErrorFromResponse`) verwenden.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { overrideRiskAssessment } from './profiling';
import { ApiError, apiErrorFromResponse, fetchAdvisoryReport, formatApiErrorDetail } from './client';
import { flattenDetail } from './allocation';
import { formatGoalError } from '@/lib/goalForm';

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

const STRUCTURED = {
  reason_code: 'RISK_ASSESSMENT_NOT_CURRENT',
  message: 'Nur das aktuelle Risikoprofil kann uebersteuert werden.',
  assessment_id: 'ra-old',
  current_assessment_id: 'ra-current',
};

describe('formatApiErrorDetail', () => {
  it('zeigt strukturierte Details als "message [reason_code]"', () => {
    expect(formatApiErrorDetail(STRUCTURED)).toBe(
      'Nur das aktuelle Risikoprofil kann uebersteuert werden. [RISK_ASSESSMENT_NOT_CURRENT]',
    );
  });
  it('zeigt message ohne reason_code unveraendert', () => {
    expect(formatApiErrorDetail({ message: 'Nur Text' })).toBe('Nur Text');
  });
  it('laesst Strings unveraendert', () => {
    expect(formatApiErrorDetail('boom')).toBe('boom');
  });
  it('flacht FastAPI-422-Arrays ueber .msg', () => {
    expect(formatApiErrorDetail([{ loc: ['body', 'x'], msg: 'a' }, { msg: 'b' }])).toBe('a; b');
  });
  it('faellt auf den uebergebenen Default zurueck', () => {
    expect(formatApiErrorDetail(null, 'Default')).toBe('Default');
  });
  it('Modul-Formatter delegieren an den zentralen Formatter', () => {
    const expected = formatApiErrorDetail(STRUCTURED);
    expect(flattenDetail(STRUCTURED)).toBe(expected);
    expect(formatGoalError(STRUCTURED)).toBe(expected);
  });
});

describe('apiErrorFromResponse', () => {
  it.each([409, 422])('baut fuer %i mit strukturiertem Detail "message [reason_code]"', async (status) => {
    const err = await apiErrorFromResponse(jsonResponse(status, { detail: STRUCTURED }));
    expect(err).toBeInstanceOf(ApiError);
    expect(err.status).toBe(status);
    expect(err.detail).toBe(
      'Nur das aktuelle Risikoprofil kann uebersteuert werden. [RISK_ASSESSMENT_NOT_CURRENT]',
    );
    expect(err.raw).toEqual(STRUCTURED);
  });
  it('faellt bei Non-JSON auf "HTTP <status>" zurueck', async () => {
    const err = await apiErrorFromResponse(new Response('nope', { status: 500 }));
    expect(err.detail).toBe('HTTP 500');
  });
});

describe('API-Clients nutzen den zentralen Handler', () => {
  const fetchMock = vi.fn();
  beforeEach(() => {
    fetchMock.mockReset();
    vi.stubGlobal('fetch', fetchMock);
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('Risiko-Override: 409 zeigt message [reason_code]', async () => {
    fetchMock.mockResolvedValue(jsonResponse(409, { detail: STRUCTURED }));
    await expect(
      overrideRiskAssessment('m1', 'ra-old', {
        override_score_x10: 60,
        override_profile: 'Ausgewogen',
        override_reason: 'Kunde wuenscht eine dokumentierte Anpassung nach Besprechung.',
      }),
    ).rejects.toMatchObject({
      status: 409,
      detail: 'Nur das aktuelle Risikoprofil kann uebersteuert werden. [RISK_ASSESSMENT_NOT_CURRENT]',
    });
  });

  it('Advisory-Report: 409 zeigt message [reason_code]', async () => {
    fetchMock.mockResolvedValue(
      jsonResponse(409, { detail: { reason_code: 'COST_DISCLOSURE_DEGRADED', message: 'Kostenausweis unvollstaendig.' } }),
    );
    await expect(fetchAdvisoryReport('m1')).rejects.toMatchObject({
      status: 409,
      detail: 'Kostenausweis unvollstaendig. [COST_DISCLOSURE_DEGRADED]',
    });
  });
});
