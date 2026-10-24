/**
 * RISK-CAPACITY-REPORT-001: Plausibilitaetspruefung Risikofaehigkeit im
 * Advisory-Report (kompakter Beraterhinweis). Die fruehere Endpoint-Ansicht
 * gehoerte zum entfernten Risikoprofil-Editor (O-1).
 */
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { RiskCapacityPlausibilityCompact } from '@/api/riskCapacityPlausibility';
import { RiskCapacityPlausibilityNotice } from './RiskCapacityPlausibilityPanel';

describe('RiskCapacityPlausibilityNotice (Report, kompakt)', () => {
  const compact = (status: RiskCapacityPlausibilityCompact['status']): RiskCapacityPlausibilityCompact => ({
    status,
    reason_code: status === 'inconsistent' ? 'RISK_CAPACITY_INCONSISTENT' : null,
    finding_checks: status === 'inconsistent' ? ['LEVERAGE_HIGH'] : [],
    open_checks: status === 'partial' ? ['SAVINGS_RATE_ABOVE_RECORDED'] : [],
    note: '',
  });

  it('renders nothing for consistent', () => {
    const status = 'consistent' as const;
    const { container } = render(<RiskCapacityPlausibilityNotice data={compact(status)} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('renders a data request for not_evaluable (never silent)', () => {
    render(<RiskCapacityPlausibilityNotice data={compact('not_evaluable')} />);
    expect(screen.getByText('Nicht prüfbar')).toBeInTheDocument();
    expect(screen.getByText(/mangels Daten nicht prüfbar – Finanzdaten erfassen/)).toBeInTheDocument();
  });

  it('renders a capture request when no current assessment exists', () => {
    render(
      <RiskCapacityPlausibilityNotice
        data={{
          ...compact('not_evaluable'),
          reason_code: 'NO_CURRENT_RISK_ASSESSMENT',
          availability: 'missing_input',
          risk_assessment_id: null,
        }}
      />,
    );
    expect(screen.getByText('Nicht prüfbar')).toBeInTheDocument();
    expect(screen.getByText(/Kein aktuelles Risikoprofil vorhanden – Risikoprofil erfassen/)).toBeInTheDocument();
    expect(screen.getByText('NO_CURRENT_RISK_ASSESSMENT')).toBeInTheDocument();
  });

  it('labels a block that evaluates another profile than the suitability reference', () => {
    render(
      <RiskCapacityPlausibilityNotice
        data={{ ...compact('partial'), risk_assessment_id: 'ra-2', suitability_reference_match: false }}
      />,
    );
    expect(screen.getByText(/nicht auf das in der Eignungsprüfung referenzierte Profil/)).toBeInTheDocument();
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

import { makeRisikoprofil } from '@/test/fixtures';
import { Risikoprofil } from '@/pages/Risikoprofil';

describe('Einbindung', () => {
  afterEach(() => {
    roleState.canEdit = true;
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
