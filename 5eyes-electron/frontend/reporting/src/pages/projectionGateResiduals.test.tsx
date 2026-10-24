/**
 * MC-CONTEXT-001 / GOAL-PUBLICATION-001 (Codex-Closure-Review PR #663):
 * bei ausgeblendetem Projection-Gate zeigt der Report weder eine
 * scheinbar gemessene 0-%-Zielerreichung noch das Risikobudget einer alten
 * Allokation -- stattdessen "—" und den gemeinsamen Gate-Hinweis.
 */
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';

vi.mock('@/api/useUserRole', () => ({
  useUserRole: () => ({
    role: 'advisor',
    canEdit: false,
    loading: false,
    error: null,
  }),
}));

import type { ProjectionGateData } from '@/api/types';
import { makeGoals, makeRisikoprofil } from '@/test/fixtures';

import { Goals } from './Goals';
import { Risikoprofil } from './Risikoprofil';

const HINT = 'Soll-Allokation veraltet – Projektionen ausgeblendet.';

function gate(hidden: boolean): ProjectionGateData {
  return {
    status: hidden ? 'stale' : 'current',
    reason_code: hidden ? 'assessment' : null,
    projections_hidden: hidden,
    hinweis: hidden ? HINT : null,
    note: null,
    hidden_channels: hidden
      ? [
          'goal_based_investing.goal_achievement_score_bps',
          'risikoprofilierung.risky_fraction_bps',
        ]
      : [],
    historical_ist_channels: [],
  };
}

function withRouter(ui: React.ReactNode) {
  return <MemoryRouter>{ui}</MemoryRouter>;
}

describe('Zielerreichung gesamt', () => {
  it('null-Score ohne Gate: "—", nie 0 %', () => {
    render(withRouter(<Goals data={{ ...makeGoals(), goal_achievement_score_bps: null }} />));
    expect(screen.getByTestId('achievement-score-value')).toHaveTextContent('—');
    expect(screen.getByTestId('achievement-score-value')).not.toHaveTextContent('0');
  });

  it('Gate ausgeblendet: "—" plus Gate-Hinweis, auch wenn ein Wert mitkommt', () => {
    render(
      withRouter(
        <Goals
          data={{ ...makeGoals(), goal_achievement_score_bps: 0 }}
          projectionGate={gate(true)}
        />,
      ),
    );
    expect(screen.getByTestId('achievement-score-value')).toHaveTextContent('—');
    expect(screen.getByTestId('achievement-score-note')).toHaveTextContent(HINT);
  });

  it('Positivkontrolle: Gate offen -> numerischer Score', () => {
    render(withRouter(<Goals data={makeGoals()} projectionGate={gate(false)} />));
    expect(screen.getByTestId('achievement-score-value')).not.toHaveTextContent('—');
    expect(screen.getByTestId('achievement-score-note')).not.toHaveTextContent(HINT);
  });
});

describe('Risikoprofil: Risikobudget', () => {
  it('Gate ausgeblendet: alte Risikoquote nicht sichtbar, Hinweis statt Wert', () => {
    render(withRouter(<Risikoprofil data={makeRisikoprofil()} projectionGate={gate(true)} />));
    expect(screen.queryByText('42.5 %')).toBeNull();
    expect(screen.getByTestId('risk-budget-gate-hint')).toHaveTextContent(HINT);
    // Assessmentdaten bleiben sichtbar.
    expect(screen.getByText('62 / 100')).toBeInTheDocument();
  });

  it('Positivkontrolle: Gate offen -> Risikobudget sichtbar, kein Hinweis', () => {
    render(withRouter(<Risikoprofil data={makeRisikoprofil()} projectionGate={gate(false)} />));
    expect(screen.getByText('42.5 %')).toBeInTheDocument();
    expect(screen.queryByTestId('risk-budget-gate-hint')).toBeNull();
  });
});
