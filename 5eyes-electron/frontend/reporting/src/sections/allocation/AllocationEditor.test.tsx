/**
 * Render- + a11y-Tests für den AllocationEditor (Track #67).
 */
import { render, screen, fireEvent } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '@/api/client';
import type { TargetAllocationRecord } from '@/api/types';

vi.mock('@/api/allocation', () => ({
  fetchCurrentAllocation: vi.fn(),
  saveTargetAllocation: vi.fn(),
  generateAllocation: vi.fn(),
  runSensitivity: vi.fn(),
  flattenDetail: (d: unknown) => String(d),
}));

import {
  fetchCurrentAllocation,
  generateAllocation,
} from '@/api/allocation';
import { AllocationEditor } from './AllocationEditor';

const fetchMock = vi.mocked(fetchCurrentAllocation);
const generateMock = vi.mocked(generateAllocation);

function makeRecord(overrides: Partial<TargetAllocationRecord> = {}): TargetAllocationRecord {
  return {
    id: 'ta1',
    mandate_id: 'm1',
    version: 1,
    is_current: 1,
    target_equities_bps: 4000,
    target_bonds_bps: 3000,
    target_real_estate_bps: 1000,
    target_alternatives_bps: 1000,
    target_liquidity_bps: 1000,
    band_equities_min_bps: 3000,
    band_equities_max_bps: 5000,
    band_bonds_min_bps: 2000,
    band_bonds_max_bps: 4000,
    band_real_estate_min_bps: 0,
    band_real_estate_max_bps: 2000,
    band_alternatives_min_bps: 0,
    band_alternatives_max_bps: 2000,
    band_liquidity_min_bps: 0,
    band_liquidity_max_bps: 2000,
    risky_fraction_bps: 6000,
    based_on_assessment_id: 'ra-1',
    policy_id: 'pol-1',
    set_by: 'advisor',
    set_at: '2026-06-22T00:00:00.000Z',
    created_at: '2026-06-22T00:00:00.000Z',
    updated_at: '2026-06-22T00:00:00.000Z',
    ...overrides,
  };
}

beforeEach(() => {
  fetchMock.mockReset();
  generateMock.mockReset();
});

afterEach(() => {
  vi.clearAllMocks();
});

describe('AllocationEditor', () => {
  it('rendert die editierbare Tabelle mit beschrifteten Feldern', async () => {
    fetchMock.mockResolvedValue(makeRecord());
    render(<AllocationEditor mandateId="m1" />);
    expect(await screen.findByRole('table', { name: 'SOLL-Allokation pro Anlageklasse' })).toBeInTheDocument();
    expect(screen.getByLabelText('Aktien Ziel in bps')).toHaveValue(4000);
    expect(screen.getByLabelText('Liquidität Max in bps')).toHaveValue(2000);
  });

  it('zeigt einen Empty-State bei 404 (keine SOLL)', async () => {
    fetchMock.mockRejectedValue(new ApiError(404, 'Keine Soll-Allokation gefunden'));
    render(<AllocationEditor mandateId="m1" />);
    expect(await screen.findByText(/Noch keine SOLL-Allokation/)).toBeInTheDocument();
  });

  it('zeigt einen Fehler bei anderem ApiError', async () => {
    fetchMock.mockRejectedValue(new ApiError(500, 'kaputt'));
    render(<AllocationEditor mandateId="m1" />);
    expect(await screen.findByText('kaputt')).toBeInTheDocument();
  });

  it('hat eine Status-Live-Region (role=status)', async () => {
    fetchMock.mockResolvedValue(makeRecord());
    render(<AllocationEditor mandateId="m1" />);
    await screen.findByRole('table');
    expect(screen.getByRole('status')).toBeInTheDocument();
  });

  it('füllt den Editor mit dem Optimizer-Vorschlag vor', async () => {
    fetchMock.mockRejectedValue(new ApiError(404, 'keine'));
    generateMock.mockResolvedValue({
      target_allocation: makeRecord({ target_equities_bps: 5000, target_bonds_bps: 2000 }),
      expected_return_bps: 350,
      expected_volatility_bps: 900,
      risky_fraction_total_bps: 6000,
      limiting_factor: null,
      reasoning: [],
      messages: [],
    });
    render(<AllocationEditor mandateId="m1" />);
    await screen.findByText(/Noch keine SOLL-Allokation/);
    fireEvent.click(screen.getByRole('button', { name: 'Optimizer-Vorschlag' }));
    expect(await screen.findByLabelText('Aktien Ziel in bps')).toHaveValue(5000);
    expect(generateMock).toHaveBeenCalledWith('m1');
  });
});
