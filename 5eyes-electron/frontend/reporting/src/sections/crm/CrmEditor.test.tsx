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
  postOptHistory: vi.fn(),
}));

import { listClients, updateClient, fetchClient, postOptHistory } from '@/api/crm';
import { CrmEditor } from './CrmEditor';

const listMock = vi.mocked(listClients);
const updateMock = vi.mocked(updateClient);
const fetchClientMock = vi.mocked(fetchClient);
const postOptHistoryMock = vi.mocked(postOptHistory);

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
  fetchClientMock.mockReset();
  postOptHistoryMock.mockReset();
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

  // DUAL-STACK-01 (2026-10-Audit): client_classification/is_qualified_investor/
  // is_professional_opt_out duerfen nicht mehr editierbar im Hauptformular
  // sein und niemals im allgemeinen Speichern-Payload landen.
  describe('DUAL-STACK-01: Klassifikation/Opt-out nur beleggebunden aenderbar', () => {
    it('zeigt Klassifikation/Qualifizierter Anleger/Opt-out nur read-only, nicht als Eingabefelder', async () => {
      listMock.mockResolvedValue([makeClient({ client_classification: 'Professioneller Kunde', is_qualified_investor: 1 })]);
      render(<CrmEditor />);
      await screen.findByText('Muster, Max');
      fireEvent.click(screen.getByRole('button', { name: 'Stammdaten von Muster, Max bearbeiten' }));

      // Kein editierbares Dropdown/Checkbox mehr fuer diese Felder.
      expect(screen.queryByLabelText('Klassifizierung')).not.toBeInTheDocument();
      expect(screen.queryAllByRole('checkbox')).toHaveLength(0);

      // Read-only Anzeige ist vorhanden.
      expect(screen.getByText('Professioneller Kunde')).toBeInTheDocument();
      expect(screen.getByText(/Qualifizierter Anleger/)).toBeInTheDocument();
      expect(screen.getByText(/Professional Opt-out/)).toBeInTheDocument();
      expect(screen.getByRole('button', { name: 'Klassifikation ändern' })).toBeInTheDocument();
    });

    it('Speichern-Payload enthält client_classification/is_qualified_investor/is_professional_opt_out NICHT', async () => {
      listMock.mockResolvedValue([makeClient({ client_classification: 'Institutioneller Kunde', is_qualified_investor: 1, is_professional_opt_out: 1 })]);
      updateMock.mockResolvedValue(makeClient());
      render(<CrmEditor />);
      await screen.findByText('Muster, Max');
      fireEvent.click(screen.getByRole('button', { name: 'Stammdaten von Muster, Max bearbeiten' }));
      fireEvent.click(screen.getByRole('button', { name: 'Stammdaten speichern' }));
      await screen.findByText('Stammdaten gespeichert.');

      expect(updateMock).toHaveBeenCalledTimes(1);
      const payload = updateMock.mock.calls[0][1] as Record<string, unknown>;
      expect(payload).not.toHaveProperty('client_classification');
      expect(payload).not.toHaveProperty('is_qualified_investor');
      expect(payload).not.toHaveProperty('is_professional_opt_out');
    });

    it('ruft bei "Klassifikation ändern" POST /clients/{id}/opt-history mit korrekter Form auf und lädt danach neu', async () => {
      const original = makeClient({ client_classification: 'Privatkunde' });
      listMock.mockResolvedValue([original]);
      postOptHistoryMock.mockResolvedValue({
        id: 'h1',
        client_id: 'c1',
        event_type: 'reclassification',
        from_classification: 'Privatkunde',
        to_classification: 'Professioneller Kunde',
        client_requested: 1,
        documented_by: 'a1',
        documented_at: '2026-10-07T00:00:00.000Z',
        notes: 'Antrag Kunde',
        created_at: '2026-10-07T00:00:00.000Z',
      });
      fetchClientMock.mockResolvedValue(makeClient({ client_classification: 'Professioneller Kunde' }));

      render(<CrmEditor />);
      await screen.findByText('Muster, Max');
      fireEvent.click(screen.getByRole('button', { name: 'Stammdaten von Muster, Max bearbeiten' }));
      fireEvent.click(screen.getByRole('button', { name: 'Klassifikation ändern' }));

      fireEvent.change(screen.getByLabelText('Neue Klassifikation'), { target: { value: 'Professioneller Kunde' } });
      fireEvent.change(screen.getByLabelText('Begründung'), { target: { value: 'Antrag Kunde' } });
      fireEvent.click(screen.getByRole('button', { name: 'Klassifikation speichern' }));

      await screen.findByText('Klassifikation geändert und gespeichert.');

      expect(postOptHistoryMock).toHaveBeenCalledWith('c1', expect.objectContaining({
        event_type: 'reclassification',
        from_classification: 'Privatkunde',
        to_classification: 'Professioneller Kunde',
        notes: 'Antrag Kunde',
        data_classification: 'real',
      }));
      expect(fetchClientMock).toHaveBeenCalledWith('c1');
      expect(screen.getByText('Professioneller Kunde')).toBeInTheDocument();
    });

    it('zeigt bei 409 (stale from_classification) eine Fehlermeldung ohne Absturz', async () => {
      listMock.mockResolvedValue([makeClient({ client_classification: 'Privatkunde' })]);
      postOptHistoryMock.mockRejectedValue(new ApiError(409, 'from_classification stimmt nicht mit dem aktuellen Status ueberein.'));

      render(<CrmEditor />);
      await screen.findByText('Muster, Max');
      fireEvent.click(screen.getByRole('button', { name: 'Stammdaten von Muster, Max bearbeiten' }));
      fireEvent.click(screen.getByRole('button', { name: 'Klassifikation ändern' }));

      fireEvent.change(screen.getByLabelText('Neue Klassifikation'), { target: { value: 'Professioneller Kunde' } });
      fireEvent.change(screen.getByLabelText('Begründung'), { target: { value: 'Antrag Kunde' } });
      fireEvent.click(screen.getByRole('button', { name: 'Klassifikation speichern' }));

      expect(await screen.findByRole('alert')).toHaveTextContent(/erneut versuchen/);
      // Client-Record bleibt unveraendert, kein Crash, kein stiller Retry.
      expect(fetchClientMock).not.toHaveBeenCalled();
    });

    it('verlangt eine Begründung bevor der opt-history-Call ausgeführt wird', async () => {
      listMock.mockResolvedValue([makeClient({ client_classification: 'Privatkunde' })]);
      render(<CrmEditor />);
      await screen.findByText('Muster, Max');
      fireEvent.click(screen.getByRole('button', { name: 'Stammdaten von Muster, Max bearbeiten' }));
      fireEvent.click(screen.getByRole('button', { name: 'Klassifikation ändern' }));
      fireEvent.click(screen.getByRole('button', { name: 'Klassifikation speichern' }));

      expect(await screen.findByRole('alert')).toHaveTextContent('Begründung ist erforderlich.');
      expect(postOptHistoryMock).not.toHaveBeenCalled();
    });
  });
});
