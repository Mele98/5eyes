/**
 * Render- + a11y-Tests für den WealthInflowEditor (Roadmap #54).
 */
import { render, screen, fireEvent } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '@/api/client';
import type { WealthInflowRecord } from '@/api/types';

vi.mock('@/api/wealthInflow', () => ({
  fetchWealthInflows: vi.fn(),
  createWealthInflow: vi.fn(),
  updateWealthInflow: vi.fn(),
  deleteWealthInflow: vi.fn(),
}));

import { fetchWealthInflows } from '@/api/wealthInflow';
import { WealthInflowEditor } from './WealthInflowEditor';

const fetchMock = vi.mocked(fetchWealthInflows);

function makeInflow(overrides: Partial<WealthInflowRecord> = {}): WealthInflowRecord {
  return {
    id: 'i1',
    client_id: 'c1',
    mandate_id: null,
    label: 'Erbschaft Tante',
    source_type: 'Erbschaft',
    amount_rappen: 25_000_000,
    expected_year: 2032,
    is_recurring: 0,
    frequency: null,
    duration_years: null,
    value_mode: 'nominal',
    notes: null,
    is_active: 1,
    created_at: '2026-06-22T00:00:00.000Z',
    updated_at: '2026-06-22T00:00:00.000Z',
    ...overrides,
  };
}

beforeEach(() => {
  fetchMock.mockReset();
});

afterEach(() => {
  vi.clearAllMocks();
});

describe('WealthInflowEditor', () => {
  it('zeigt einen Empty-State ohne Zuflüsse', async () => {
    fetchMock.mockResolvedValue([]);
    render(<WealthInflowEditor clientId="c1" />);
    expect(await screen.findByText(/Noch keine Zuflüsse erfasst/)).toBeInTheDocument();
  });

  it('rendert Zuflüsse in einer Tabelle', async () => {
    fetchMock.mockResolvedValue([makeInflow()]);
    render(<WealthInflowEditor clientId="c1" />);
    expect(await screen.findByText('Erbschaft Tante')).toBeInTheDocument();
    expect(screen.getByRole('table', { name: 'Erwartete Vermögenszuflüsse' })).toBeInTheDocument();
  });

  it('zeigt einen Fehler bei ApiError', async () => {
    fetchMock.mockRejectedValue(new ApiError(500, 'kaputt'));
    render(<WealthInflowEditor clientId="c1" />);
    expect(await screen.findByText('kaputt')).toBeInTheDocument();
  });

  it('öffnet den Form-Dialog und blendet Frequenz/Dauer erst bei "Wiederkehrend" ein', async () => {
    fetchMock.mockResolvedValue([]);
    render(<WealthInflowEditor clientId="c1" />);
    await screen.findByText(/Noch keine Zuflüsse erfasst/);
    fireEvent.click(screen.getByRole('button', { name: 'Neuer Zufluss' }));
    const dialog = screen.getByRole('dialog', { name: 'Neuen Zufluss anlegen' });
    expect(dialog).toBeInTheDocument();
    // Frequenz erst nach Aktivierung von "Wiederkehrend"
    expect(screen.queryByLabelText('Dauer (Jahre)')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('checkbox', { name: 'Wiederkehrend' }));
    expect(screen.getByLabelText('Dauer (Jahre)')).toBeInTheDocument();
  });

  it('hat eine Status-Live-Region', async () => {
    fetchMock.mockResolvedValue([]);
    render(<WealthInflowEditor clientId="c1" />);
    await screen.findByText(/Noch keine Zuflüsse erfasst/);
    expect(screen.getByRole('status')).toBeInTheDocument();
  });
});
