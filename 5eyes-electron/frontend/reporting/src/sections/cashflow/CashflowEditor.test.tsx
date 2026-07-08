/**
 * Render- + a11y-Tests für den CashflowEditor (Track #68).
 */
import { render, screen, fireEvent } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '@/api/client';
import type { CashflowRecord, DerivedCashflow } from '@/api/types';

vi.mock('@/api/cashflow', () => ({
  fetchCashflows: vi.fn(),
  fetchDerivedCashflows: vi.fn(),
  createCashflow: vi.fn(),
  updateCashflow: vi.fn(),
  deleteCashflow: vi.fn(),
}));

import { fetchCashflows, fetchDerivedCashflows } from '@/api/cashflow';
import { CashflowEditor } from './CashflowEditor';

const cfMock = vi.mocked(fetchCashflows);
const derivedMock = vi.mocked(fetchDerivedCashflows);

function makeCashflow(overrides: Partial<CashflowRecord> = {}): CashflowRecord {
  return {
    id: 'cf1',
    client_id: 'c1',
    cashflow_type: 'Expense',
    label: 'Lebenshaltung',
    amount_rappen: 3_600_000,
    gross_amount_rappen: null,
    tax_amount_rappen: null,
    timing_precision: null,
    currency: 'CHF',
    frequency: 'jährlich',
    nature: 'wiederkehrend',
    valid_from: null,
    valid_until: '2045-12-31',
    is_inflation_linked: 1,
    notes: null,
    is_active: 1,
    created_at: '2026-06-22T00:00:00.000Z',
    updated_at: '2026-06-22T00:00:00.000Z',
    ...overrides,
  };
}

function makeDerived(): DerivedCashflow {
  return {
    id: 'd1',
    client_id: 'c1',
    cashflow_type: 'Expense',
    label: 'Hypothekarzins',
    amount_rappen: 1_200_000,
    currency: 'CHF',
    frequency: 'jährlich',
    nature: 'wiederkehrend',
    valid_from: null,
    valid_until: null,
    is_inflation_linked: 0,
    notes: null,
    is_active: 1,
    is_derived: 1,
    source: 'wealth_position',
    origin_position_id: 'pos1',
    origin_position_type: 'mortgage',
  };
}

beforeEach(() => {
  cfMock.mockReset();
  derivedMock.mockReset();
  derivedMock.mockResolvedValue([]);
});

afterEach(() => {
  vi.clearAllMocks();
});

describe('CashflowEditor', () => {
  it('zeigt einen Empty-State ohne manuelle Cashflows', async () => {
    cfMock.mockResolvedValue([]);
    render(<CashflowEditor clientId="c1" />);
    expect(await screen.findByText(/Noch keine manuellen Cashflows/)).toBeInTheDocument();
  });

  it('rendert manuelle Cashflows in einer Tabelle', async () => {
    cfMock.mockResolvedValue([makeCashflow()]);
    render(<CashflowEditor clientId="c1" />);
    expect(await screen.findByText('Lebenshaltung')).toBeInTheDocument();
    expect(screen.getByRole('table', { name: 'Manuelle Cashflows' })).toBeInTheDocument();
  });

  it('rendert read-only abgeleitete Cashflows als eigene Sektion', async () => {
    cfMock.mockResolvedValue([]);
    derivedMock.mockResolvedValue([makeDerived()]);
    render(<CashflowEditor clientId="c1" />);
    expect(await screen.findByText('Hypothekarzins')).toBeInTheDocument();
    expect(
      screen.getByRole('table', { name: 'Abgeleitete Cashflows (read-only)' }),
    ).toBeInTheDocument();
  });

  it('zeigt einen Fehler bei ApiError', async () => {
    cfMock.mockRejectedValue(new ApiError(500, 'kaputt'));
    render(<CashflowEditor clientId="c1" />);
    expect(await screen.findByText('kaputt')).toBeInTheDocument();
  });

  it('öffnet den Form-Dialog über "Neuer Cashflow"', async () => {
    cfMock.mockResolvedValue([]);
    render(<CashflowEditor clientId="c1" />);
    await screen.findByText(/Noch keine manuellen Cashflows/);
    fireEvent.click(screen.getByRole('button', { name: 'Neuer Cashflow' }));
    expect(screen.getByRole('dialog', { name: 'Neuen Cashflow anlegen' })).toBeInTheDocument();
  });

  it('hat eine Status-Live-Region', async () => {
    cfMock.mockResolvedValue([]);
    render(<CashflowEditor clientId="c1" />);
    await screen.findByText(/Noch keine manuellen Cashflows/);
    expect(screen.getByRole('status')).toBeInTheDocument();
  });
});
