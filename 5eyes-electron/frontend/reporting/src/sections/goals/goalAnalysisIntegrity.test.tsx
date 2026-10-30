/**
 * GOAL-ANALYSIS-INTEGRITY-UI-REACT-001: ruhiger Berater-Hinweis in der
 * Zielanalyse (Sektion 11), wenn die gespeicherte Zielanalyse oder der
 * Shadow-Container der aktuellen Strategie ihren Integritaetsnachweis
 * verletzen (GET /mandates/{id}/target-allocation/current/analysis-integrity).
 */
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { fetchAnalysisIntegrity } from '@/api/allocation';
import type { AnalysisIntegrityReport } from '@/api/types';
import { Goals } from '@/pages/Goals';
import { makeGoals } from '@/test/fixtures';
import { GoalAnalysisIntegrity, GoalAnalysisIntegrityNotice } from './GoalAnalysisIntegrityNotice';

const role = vi.hoisted(() => ({ canEdit: true }));
vi.mock('@/api/useUserRole', () => ({
  useUserRole: () => ({ role: 'advisor', canEdit: role.canEdit, loading: false, error: null }),
}));

const mismatch: AnalysisIntegrityReport = {
  goal_analysis: 'integrity_mismatch',
  shadow_analysis: 'verified',
  needs_attention: true,
  label: 'Zielanalyse nicht verifizierbar',
  text:
    'Die gespeicherte Zielanalyse dieser Strategie stimmt nicht mit ihrem Integritaetsnachweis ueberein und wird deshalb nicht angezeigt. Bitte die Strategie neu berechnen.',
};

const verified: AnalysisIntegrityReport = {
  goal_analysis: 'verified',
  shadow_analysis: 'not_applicable',
  needs_attention: false,
  label: null,
  text: null,
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

describe('GoalAnalysisIntegrityNotice', () => {
  it('shows the backend label and text on an integrity mismatch, never in print', () => {
    render(<GoalAnalysisIntegrityNotice data={mismatch} />);
    const note = screen.getByRole('status');
    expect(note).toHaveTextContent('Zielanalyse nicht verifizierbar');
    expect(note).toHaveTextContent(/Bitte die Strategie neu berechnen/);
    expect(note).toHaveAttribute('data-integrity', 'integrity_mismatch|verified');
    expect(note.className).toContain('print:hidden');
  });

  it('falls back to the fixed label when the backend sends none', () => {
    render(<GoalAnalysisIntegrityNotice data={{ ...mismatch, label: null, text: null }} />);
    expect(screen.getByRole('status')).toHaveTextContent('Zielanalyse nicht verifizierbar');
  });

  it('renders nothing for a verified analysis or without a report', () => {
    const { container, rerender } = render(<GoalAnalysisIntegrityNotice data={verified} />);
    expect(container).toBeEmptyDOMElement();
    rerender(<GoalAnalysisIntegrityNotice data={null} />);
    expect(container).toBeEmptyDOMElement();
  });
});

describe('fetchAnalysisIntegrity', () => {
  it('reads the analysis-integrity endpoint of the current target allocation', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ target_allocation_id: 'ta-1', ...mismatch }));
    vi.stubGlobal('fetch', fetchMock);
    await expect(fetchAnalysisIntegrity('m 1')).resolves.toMatchObject(mismatch);
    expect(fetchMock.mock.calls[0][0]).toBe(
      '/mandates/m%201/target-allocation/current/analysis-integrity',
    );
  });

  it('returns null when there is no current target allocation (404)', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse({ detail: 'x' }, 404)));
    await expect(fetchAnalysisIntegrity('m-1')).resolves.toBeNull();
  });

  it('rejects a report without a boolean needs_attention', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(jsonResponse({ ...mismatch, needs_attention: 'yes' })),
    );
    await expect(fetchAnalysisIntegrity('m-1')).rejects.toThrow();
  });
});

describe('GoalAnalysisIntegrity (Container)', () => {
  it('loads the report for the mandate and shows the hint', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse(mismatch)));
    render(<GoalAnalysisIntegrity mandateId="m-1" />);
    await waitFor(() =>
      expect(screen.getByRole('status')).toHaveTextContent('Zielanalyse nicht verifizierbar'),
    );
  });

  it('stays quiet when loading fails', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ detail: 'kaputt' }, 500));
    vi.stubGlobal('fetch', fetchMock);
    const { container } = render(<GoalAnalysisIntegrity mandateId="m-1" />);
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });

  it('stays quiet on a network error', async () => {
    const fetchMock = vi.fn().mockRejectedValue(new TypeError('offline'));
    vi.stubGlobal('fetch', fetchMock);
    const { container } = render(<GoalAnalysisIntegrity mandateId="m-1" />);
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });
});

describe('Goals (Sektion 11) zeigt den Hinweis in der Berater-Ansicht', () => {
  it('loads and shows the hint for advisors', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(mismatch));
    vi.stubGlobal('fetch', fetchMock);
    render(
      <MemoryRouter>
        <Goals data={makeGoals()} mandateId="m-1" />
      </MemoryRouter>,
    );
    const label = await screen.findByText('Zielanalyse nicht verifizierbar');
    expect(label.closest('[role="status"]')?.className).toContain('print:hidden');
    expect(fetchMock.mock.calls[0][0]).toBe(
      '/mandates/m-1/target-allocation/current/analysis-integrity',
    );
  });

  it('does not load anything in the read-only view', async () => {
    role.canEdit = false;
    const fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);
    render(
      <MemoryRouter>
        <Goals data={makeGoals()} mandateId="m-1" />
      </MemoryRouter>,
    );
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(fetchMock).not.toHaveBeenCalled();
    expect(screen.queryByText('Zielanalyse nicht verifizierbar')).toBeNull();
  });
});
