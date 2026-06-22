/**
 * CRM / Stammdaten-Editor (Track #66).
 *
 * Suche/Filter über die Client-Liste (GET /clients?search=), Trefferliste,
 * Auswahl lädt die Stammdaten in eine editierbare Form (PUT /clients/{id}).
 * Letzter Editor-Track vor dem App-Shell-Cutover (#69).
 */
import { useCallback, useEffect, useState } from 'react';
import { ApiError } from '@/api/client';
import { fetchClient, listClients, updateClient } from '@/api/crm';
import {
  CLIENT_CLASSIFICATIONS,
  CLIENT_LANGUAGES,
  HOUSEHOLD_TYPES,
  SALUTATIONS,
  buildClientUpdatePayload,
  clientDisplayName,
  validateClient,
  type ClientFormInput,
} from '@/lib/clientForm';
import type {
  ClientClassification,
  ClientLanguage,
  ClientRecord,
  HouseholdType,
  Salutation,
} from '@/api/types';

type ListState = 'idle' | 'loading' | 'ready' | 'error';

function inputFromRecord(rec: ClientRecord): ClientFormInput {
  return {
    salutation: (rec.salutation as Salutation) ?? '',
    first_name: rec.first_name ?? '',
    last_name: rec.last_name ?? '',
    date_of_birth: rec.date_of_birth ?? '',
    country_of_residence: rec.country_of_residence ?? 'CH',
    canton: rec.canton ?? '',
    civil_status: rec.civil_status ?? '',
    profession: rec.profession ?? '',
    employer: rec.employer ?? '',
    language: (rec.language as ClientLanguage) ?? 'DE',
    household_type: (rec.household_type as HouseholdType) ?? 'Einzelperson',
    client_classification: (rec.client_classification as ClientClassification) ?? 'Privatkunde',
    is_qualified_investor: rec.is_qualified_investor === 1,
    is_professional_opt_out: rec.is_professional_opt_out === 1,
    notes: rec.notes ?? '',
  };
}

interface CrmEditorProps {
  /** Optional vorselektierter Kunde (Deep-Link). */
  initialClientId?: string;
}

export function CrmEditor({ initialClientId }: CrmEditorProps) {
  const [search, setSearch] = useState('');
  const [listState, setListState] = useState<ListState>('idle');
  const [results, setResults] = useState<ClientRecord[]>([]);
  const [listError, setListError] = useState('');
  const [selected, setSelected] = useState<ClientRecord | null>(null);
  const [form, setForm] = useState<ClientFormInput | null>(null);
  const [errors, setErrors] = useState<string[]>([]);
  const [statusMsg, setStatusMsg] = useState('');
  const [saving, setSaving] = useState(false);

  const runSearch = useCallback(
    async (term: string, signal?: AbortSignal) => {
      setListState('loading');
      setListError('');
      try {
        const rows = await listClients({ search: term || undefined, signal });
        setResults(rows);
        setListState('ready');
      } catch (err) {
        if (err instanceof DOMException && err.name === 'AbortError') return;
        setListError(err instanceof ApiError ? err.detail : 'Kunden konnten nicht geladen werden.');
        setListState('error');
      }
    },
    [],
  );

  function selectClient(rec: ClientRecord) {
    setSelected(rec);
    setForm(inputFromRecord(rec));
    setErrors([]);
    setStatusMsg('');
  }

  useEffect(() => {
    const controller = new AbortController();
    void runSearch('', controller.signal);
    return () => controller.abort();
  }, [runSearch]);

  useEffect(() => {
    if (!initialClientId) return;
    const controller = new AbortController();
    fetchClient(initialClientId, { signal: controller.signal })
      .then((rec) => selectClient(rec))
      .catch(() => {
        /* Deep-Link-Fehler ist nicht fatal — Liste bleibt nutzbar. */
      });
    return () => controller.abort();
  }, [initialClientId]);

  function set<K extends keyof ClientFormInput>(field: K, value: ClientFormInput[K]) {
    setForm((prev) => (prev ? { ...prev, [field]: value } : prev));
  }

  async function onSave() {
    if (!form || !selected) return;
    const validationErrors = validateClient(form);
    if (validationErrors.length > 0) {
      setErrors(validationErrors);
      return;
    }
    setSaving(true);
    setErrors([]);
    setStatusMsg('');
    try {
      const saved = await updateClient(selected.id, buildClientUpdatePayload(form));
      setSelected(saved);
      setForm(inputFromRecord(saved));
      setResults((prev) => prev.map((r) => (r.id === saved.id ? saved : r)));
      setStatusMsg('Stammdaten gespeichert.');
    } catch (err) {
      setErrors([err instanceof ApiError ? err.detail : 'Speichern fehlgeschlagen.']);
    } finally {
      setSaving(false);
    }
  }

  const inputClass = 'mt-1 w-full rounded border border-rule bg-canvas px-2 py-1 text-body text-ink';

  return (
    <article className="mx-auto min-h-screen max-w-editorial px-page-x py-page-y">
      <header>
        <p className="text-micro uppercase tracking-widest text-ink-subtle">CRM</p>
        <h1 className="mt-block font-serif text-h1 text-ink">Kunden &amp; Stammdaten</h1>
      </header>

      <form
        role="search"
        className="mt-block flex gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          void runSearch(search);
        }}
      >
        <input
          type="search"
          aria-label="Kundensuche"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Name oder Kundennummer…"
          className="flex-1 rounded border border-rule bg-canvas px-3 py-2 text-body text-ink"
        />
        <button type="submit" className="rounded bg-ink px-4 py-2 text-caption text-paper">Suchen</button>
      </form>

      <p role="status" aria-live="polite" className="mt-2 min-h-[1.25rem] text-caption text-ink-muted">
        {statusMsg}
      </p>

      <div className="mt-block grid gap-block lg:grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)]">
        <section aria-labelledby="results-heading">
          <h2 id="results-heading" className="text-micro uppercase tracking-widest text-ink-subtle">Treffer</h2>
          {listState === 'loading' || listState === 'idle' ? (
            <p aria-busy="true" className="mt-2 text-body text-ink-muted">Lädt…</p>
          ) : listState === 'error' ? (
            <p role="alert" className="mt-2 text-body text-status-rot">{listError}</p>
          ) : results.length === 0 ? (
            <p className="mt-2 text-body text-ink-muted">Keine Kunden gefunden.</p>
          ) : (
            <table className="mt-2 w-full border-collapse text-body" aria-label="Kunden-Trefferliste">
              <thead>
                <tr className="border-b border-rule text-left text-caption text-ink-subtle">
                  <th scope="col" className="py-2">Nr.</th>
                  <th scope="col" className="py-2">Name</th>
                  <th scope="col" className="py-2"><span className="sr-only">Aktion</span></th>
                </tr>
              </thead>
              <tbody>
                {results.map((c) => (
                  <tr key={c.id} className="border-b border-rule/50">
                    <td className="py-2">{c.client_number}</td>
                    <td className="py-2">{clientDisplayName(c)}</td>
                    <td className="py-2 text-right">
                      <button
                        type="button"
                        onClick={() => selectClient(c)}
                        className="rounded border border-rule px-2 py-1 text-caption text-ink"
                        aria-label={`Stammdaten von ${clientDisplayName(c)} bearbeiten`}
                      >
                        Öffnen
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>

        <section aria-labelledby="form-heading">
          <h2 id="form-heading" className="text-micro uppercase tracking-widest text-ink-subtle">Stammdaten</h2>
          {!form || !selected ? (
            <p className="mt-2 text-body text-ink-muted">Einen Kunden aus der Liste wählen.</p>
          ) : (
            <form
              className="mt-2 grid grid-cols-2 gap-3"
              aria-label="Kunden-Stammdaten"
              onSubmit={(e) => {
                e.preventDefault();
                void onSave();
              }}
            >
              <label className="block text-caption text-ink-muted">
                Anrede
                <select value={form.salutation} onChange={(e) => set('salutation', e.target.value as '' | Salutation)} className={inputClass}>
                  <option value="">—</option>
                  {SALUTATIONS.map((s) => <option key={s} value={s}>{s}</option>)}
                </select>
              </label>
              <label className="block text-caption text-ink-muted">
                Sprache
                <select value={form.language} onChange={(e) => set('language', e.target.value as ClientLanguage)} className={inputClass}>
                  {CLIENT_LANGUAGES.map((l) => <option key={l} value={l}>{l}</option>)}
                </select>
              </label>
              <label className="block text-caption text-ink-muted">
                Vorname
                <input type="text" value={form.first_name} onChange={(e) => set('first_name', e.target.value)} className={inputClass} />
              </label>
              <label className="block text-caption text-ink-muted">
                Nachname
                <input type="text" value={form.last_name} onChange={(e) => set('last_name', e.target.value)} className={inputClass} />
              </label>
              <label className="block text-caption text-ink-muted">
                Geburtsdatum
                <input type="date" value={form.date_of_birth} onChange={(e) => set('date_of_birth', e.target.value)} className={inputClass} />
              </label>
              <label className="block text-caption text-ink-muted">
                Wohnsitzland
                <input type="text" value={form.country_of_residence} onChange={(e) => set('country_of_residence', e.target.value)} className={inputClass} />
              </label>
              <label className="block text-caption text-ink-muted">
                Kanton
                <input type="text" value={form.canton} onChange={(e) => set('canton', e.target.value)} className={inputClass} />
              </label>
              <label className="block text-caption text-ink-muted">
                Zivilstand
                <input type="text" value={form.civil_status} onChange={(e) => set('civil_status', e.target.value)} className={inputClass} />
              </label>
              <label className="block text-caption text-ink-muted">
                Beruf
                <input type="text" value={form.profession} onChange={(e) => set('profession', e.target.value)} className={inputClass} />
              </label>
              <label className="block text-caption text-ink-muted">
                Arbeitgeber
                <input type="text" value={form.employer} onChange={(e) => set('employer', e.target.value)} className={inputClass} />
              </label>
              <label className="block text-caption text-ink-muted">
                Haushaltstyp
                <select value={form.household_type} onChange={(e) => set('household_type', e.target.value as HouseholdType)} className={inputClass}>
                  {HOUSEHOLD_TYPES.map((h) => <option key={h} value={h}>{h}</option>)}
                </select>
              </label>
              <label className="block text-caption text-ink-muted">
                Klassifizierung
                <select value={form.client_classification} onChange={(e) => set('client_classification', e.target.value as ClientClassification)} className={inputClass}>
                  {CLIENT_CLASSIFICATIONS.map((c) => <option key={c} value={c}>{c}</option>)}
                </select>
              </label>
              <label className="flex items-center gap-2 text-caption text-ink-muted">
                <input type="checkbox" checked={form.is_qualified_investor} onChange={(e) => set('is_qualified_investor', e.target.checked)} />
                Qualifizierter Anleger
              </label>
              <label className="flex items-center gap-2 text-caption text-ink-muted">
                <input type="checkbox" checked={form.is_professional_opt_out} onChange={(e) => set('is_professional_opt_out', e.target.checked)} />
                Professional Opt-out
              </label>
              <label className="col-span-2 block text-caption text-ink-muted">
                Notizen
                <textarea value={form.notes} onChange={(e) => set('notes', e.target.value)} rows={2} className={inputClass} />
              </label>

              {errors.length > 0 && (
                <ul role="alert" aria-live="assertive" className="col-span-2 list-disc rounded border border-status-rot/40 bg-status-rot/5 p-3 pl-8 text-caption text-status-rot">
                  {errors.map((msg, idx) => <li key={idx}>{msg}</li>)}
                </ul>
              )}

              <div className="col-span-2 flex justify-end">
                <button type="submit" disabled={saving} className="rounded bg-ink px-4 py-2 text-caption text-paper disabled:opacity-50">
                  {saving ? 'Speichere…' : 'Stammdaten speichern'}
                </button>
              </div>
            </form>
          )}
        </section>
      </div>
    </article>
  );
}
