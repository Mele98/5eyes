import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import {
  buildRiskAssessmentPayload,
  ProfilingPage,
} from './ProfilingPage';
import {
  conservativeRiskProfile,
  riskProfileForScoreX10,
} from './RiskSummary';
import { makeRiskAssessment } from '@/test/fixtures';

vi.mock('@/api/profiling', () => ({
  fetchCurrentRiskAssessment: vi.fn(),
  createRiskAssessment: vi.fn(),
  overrideRiskAssessment: vi.fn(),
}));

import {
  createRiskAssessment,
  fetchCurrentRiskAssessment,
} from '@/api/profiling';

const mockedFetchCurrent = vi.mocked(fetchCurrentRiskAssessment);
const mockedCreate = vi.mocked(createRiskAssessment);

beforeEach(() => {
  vi.clearAllMocks();
});

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/mandates/mandate-1/risikoprofil-editor']}>
      <Routes>
        <Route
          path="/mandates/:mandateId/risikoprofil-editor"
          element={<ProfilingPage />}
        />
      </Routes>
    </MemoryRouter>,
  );
}

describe('Profiling score mapping', () => {
  it.each([
    [10, 'Kapitalschutz'],
    [24, 'Kapitalschutz'],
    [25, 'Defensiv'],
    [44, 'Defensiv'],
    [45, 'Ausgewogen'],
    [64, 'Ausgewogen'],
    [65, 'Wachstumsorientiert'],
    [84, 'Wachstumsorientiert'],
    [85, 'Dynamisch'],
    [94, 'Dynamisch'],
    [95, 'Aktien'],
    [100, 'Aktien'],
  ])('maps %i to %s like backend thresholds', (score, profile) => {
    expect(riskProfileForScoreX10(score)).toBe(profile);
  });

  it('override uses the more conservative lower profile', () => {
    expect(conservativeRiskProfile('Dynamisch', 'Defensiv')).toBe('Defensiv');
    expect(conservativeRiskProfile('Defensiv', 'Dynamisch')).toBe('Defensiv');
  });
});

describe('Profiling payload', () => {
  it('builds all current backend answer markers', () => {
    const payload = buildRiskAssessmentPayload({
      q_income_points: 2,
      q_obligations_points: 2,
      q_savings_points: 6,
      q_wealth_points: 6,
      investment_horizon_label: '6 bis 7 Jahre',
      investment_horizon_years: 6,
      q_investment_goal_points: 3,
      q_risk_preference_points: 3,
      q_risk_behavior_points: 3,
    });
    expect(payload.answers?.map((answer) => answer.question_number)).toEqual([
      1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11,
    ]);
    expect(payload.knowledge_services_json).toBeTruthy();
    expect(payload.knowledge_instruments_json).toBeTruthy();
    expect(payload.income_sources_json).toBeTruthy();
  });
});

describe('ProfilingPage save flow', () => {
  it('does not show score or point labels in the questionnaire', async () => {
    mockedFetchCurrent.mockResolvedValueOnce(makeRiskAssessment());
    const { container } = renderPage();
    await screen.findByText('Aktuelles Risikoprofil geladen.');

    expect(container).not.toHaveTextContent(/\bScore\b|Punkte/);
  });

  it('saves successfully and updates the live status', async () => {
    mockedFetchCurrent.mockResolvedValueOnce(makeRiskAssessment());
    mockedCreate.mockResolvedValueOnce(
      makeRiskAssessment({ final_profile: 'Wachstumsorientiert' }),
    );

    renderPage();
    await screen.findByText('Aktuelles Risikoprofil geladen.');

    fireEvent.click(screen.getByRole('button', { name: /speichern/i }));

    await waitFor(() => {
      expect(mockedCreate).toHaveBeenCalledWith(
        'mandate-1',
        expect.objectContaining({ q_income_points: 2 }),
      );
    });
    expect(await screen.findByText('Risikoprofil gespeichert.')).toBeInTheDocument();
    expect(screen.getByText('Wachstumsorientiert')).toBeInTheDocument();
  });

  it('shows save failure in alert and live region', async () => {
    mockedFetchCurrent.mockRejectedValueOnce({ status: 404 });
    mockedCreate.mockRejectedValueOnce(new Error('Backend 422'));

    renderPage();
    await screen.findByText('Neues Risikoprofil vorbereiten.');

    fireEvent.click(screen.getByRole('button', { name: /speichern/i }));

    expect(await screen.findByRole('alert')).toHaveTextContent('Backend 422');
    expect(screen.getByText('Speichern fehlgeschlagen.')).toBeInTheDocument();
  });
});
