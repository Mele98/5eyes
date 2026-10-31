/**
 * RISK-CAPACITY-RECHECK-UI-001: Status der zuletzt gebundenen Bewertung der
 * Plausibilitaetspruefung (GET /mandates/{id}/risk-capacity-plausibility,
 * Feld bound_evaluation). Entspricht sie nicht mehr der aktuellen Datenlage,
 * zeigt die Berater-Ansicht ruhig "neu zu prüfen".
 */
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { RiskCapacityBoundEvaluation } from '@/api/types';
import { fetchRiskCapacityBoundEvaluation } from '@/api/profiling';
import { Risikoprofil } from '@/pages/Risikoprofil';
import { makeRisikoprofil } from '@/test/fixtures';
import { RiskCapacityRecheck, RiskCapacityRecheckNotice } from './RiskCapacityRecheckNotice';

const role = vi.hoisted(() => ({ canEdit: true }));
vi.mock('@/api/useUserRole', () => ({
  useUserRole: () => ({ role: 'advisor', canEdit: role.canEdit, loading: false, error: null }),
}));

const stale: RiskCapacityBoundEvaluation = {
  evaluation_id: 'ev-1',
  binding_context: 'allocation_generated',
  evaluated_at: '2026-10-20T10:00:00',
  needs_recheck: true,
  recheck_code: 'RISK_CAPACITY_EVALUATION_RECHECK_REQUIRED',
  recheck_label: 'neu zu prüfen',
  recheck_text:
    'Plausibilitätsprüfung Risikofähigkeit neu zu prüfen: die bei der Beratung gespeicherte Bewertung entspricht nicht mehr der aktuellen Datenlage.',
  stale_reasons: ['EVALUATION_INPUTS_CHANGED'],
};

const current: RiskCapacityBoundEvaluation = {
  ...stale,
  needs_recheck: false,
  recheck_code: null,
  recheck_label: null,
  recheck_text: null,
  stale_reasons: [],
};

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

afterEach(() => {
  role.canEdit = true;
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('RiskCapacityRecheckNotice', () => {
  it('shows the backend label and text when the bound evaluation needs a recheck', () => {
    render(<RiskCapacityRecheckNotice data={stale} />);
    const note = screen.getByRole('status');
    expect(note).toHaveTextContent('neu zu prüfen');
    expect(note).toHaveTextContent(/entspricht nicht mehr der aktuellen Datenlage/);
    expect(note).toHaveAttribute('data-recheck-code', 'RISK_CAPACITY_EVALUATION_RECHECK_REQUIRED');
    expect(note.className).toContain('print:hidden');
  });

  it('falls back to the fixed label when the backend sends none', () => {
    render(<RiskCapacityRecheckNotice data={{ ...stale, recheck_label: null, recheck_text: null }} />);
    expect(screen.getByRole('status')).toHaveTextContent('neu zu prüfen');
  });

  it('renders nothing for a current evaluation or without a bound evaluation', () => {
    const { container, rerender } = render(<RiskCapacityRecheckNotice data={current} />);
    expect(container).toBeEmptyDOMElement();
    rerender(<RiskCapacityRecheckNotice data={null} />);
    expect(container).toBeEmptyDOMElement();
  });
});

describe('fetchRiskCapacityBoundEvaluation', () => {
  it('reads bound_evaluation from the plausibility endpoint', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ status: 'consistent', bound_evaluation: stale }));
    vi.stubGlobal('fetch', fetchMock);
    await expect(fetchRiskCapacityBoundEvaluation('m 1')).resolves.toEqual(stale);
    expect(fetchMock.mock.calls[0][0]).toBe('/mandates/m%201/risk-capacity-plausibility');
  });

  it('returns null when nothing is bound yet or there is no current profile', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse({ status: 'partial', bound_evaluation: null })));
    await expect(fetchRiskCapacityBoundEvaluation('m-1')).resolves.toBeNull();
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse({ status: 'consistent' })));
    await expect(fetchRiskCapacityBoundEvaluation('m-1')).resolves.toBeNull();
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse({ detail: 'x' }, 404)));
    await expect(fetchRiskCapacityBoundEvaluation('m-1')).resolves.toBeNull();
  });

  it('rejects a bound evaluation without a boolean needs_recheck', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(jsonResponse({ bound_evaluation: { ...stale, needs_recheck: 'yes' } })),
    );
    await expect(fetchRiskCapacityBoundEvaluation('m-1')).rejects.toThrow();
  });
});

describe('RiskCapacityRecheck (Container)', () => {
  it('loads the status for the mandate and shows the hint', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse({ bound_evaluation: stale })));
    render(<RiskCapacityRecheck mandateId="m-1" />);
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('neu zu prüfen'));
  });

  it('stays quiet when loading fails', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ detail: 'kaputt' }, 500));
    vi.stubGlobal('fetch', fetchMock);
    const { container } = render(<RiskCapacityRecheck mandateId="m-1" />);
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });
});

describe('Risikoprofil (Sektion 12) zeigt den Hinweis dort, wo die Plausibilitaet steht', () => {
  it('loads and shows "neu zu prüfen" for advisors', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ bound_evaluation: stale }));
    vi.stubGlobal('fetch', fetchMock);
    render(
      <MemoryRouter>
        <Risikoprofil data={makeRisikoprofil()} mandateId="m-1" />
      </MemoryRouter>,
    );
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('neu zu prüfen'));
    expect(fetchMock.mock.calls[0][0]).toBe('/mandates/m-1/risk-capacity-plausibility');
  });

  it('does not load anything in the read-only view', () => {
    role.canEdit = false;
    const fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);
    render(
      <MemoryRouter>
        <Risikoprofil data={makeRisikoprofil()} mandateId="m-1" />
      </MemoryRouter>,
    );
    expect(fetchMock).not.toHaveBeenCalled();
    expect(screen.queryByRole('status')).toBeNull();
  });
});
