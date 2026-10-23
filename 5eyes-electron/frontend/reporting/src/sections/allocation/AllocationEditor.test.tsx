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
  saveTargetAllocation,
} from '@/api/allocation';
import { AllocationEditor } from './AllocationEditor';

const fetchMock = vi.mocked(fetchCurrentAllocation);
const generateMock = vi.mocked(generateAllocation);
const saveMock = vi.mocked(saveTargetAllocation);

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
  saveMock.mockReset();
});

afterEach(() => {
  vi.clearAllMocks();
});

describe('AllocationEditor', () => {
  it('rendert die editierbare Tabelle mit beschrifteten Feldern', async () => {
    fetchMock.mockResolvedValue(makeRecord());
    render(<AllocationEditor mandateId="m1" />);
    expect(await screen.findByRole('table', { name: 'SOLL-Allokation pro Anlageklasse' })).toBeInTheDocument();
    expect(screen.getByLabelText('Aktien Ziel in %')).toHaveValue('40.0');
    expect(screen.getByLabelText('Liquidität Maximum in %')).toHaveValue('20.0');
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
    expect(await screen.findByLabelText('Aktien Ziel in %')).toHaveValue('50.0');
    expect(generateMock).toHaveBeenCalledWith('m1');
  });

  it('verlangt eine Begründung vor dem Speichern (MANUAL-SAVE-DEADEND-001)', async () => {
    fetchMock.mockResolvedValue(makeRecord());
    render(<AllocationEditor mandateId="m1" />);
    await screen.findByRole('table');
    fireEvent.click(screen.getByRole('button', { name: 'SOLL-Allokation speichern' }));
    expect(await screen.findByText(/Begründung der manuellen Anpassung erfassen/)).toBeInTheDocument();
    expect(saveMock).not.toHaveBeenCalled();
  });

  it('sendet die Begründung mit und zeigt Hausmatrix-Warnungen an', async () => {
    fetchMock.mockResolvedValue(makeRecord());
    saveMock.mockResolvedValue(
      makeRecord({
        version: 2,
        manual_override_warnings: ['Obligationen: manuelle Bandbreite ausserhalb der Hausmatrix'],
      }),
    );
    render(<AllocationEditor mandateId="m1" />);
    await screen.findByRole('table');
    fireEvent.change(screen.getByLabelText(/Begründung der manuellen Anpassung/), {
      target: { value: 'Kunde wünscht nach Gespräch eine defensivere Gewichtung.' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'SOLL-Allokation speichern' }));
    expect(await screen.findByText(/ausserhalb der Hausmatrix/)).toBeInTheDocument();
    expect(saveMock).toHaveBeenCalledWith(
      'm1',
      expect.objectContaining({
        override_reason: 'Kunde wünscht nach Gespräch eine defensivere Gewichtung.',
      }),
    );
  });

  it('rechnet Prozent-Eingaben in bps um und sendet bps (UX-Audit Befund 15)', async () => {
    fetchMock.mockResolvedValue(makeRecord());
    saveMock.mockResolvedValue(makeRecord({ version: 2 }));
    render(<AllocationEditor mandateId="m1" />);
    await screen.findByRole('table');
    fireEvent.change(screen.getByLabelText('Aktien Ziel in %'), { target: { value: '35,5' } });
    fireEvent.change(screen.getByLabelText('Obligationen Ziel in %'), { target: { value: '34.5' } });
    fireEvent.change(screen.getByLabelText(/Begründung der manuellen Anpassung/), {
      target: { value: 'Kunde wünscht nach Gespräch eine defensivere Gewichtung.' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'SOLL-Allokation speichern' }));
    expect(saveMock).toHaveBeenCalledWith(
      'm1',
      expect.objectContaining({ target_equities_bps: 3550, target_bonds_bps: 3450 }),
    );
  });

  it('zeigt Fehler direkt am Feld und sperrt Speichern bis gültig', async () => {
    fetchMock.mockResolvedValue(makeRecord());
    render(<AllocationEditor mandateId="m1" />);
    await screen.findByRole('table');
    const save = screen.getByRole('button', { name: 'SOLL-Allokation speichern' });
    expect(save).toBeEnabled();
    const minField = screen.getByLabelText('Aktien Minimum in %');
    fireEvent.change(minField, { target: { value: '60' } });
    expect(minField).toHaveAttribute('aria-invalid', 'true');
    expect(minField).toHaveAccessibleDescription(/Minimum 60.0 % liegt über dem Maximum 50.0 %/);
    expect(save).toBeDisabled();
    fireEvent.change(minField, { target: { value: '30' } });
    expect(minField).toHaveAttribute('aria-invalid', 'false');
    expect(save).toBeEnabled();
  });
  it('sendet die erwartete Allokations-ID/-Version mit (ALLOC-EDITOR-STALE-001)', async () => {
    fetchMock.mockResolvedValue(makeRecord({ id: 'ta-7', version: 7 }));
    saveMock.mockResolvedValue(makeRecord({ id: 'ta-8', version: 8 }));
    render(<AllocationEditor mandateId="m1" />);
    await screen.findByRole('table');
    fireEvent.change(screen.getByLabelText(/Begründung der manuellen Anpassung/), {
      target: { value: 'Kunde wünscht nach Gespräch eine defensivere Gewichtung.' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'SOLL-Allokation speichern' }));
    expect(await screen.findByText(/Version 8/)).toBeInTheDocument();
    expect(saveMock).toHaveBeenCalledWith(
      'm1',
      expect.objectContaining({
        expected_current_allocation_id: 'ta-7',
        expected_current_allocation_version: 7,
      }),
    );
  });

  it('zeigt die 409-Meldung eines veralteten Stands an (Lost Update)', async () => {
    fetchMock.mockResolvedValue(makeRecord());
    saveMock.mockRejectedValue(
      new ApiError(409, 'Die Soll-Allokation wurde inzwischen in einer anderen Sitzung geaendert (aktuelle Version 2). [allocation_version_conflict]'),
    );
    render(<AllocationEditor mandateId="m1" />);
    await screen.findByRole('table');
    fireEvent.change(screen.getByLabelText(/Begründung der manuellen Anpassung/), {
      target: { value: 'Kunde wünscht nach Gespräch eine defensivere Gewichtung.' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'SOLL-Allokation speichern' }));
    expect(await screen.findByText(/allocation_version_conflict/)).toBeInTheDocument();
  });

  it('verwirft Optimizer-Kennzahlen nach dem manuellen Speichern', async () => {
    fetchMock.mockRejectedValue(new ApiError(404, 'keine'));
    generateMock.mockResolvedValue({
      target_allocation: makeRecord({ id: 'ta-gen', version: 3 }),
      expected_return_bps: 350,
      expected_volatility_bps: 900,
      risky_fraction_total_bps: 6000,
      limiting_factor: null,
      reasoning: [],
      messages: [],
    });
    saveMock.mockResolvedValue(makeRecord({ id: 'ta-man', version: 4 }));
    render(<AllocationEditor mandateId="m1" />);
    await screen.findByText(/Noch keine SOLL-Allokation/);
    fireEvent.click(screen.getByRole('button', { name: 'Optimizer-Vorschlag' }));
    expect(await screen.findByText(/Erwartete Rendite/)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText(/Begründung der manuellen Anpassung/), {
      target: { value: 'Kunde wünscht nach Gespräch eine defensivere Gewichtung.' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'SOLL-Allokation speichern' }));
    expect(await screen.findByText(/Version 4/)).toBeInTheDocument();
    expect(screen.queryByText(/Erwartete Rendite/)).not.toBeInTheDocument();
    expect(saveMock).toHaveBeenCalledWith(
      'm1',
      expect.objectContaining({ expected_current_allocation_id: 'ta-gen' }),
    );
  });
});
