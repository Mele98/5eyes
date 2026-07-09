import { render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ProfilingPage } from './ProfilingPage';
import { makeRiskAssessment } from '@/test/fixtures';

vi.mock('@/api/profiling', () => ({
  fetchCurrentRiskAssessment: vi.fn(),
  createRiskAssessment: vi.fn(),
  overrideRiskAssessment: vi.fn(),
}));

import { fetchCurrentRiskAssessment } from '@/api/profiling';

const mockedFetchCurrent = vi.mocked(fetchCurrentRiskAssessment);

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

describe('ProfilingPage a11y', () => {
  it('renders labelled form controls', async () => {
    mockedFetchCurrent.mockResolvedValueOnce(makeRiskAssessment());
    renderPage();

    expect(screen.getByLabelText('Einkommenssituation')).toBeInTheDocument();
    expect(screen.getByLabelText('Verpflichtungen')).toBeInTheDocument();
    expect(screen.getByLabelText('Sparquote')).toBeInTheDocument();
    expect(screen.getByLabelText('Freie Vermoegensbasis')).toBeInTheDocument();
    expect(screen.getByLabelText('Anlagehorizont')).toBeInTheDocument();
    expect(screen.getByLabelText('Anlageziel')).toBeInTheDocument();
    expect(screen.getByLabelText('Umgang mit Risiko')).toBeInTheDocument();
    expect(screen.getByLabelText('Verhalten bei Verlusten')).toBeInTheDocument();
  });

  it('has live regions for save status and errors', () => {
    mockedFetchCurrent.mockRejectedValueOnce({ status: 404 });
    renderPage();

    expect(screen.getByRole('status')).toHaveAttribute('aria-live', 'polite');
    expect(screen.queryByRole('alert')).toBeNull();
  });
});
