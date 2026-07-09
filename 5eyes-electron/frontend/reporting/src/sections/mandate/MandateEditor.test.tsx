/**
 * Render- + a11y-Tests für den MandateEditor (Track #65).
 */
import { render, screen, fireEvent } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '@/api/client';
import type { MandateRecord } from '@/api/types';

vi.mock('@/api/mandate', () => ({
  fetchMandate: vi.fn(),
  updateMandate: vi.fn(),
  listMandates: vi.fn(),
  createMandate: vi.fn(),
}));

import { fetchMandate, updateMandate } from '@/api/mandate';
import { MandateEditor } from './MandateEditor';

const fetchMandateMock = vi.mocked(fetchMandate);
const updateMandateMock = vi.mocked(updateMandate);

function makeMandate(overrides: Partial<MandateRecord> = {}): MandateRecord {
  return {
    id: 'm1',
    client_id: 'c1',
    mandate_number: 'M-001',
    mandate_type: 'Anlageberatung',
    status: 'Aktiv',
    base_currency: 'CHF',
    advisory_language: 'DE',
    depot_bank: 'UBS',
    depot_account_number: '123',
    opened_at: '2026-01-01',
    closed_at: null,
    retirement_year: 2040,
    life_expectancy_year: 2065,
    investment_universe: 'Standard',
    default_building_blocks_json: null,
    client_birth_year: 1975,
    client_sex: 'M',
    use_mortality_simulation: false,
    tax_jurisdiction: 'CH-ZH',
    tax_overrides_json: null,
    created_at: '2026-01-01T00:00:00.000Z',
    updated_at: '2026-01-01T00:00:00.000Z',
    ...overrides,
  };
}

beforeEach(() => {
  fetchMandateMock.mockReset();
  updateMandateMock.mockReset();
});

afterEach(() => {
  vi.clearAllMocks();
});

describe('MandateEditor', () => {
  it('rendert das Formular mit geladenen Werten', async () => {
    fetchMandateMock.mockResolvedValue(makeMandate());
    render(<MandateEditor mandateId="m1" />);
    expect(await screen.findByRole('form', { name: 'Mandat-Stammdaten' })).toBeInTheDocument();
    expect(screen.getByText(/M-001/)).toBeInTheDocument();
    expect(screen.getByLabelText('Basiswährung')).toHaveValue('CHF');
    expect(screen.getByLabelText('Steuersitz (tax_jurisdiction)')).toHaveValue('CH-ZH');
  });

  it('zeigt einen Fehler bei ApiError', async () => {
    fetchMandateMock.mockRejectedValue(new ApiError(404, 'Mandat nicht gefunden'));
    render(<MandateEditor mandateId="m1" />);
    expect(await screen.findByText('Mandat nicht gefunden')).toBeInTheDocument();
  });

  it('blockiert Speichern bei Lebenserwartung <= Pensionierung', async () => {
    fetchMandateMock.mockResolvedValue(makeMandate());
    render(<MandateEditor mandateId="m1" />);
    await screen.findByRole('form', { name: 'Mandat-Stammdaten' });
    fireEvent.change(screen.getByLabelText('Pensionierungsjahr'), { target: { value: '2040' } });
    fireEvent.change(screen.getByLabelText('Lebenserwartung (Jahr)'), { target: { value: '2035' } });
    fireEvent.click(screen.getByRole('button', { name: 'Mandat speichern' }));
    expect(await screen.findByText('Lebenserwartung muss nach dem Pensionierungsjahr liegen.')).toBeInTheDocument();
    expect(updateMandateMock).not.toHaveBeenCalled();
  });

  it('speichert gültige Änderungen via updateMandate', async () => {
    fetchMandateMock.mockResolvedValue(makeMandate());
    updateMandateMock.mockResolvedValue(makeMandate({ status: 'Inaktiv' }));
    render(<MandateEditor mandateId="m1" />);
    await screen.findByRole('form', { name: 'Mandat-Stammdaten' });
    fireEvent.click(screen.getByRole('button', { name: 'Mandat speichern' }));
    expect(await screen.findByText('Mandat gespeichert.')).toBeInTheDocument();
    expect(updateMandateMock).toHaveBeenCalledWith('m1', expect.objectContaining({ base_currency: 'CHF' }));
  });

  it('hat eine Status-Live-Region', async () => {
    fetchMandateMock.mockResolvedValue(makeMandate());
    render(<MandateEditor mandateId="m1" />);
    await screen.findByRole('form');
    expect(screen.getByRole('status')).toBeInTheDocument();
  });
});
