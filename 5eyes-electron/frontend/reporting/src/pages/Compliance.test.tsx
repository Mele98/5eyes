/**
 * Tests fuer Compliance-Dashboard (Sub-App Sektion 17).
 */
import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';

import { Compliance } from './Compliance';
import {
  makeSuitabilityCompliance,
  makeMethodologyModels,
  makeRecommendationMethodology,
  makeMandateLockStatus,
  makeLiquidityCascade,
} from '@/test/fixtures';


function renderCompliance(overrides: Partial<Parameters<typeof Compliance>[0]> = {}) {
  const props = {
    suitability: makeSuitabilityCompliance(),
    methodology: makeMethodologyModels(),
    recommendation: makeRecommendationMethodology(),
    mandateLock: makeMandateLockStatus(),
    liquidityCascade: makeLiquidityCascade(),
    ...overrides,
  };
  render(<Compliance {...props} />);
}


describe('Compliance-Dashboard', () => {
  it('renders all 5 audit-cards', () => {
    renderCompliance();
    expect(screen.getByTestId('compliance-suitability')).toBeInTheDocument();
    expect(screen.getByTestId('compliance-methodology')).toBeInTheDocument();
    expect(screen.getByTestId('compliance-recommendation')).toBeInTheDocument();
    expect(screen.getByTestId('compliance-mandate-lock')).toBeInTheDocument();
    expect(screen.getByTestId('compliance-liquidity')).toBeInTheDocument();
  });

  it('renders overall status banner', () => {
    renderCompliance();
    expect(screen.getByTestId('compliance-overall-banner')).toBeInTheDocument();
  });

  it('overall banner shows "Audit-Bestand sauber" with all-clean defaults', () => {
    renderCompliance();
    expect(screen.getByText(/Audit-Bestand sauber/i)).toBeInTheDocument();
  });

  it('overall banner shows handlungsbedarf when suitability not compliant', () => {
    renderCompliance({
      suitability: {
        ...makeSuitabilityCompliance(),
        is_compliant: false,
      },
    });
    expect(screen.getByText(/Audit-Handlungsbedarf/i)).toBeInTheDocument();
  });

  it('overall banner shows handlungsbedarf when liquidity emergency', () => {
    renderCompliance({
      liquidityCascade: {
        ...makeLiquidityCascade(),
        stage: 'emergency',
        warning_required: true,
      },
    });
    expect(screen.getByText(/Audit-Handlungsbedarf/i)).toBeInTheDocument();
  });

  it('mandate-lock shows lock_reasons when not editable', () => {
    renderCompliance({
      mandateLock: {
        is_editable: false,
        lock_reasons: ['mandate_closed'],
        lock_reason_labels: {
          mandate_closed: 'Mandat ist geschlossen (closed_at gesetzt).',
        },
        mandate_status: 'Geschlossen',
        latest_optimizer_status: null,
        fidleg_basis: 'Art. 16 / Art. 11 FIDLEG',
      },
    });
    expect(screen.getByText('mandate_closed')).toBeInTheDocument();
    expect(screen.getByText(/Mandat ist geschlossen/i)).toBeInTheDocument();
  });

  it('mandate-lock shows "Keine Sperren" when editable', () => {
    renderCompliance();
    expect(screen.getByText(/Keine Sperren aktiv/i)).toBeInTheDocument();
  });

  it('liquidity-card shows warning-box when warning_required', () => {
    renderCompliance({
      liquidityCascade: {
        ...makeLiquidityCascade(),
        stage: 'emergency',
        liquidity_bps: 800,
        over_hard_cap_by_bps: 500,
        warning_required: true,
        beratungsgespraech_pruefen: true,
      },
    });
    expect(screen.getByText(/Beratungsgespraech pruefen/i)).toBeInTheDocument();
  });

  it('methodology-card shows "Keine CMA-Daten" when models empty', () => {
    renderCompliance();
    expect(screen.getByText(/Keine CMA-Daten verfuegbar/i)).toBeInTheDocument();
  });

  it('methodology-card renders methodology_notes when present', () => {
    renderCompliance({
      methodology: {
        ...makeMethodologyModels(),
        active_count: 1,
        methodology_notes: ['Bond-Renditen aus Yield-Curve (Nelson-Siegel).'],
      },
    });
    expect(screen.getByText(/Bond-Renditen aus Yield-Curve/i)).toBeInTheDocument();
  });

  it('recommendation-card shows "Noch kein aktiver Run" with empty default', () => {
    renderCompliance();
    expect(screen.getByText(/Noch kein aktiver Optimizer-Run/i)).toBeInTheDocument();
  });

  it('recommendation-card shows run-details when latest_active_run set', () => {
    renderCompliance({
      recommendation: {
        ...makeRecommendationMethodology(),
        latest_active_run: {
          run_id: 'r-1',
          method: 'stochastic',
          status: 'converged',
          status_label: 'konvergiert',
          is_acceptable: true,
          seed: 42,
          n_paths: 1000,
          n_iterations: 250,
        } as unknown as Record<string, unknown>,
        total_runs: 5,
        active_count: 1,
      },
    });
    expect(screen.getByText('stochastic')).toBeInTheDocument();
    expect(screen.getByText('konvergiert')).toBeInTheDocument();
    expect(screen.getByText('42')).toBeInTheDocument();
  });

  it('shows fidleg_basis on each card', () => {
    renderCompliance();
    expect(screen.getByText(/Art. 11\/13\/16 FIDLEG/)).toBeInTheDocument();
    expect(screen.getByText(/Art. 16 FIDLEG/)).toBeInTheDocument();
    expect(screen.getByText(/Art. 11 \/ Art. 13 FIDLEG/)).toBeInTheDocument();
  });
});
