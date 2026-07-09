/**
 * Render- + a11y-Tests für den CrmEditor (Track #66).
 */
import { render, screen, fireEvent } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '@/api/client';
import type { ClientRecord } from '@/api/types';

vi.mock('@/api/crm', () => ({
  listClients: vi.fn(),
  fetchClient: vi.fn(),
  updateClient: vi.fn(),
  deleteClient: vi.fn(),
  fetchNationalities: vi.fn(),
}));

import { listClients, updateClient } from '@/api/crm';
import { CrmEditor } from './CrmEditor';

const listMock = vi.mocked(listClients);
const updateMock = vi.mocked(updateClient);

function makeClient(overrides: Partial<ClientRecord> = {}): ClientRecord {
  return {
    id: 'c1',
    client_number: 'K-001',
    salutation: 'Herr',
    first_name: 'Max',
    last_name: 'Muster',
    date_of_birth: '1975-06-01',
    investment_horizon_start: null,
    investment_horizon_end: null,
    country_of_residence: 'CH',
    canton: 'ZH',
    civil_status: 'verheiratet',
    profession: 'Ingenieur',
    employer: 'ACME',
    language: 'DE',
    partner_salutation: null,
    partner_first_name: null,
    partner_last_name: null,
    partner_date_of_birth: null,
    partner_profession: null,
    household_type: 'Paar',
    client_classification: 'Privatkunde',
    is_professional_opt_out: 0,
    is_qualified_investor: 0,
    advisor_id: 'a1',
    notes: null,
    created_at: '2026-01-01T00:00:00.000Z',
    updated_at: '2026-01-01T00:00:00.000Z',
    ...overrides,
  };
}

beforeEach(() => {
  listMock.mockReset();
  updateMock.mockReset();
});

afterEach(() => {
  vi.clearAllMocks();
});

describe('CrmEditor', () => {
  it('lädt initial die Kundenliste in eine Tabelle', async () => {
    listMock.mockResolvedValue([makeClient()]);
    render(<CrmEditor />);
    expect(await screen.findByRole('table', { name: 'Kunden-Trefferliste' })).toBeInTheDocument();
    expect(screen.getByText('Muster, Max')).toBeInTheDocument();
  });

  it('löst eine Suche mit dem Begriff aus', async () => {
    listMock.mockResolvedValue([makeClient()]);
    render(<CrmEditor />);
    await screen.findByRole('table', { name: 'Kunden-Trefferliste' });
    fireEvent.change(screen.getByLabelText('Kundensuche'), { target: { value: 'Muster' } });
    fireEvent.click(screen.getByRole('button', { name: 'Suchen' }));
    expect(listMock).toHaveBeenLastCalledWith(expect.objectContaining({ search: 'Muster' }));
  });

  it('öffnet das Stammdaten-Formular bei Auswahl', async () => {
    listMock.mockResolvedValue([makeClient({ household_type: 'Einzelperson' })]);
    render(<CrmEditor />);
    await screen.findByText('Muster, Max');
    fireEvent.click(screen.getByRole('button', { name: 'Stammdaten von Muster, Max bearbeiten' }));
    expect(screen.getByRole('form', { name: 'Kunden-Stammdaten' })).toBeInTheDocument();
    expect(screen.getByLabelText('Vorname')).toHaveValue('Max');
  });

  it('crm-2: zeigt das Partner-Fieldset nur bei Paar/Familie', async () => {
    listMock.mockResolvedValue([makeClient({ household_type: 'Einzelperson' })]);
    render(<CrmEditor />);
    await screen.findByText('Muster, Max');
    fireEvent.click(screen.getByRole('button', { name: 'Stammdaten von Muster, Max bearbeiten' }));
    // Einzelperson: kein Partner-Block
    expect(screen.queryByRole('group', { name: 'Partner' })).not.toBeInTheDocument();
    // Haushaltstyp auf Paar → Partner-Block erscheint
    fireEvent.change(screen.getByLabelText('Haushaltstyp'), { target: { value: 'Paar' } });
    expect(screen.getByRole('group', { name: 'Partner' })).toBeInTheDocument();
  });

  it('speichert Änderungen via updateClient', async () => {
    listMock.mockResolvedValue([makeClient()]);
    updateMock.mockResolvedValue(makeClient({ first_name: 'Maximilian' }));
    render(<CrmEditor />);
    await screen.findByText('Muster, Max');
    fireEvent.click(screen.getByRole('button', { name: 'Stammdaten von Muster, Max bearbeiten' }));
    fireEvent.click(screen.getByRole('button', { name: 'Stammdaten speichern' }));
    expect(await screen.findByText('Stammdaten gespeichert.')).toBeInTheDocument();
    expect(updateMock).toHaveBeenCalledWith('c1', expect.objectContaining({ last_name: 'Muster' }));
  });

  it('hat ein Such-Formular (role=search) und eine Status-Region', async () => {
    listMock.mockResolvedValue([]);
    render(<CrmEditor />);
    await screen.findByText('Keine Kunden gefunden.');
    expect(screen.getByRole('search')).toBeInTheDocument();
    expect(screen.getByRole('status')).toBeInTheDocument();
  });

  it('zeigt einen Listenfehler bei ApiError', async () => {
    listMock.mockRejectedValue(new ApiError(500, 'CRM kaputt'));
    render(<CrmEditor />);
    expect(await screen.findByText('CRM kaputt')).toBeInTheDocument();
  });
});
