/**
 * RISK-CAPACITY-REPORT-001: Plausibilitaetspruefung Risikofaehigkeit in der
 * React-App (Berater-Ansicht). Vorher zeigte die React-App den Status nirgends.
 */
import { render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  fetchRiskCapacityPlausibility,
  normalizeRiskCapacityPlausibility,
} from '@/api/riskCapacityPlausibility';
import type {
  RiskCapacityPlausibility,
  RiskCapacityPlausibilityCompact,
} from '@/api/riskCapacityPlausibility';
import {
  RiskCapacityPlausibilityNotice,
  RiskCapacityPlausibilityPanel,
  RiskCapacityPlausibilityView,
} from './RiskCapacityPlausibilityPanel';

const INCONSISTENT_RAW = {
  version: 'RCP-2026-10-19.v2',
  status: 'inconsistent',
  reason_code: 'RISK_CAPACITY_INCONSISTENT',
  findings: [
    {
      check: 'INCOME_ABOVE_RECORDED',
      question_number: 3,
      declared: 'CHF 12000 bis 20000',
      recorded: 'CHF 4000',
      message: 'Frage 3: erfasstes Einkommen liegt unter der Angabe.',
    },
  ],
  not_evaluable: [],
  coverage: {},
  capacity_binding: true,
  override_down: false,
  thresholds: {},
  data_basis: {},
  advisor_text: 'Plausibilitätsprüfung Risikofähigkeit (RISK_CAPACITY_INCONSISTENT): 1 Angabe weicht ab.',
};

const PARTIAL_RAW = {
  ...INCONSISTENT_RAW,
  status: 'partial',
  reason_code: null,
  findings: [],
  not_evaluable: [
    { check: 'OBLIGATIONS_BELOW_RECORDED', question_number: 5, reason: 'Keine Ausgaben erfasst.' },
  ],
  advisor_text: '',
};

describe('normalizeRiskCapacityPlausibility', () => {
  it('keeps the stable interface and treats new fields as optional', () => {
    const legacy = normalizeRiskCapacityPlausibility(INCONSISTENT_RAW);
    expect(legacy.status).toBe('inconsistent');
    expect(legacy.reason_code).toBe('RISK_CAPACITY_INCONSISTENT');
    expect(legacy.findings[0].check).toBe('INCOME_ABOVE_RECORDED');
    expect(legacy.verification_code).toBeUndefined();
    expect(legacy.resolution_actions).toBeUndefined();

    const future = normalizeRiskCapacityPlausibility({
      ...PARTIAL_RAW,
      verification_code: 'RISK_CAPACITY_NOT_VERIFIED',
      resolution_actions: ['Ausgaben erfassen.', '', 'Vollständigkeit bestätigen.'],
    });
    expect(future.verification_code).toBe('RISK_CAPACITY_NOT_VERIFIED');
    expect(future.resolution_actions).toEqual(['Ausgaben erfassen.', 'Vollständigkeit bestätigen.']);
  });

  it('is fail-closed: unknown or missing status is never consistent', () => {
    expect(normalizeRiskCapacityPlausibility({ status: 'ok' }).status).toBe('not_evaluable');
    expect(normalizeRiskCapacityPlausibility(null).status).toBe('not_evaluable');
    expect(normalizeRiskCapacityPlausibility({ status: 'consistent', findings: 'x' }).findings).toEqual([]);
  });
});

describe('fetchRiskCapacityPlausibility', () => {
  const originalFetch = globalThis.fetch;
  afterEach(() => {
    globalThis.fetch = originalFetch;
  });

  it('calls the mandate endpoint and normalizes the body', async () => {
    const fetchMock = vi.fn(async () => new Response(JSON.stringify(PARTIAL_RAW), { status: 200 }));
    globalThis.fetch = fetchMock as unknown as typeof fetch;
    const result = await fetchRiskCapacityPlausibility('m 1');
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(String((fetchMock.mock.calls[0] as unknown[])[0])).toBe(
      '/mandates/m%201/risk-capacity-plausibility',
    );
    expect(result.status).toBe('partial');
  });

  it('throws an ApiError on HTTP errors', async () => {
    globalThis.fetch = vi.fn(
      async () => new Response(JSON.stringify({ detail: 'Keine aktuelle Risikoprofilierung gefunden' }), { status: 404 }),
    ) as unknown as typeof fetch;
    await expect(fetchRiskCapacityPlausibility('m1')).rejects.toMatchObject({ status: 404 });
  });
});

describe('RiskCapacityPlausibilityView', () => {
  it.each([
    ['consistent', 'Konsistent'],
    ['partial', 'Teilweise geprüft'],
    ['inconsistent', 'Widerspruch'],
    ['not_evaluable', 'Nicht prüfbar'],
  ] as const)('shows status %s as %s', (status, label) => {
    const result = normalizeRiskCapacityPlausibility({ ...PARTIAL_RAW, status });
    render(<RiskCapacityPlausibilityView result={result} />);
    const panel = screen.getByRole('region', { name: 'Plausibilitätsprüfung Risikofähigkeit' });
    expect(panel).toHaveAttribute('data-status', status);
    expect(within(panel).getByText(label)).toBeInTheDocument();
    expect(within(panel).getByText(/nicht automatisch geändert/)).toBeInTheDocument();
  });

  it('lists findings with label, message and reason code for inconsistent', () => {
    render(<RiskCapacityPlausibilityView result={normalizeRiskCapacityPlausibility(INCONSISTENT_RAW)} />);
    expect(screen.getByText('Frage 3 Einkommen')).toBeInTheDocument();
    expect(screen.getByText(/erfasstes Einkommen liegt unter der Angabe/)).toBeInTheDocument();
    expect(screen.getByText(/1 Angabe weicht ab/)).toBeInTheDocument();
    expect(screen.getByText('RISK_CAPACITY_INCONSISTENT')).toBeInTheDocument();
  });

  it('lists open checks and optional next steps for partial', () => {
    const result: RiskCapacityPlausibility = {
      ...normalizeRiskCapacityPlausibility(PARTIAL_RAW),
      verification_code: 'RISK_CAPACITY_NOT_VERIFIED',
      resolution_actions: ['Ausgaben erfassen.'],
    };
    render(<RiskCapacityPlausibilityView result={result} />);
    expect(screen.getByText('Frage 5 Verpflichtungen')).toBeInTheDocument();
    expect(screen.getByText('Keine Ausgaben erfasst.')).toBeInTheDocument();
    expect(screen.getByText('Nächste Schritte')).toBeInTheDocument();
    expect(screen.getByText('Ausgaben erfassen.')).toBeInTheDocument();
    expect(screen.getByText('RISK_CAPACITY_NOT_VERIFIED')).toBeInTheDocument();
  });
});

describe('RiskCapacityPlausibilityNotice (Report, kompakt)', () => {
  const compact = (status: RiskCapacityPlausibilityCompact['status']): RiskCapacityPlausibilityCompact => ({
    status,
    reason_code: status === 'inconsistent' ? 'RISK_CAPACITY_INCONSISTENT' : null,
    finding_checks: status === 'inconsistent' ? ['LEVERAGE_HIGH'] : [],
    open_checks: status === 'partial' ? ['SAVINGS_RATE_ABOVE_RECORDED'] : [],
    note: '',
  });

  it.each(['consistent', 'not_evaluable'] as const)('renders nothing for %s', (status) => {
    const { container } = render(<RiskCapacityPlausibilityNotice data={compact(status)} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('renders nothing without data', () => {
    const { container } = render(<RiskCapacityPlausibilityNotice data={null} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('renders partial and inconsistent with topics and is print-hidden', () => {
    const { unmount } = render(<RiskCapacityPlausibilityNotice data={compact('partial')} />);
    const partial = screen.getByRole('region', { name: 'Plausibilitätsprüfung Risikofähigkeit' });
    expect(partial).toHaveClass('print:hidden');
    expect(screen.getByText('Frage 7 Sparquote')).toBeInTheDocument();
    unmount();
    render(<RiskCapacityPlausibilityNotice data={compact('inconsistent')} />);
    expect(screen.getByText('Widerspruch')).toBeInTheDocument();
    expect(screen.getByText('Verschuldung')).toBeInTheDocument();
  });
});

describe('RiskCapacityPlausibilityPanel (laedt Endpoint)', () => {
  const originalFetch = globalThis.fetch;
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn(async () => new Response(JSON.stringify(INCONSISTENT_RAW), { status: 200 }));
    globalThis.fetch = fetchMock as unknown as typeof fetch;
  });
  afterEach(() => {
    globalThis.fetch = originalFetch;
  });

  it('renders nothing and does not fetch without current assessment', () => {
    const { container } = render(<RiskCapacityPlausibilityPanel mandateId="m1" assessmentId={null} />);
    expect(container).toBeEmptyDOMElement();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('loads and refetches when the assessment changes', async () => {
    const { rerender } = render(<RiskCapacityPlausibilityPanel mandateId="m1" assessmentId="ra-1" />);
    expect(await screen.findByText('Widerspruch')).toBeInTheDocument();
    fetchMock.mockImplementationOnce(async () => new Response(JSON.stringify(PARTIAL_RAW), { status: 200 }));
    rerender(<RiskCapacityPlausibilityPanel mandateId="m1" assessmentId="ra-2" />);
    expect(await screen.findByText('Teilweise geprüft')).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it('shows an explicit unknown state on errors (never consistent)', async () => {
    fetchMock.mockImplementationOnce(async () => new Response('{}', { status: 500 }));
    render(<RiskCapacityPlausibilityPanel mandateId="m1" assessmentId="ra-1" />);
    expect(await screen.findByText(/nicht als geprüft werten/)).toBeInTheDocument();
    expect(screen.queryByText('Konsistent')).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// Einbindung: Risikoprofil-Editor (Berater) + Report-Sektion 12 (nur Berater)
// ---------------------------------------------------------------------------

const roleState = vi.hoisted(() => ({ canEdit: true }));
vi.mock('@/api/useUserRole', () => ({
  useUserRole: () => ({
    role: roleState.canEdit ? 'advisor' : 'readonly',
    canEdit: roleState.canEdit,
    loading: false,
    error: null,
  }),
}));

vi.mock('@/api/profiling', () => ({
  fetchCurrentRiskAssessment: vi.fn(),
  createRiskAssessment: vi.fn(),
  overrideRiskAssessment: vi.fn(),
}));

import { fetchCurrentRiskAssessment } from '@/api/profiling';
import { makeRisikoprofil, makeRiskAssessment } from '@/test/fixtures';
import { ProfilingPage } from './ProfilingPage';
import { Risikoprofil } from '@/pages/Risikoprofil';

describe('Einbindung', () => {
  const originalFetch = globalThis.fetch;
  afterEach(() => {
    globalThis.fetch = originalFetch;
    roleState.canEdit = true;
  });

  it('ProfilingPage shows the plausibility panel for the loaded assessment', async () => {
    const fetchMock = vi.fn(async () => new Response(JSON.stringify(PARTIAL_RAW), { status: 200 }));
    globalThis.fetch = fetchMock as unknown as typeof fetch;
    vi.mocked(fetchCurrentRiskAssessment).mockResolvedValueOnce(makeRiskAssessment());
    render(
      <MemoryRouter initialEntries={['/mandates/mandate-1/risikoprofil-editor']}>
        <Routes>
          <Route path="/mandates/:mandateId/risikoprofil-editor" element={<ProfilingPage />} />
        </Routes>
      </MemoryRouter>,
    );
    expect(await screen.findByText('Teilweise geprüft')).toBeInTheDocument();
    await waitFor(() =>
      expect(String((fetchMock.mock.calls[0] as unknown[])[0])).toBe(
        '/mandates/mandate-1/risk-capacity-plausibility',
      ),
    );
  });

  const partialCompact: RiskCapacityPlausibilityCompact = {
    status: 'partial',
    reason_code: null,
    finding_checks: [],
    open_checks: ['OBLIGATIONS_BELOW_RECORDED'],
    note: 'Plausibilitätsprüfung Risikofähigkeit (Beraterhinweis): …',
  };

  it('report section 12 shows the notice for advisors', () => {
    roleState.canEdit = true;
    render(
      <MemoryRouter>
        <Risikoprofil data={makeRisikoprofil()} capacityPlausibility={partialCompact} />
      </MemoryRouter>,
    );
    expect(screen.getByText('Teilweise geprüft')).toBeInTheDocument();
  });

  it('report section 12 hides the notice for read-only viewers', () => {
    roleState.canEdit = false;
    render(
      <MemoryRouter>
        <Risikoprofil data={makeRisikoprofil()} capacityPlausibility={partialCompact} />
      </MemoryRouter>,
    );
    expect(screen.queryByText('Teilweise geprüft')).toBeNull();
  });
});
