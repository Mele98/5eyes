/**
 * Mandate-Editor (Track #65).
 *
 * Lädt ein Mandat (GET /mandates/{id}), editiert die MandateUpdate-Felder mit
 * TS-typisierten Selects/Validierung und speichert via PUT. Feldreiche Form;
 * die Mandatsnummer ist nicht editierbar (Identität).
 */
import { useCallback, useEffect, useState } from 'react';
import { ApiError } from '@/api/client';
import { fetchMandate, updateMandate } from '@/api/mandate';
import {
  ADVISORY_LANGUAGES,
  CLIENT_SEXES,
  INVESTMENT_UNIVERSES,
  MANDATE_STATUSES,
  MANDATE_TYPES,
  buildMandateUpdatePayload,
  validateMandate,
  type MandateFormInput,
} from '@/lib/mandateForm';
import type {
  AdvisoryLanguage,
  ClientSex,
  InvestmentUniverse,
  MandateRecord,
  MandateStatus,
  MandateType,
} from '@/api/types';

type LoadState = 'idle' | 'loading' | 'ready' | 'error';

function inputFromRecord(rec: MandateRecord): MandateFormInput {
  return {
    mandate_type: (rec.mandate_type as MandateType) ?? 'Anlageberatung',
    status: (rec.status as MandateStatus) ?? 'Aktiv',
    base_currency: rec.base_currency ?? 'CHF',
    advisory_language: (rec.advisory_language as AdvisoryLanguage) ?? 'DE',
    depot_bank: rec.depot_bank ?? '',
    depot_account_number: rec.depot_account_number ?? '',
    retirement_year: rec.retirement_year != null ? String(rec.retirement_year) : '',
    life_expectancy_year: rec.life_expectancy_year != null ? String(rec.life_expectancy_year) : '',
    investment_universe: (rec.investment_universe as InvestmentUniverse) ?? 'Standard',
    client_birth_year: rec.client_birth_year != null ? String(rec.client_birth_year) : '',
    client_sex: (rec.client_sex as ClientSex) ?? '',
    use_mortality_simulation: rec.use_mortality_simulation === true,
    tax_jurisdiction: rec.tax_jurisdiction ?? '',
  };
}

interface MandateEditorProps {
  mandateId: string;
}

export function MandateEditor({ mandateId }: MandateEditorProps) {
  const [state, setState] = useState<LoadState>('idle');
  const [record, setRecord] = useState<MandateRecord | null>(null);
  const [form, setForm] = useState<MandateFormInput | null>(null);
  const [errors, setErrors] = useState<string[]>([]);
  const [statusMsg, setStatusMsg] = useState('');
  const [saving, setSaving] = useState(false);

  const load = useCallback(
    async (signal?: AbortSignal) => {
      setState('loading');
      setErrors([]);
      try {
        const rec = await fetchMandate(mandateId, { signal });
        setRecord(rec);
        setForm(inputFromRecord(rec));
        setState('ready');
      } catch (err) {
        if (err instanceof DOMException && err.name === 'AbortError') return;
        setErrors([err instanceof ApiError ? err.detail : 'Mandat konnte nicht geladen werden.']);
        setState('error');
      }
    },
    [mandateId],
  );

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load]);

  function set<K extends keyof MandateFormInput>(field: K, value: MandateFormInput[K]) {
    setForm((prev) => (prev ? { ...prev, [field]: value } : prev));
  }

  async function onSave() {
    if (!form) return;
    const validationErrors = validateMandate(form);
    if (validationErrors.length > 0) {
      setErrors(validationErrors);
      return;
    }
    setSaving(true);
    setErrors([]);
    setStatusMsg('');
    try {
      const saved = await updateMandate(mandateId, buildMandateUpdatePayload(form));
      setRecord(saved);
      setForm(inputFromRecord(saved));
      setStatusMsg('Mandat gespeichert.');
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
        <p className="text-micro uppercase tracking-widest text-ink-subtle">Mandat</p>
        <h1 className="mt-block font-serif text-h1 text-ink">
          Mandat bearbeiten{record ? ` · ${record.mandate_number}` : ''}
        </h1>
      </header>

      <p role="status" aria-live="polite" className="mt-2 min-h-[1.25rem] text-caption text-ink-muted">
        {statusMsg}
      </p>

      {state === 'loading' || state === 'idle' ? (
        <p aria-busy="true" className="mt-block text-body text-ink-muted">Mandat wird geladen…</p>
      ) : state === 'error' ? (
        <p role="alert" aria-live="assertive" className="mt-block text-body text-status-rot">
          {errors.join(' ')}
        </p>
      ) : form ? (
        <form
          className="mt-block grid grid-cols-2 gap-4"
          aria-label="Mandat-Stammdaten"
          onSubmit={(e) => {
            e.preventDefault();
            void onSave();
          }}
        >
          <label className="block text-caption text-ink-muted">
            Mandatstyp
            <select value={form.mandate_type} onChange={(e) => set('mandate_type', e.target.value as MandateType)} className={inputClass}>
              {MANDATE_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
            </select>
          </label>
          <label className="block text-caption text-ink-muted">
            Status
            <select value={form.status} onChange={(e) => set('status', e.target.value as MandateStatus)} className={inputClass}>
              {MANDATE_STATUSES.map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
          </label>
          <label className="block text-caption text-ink-muted">
            Basiswährung
            <input type="text" value={form.base_currency} onChange={(e) => set('base_currency', e.target.value)} className={inputClass} />
          </label>
          <label className="block text-caption text-ink-muted">
            Beratungssprache
            <select value={form.advisory_language} onChange={(e) => set('advisory_language', e.target.value as AdvisoryLanguage)} className={inputClass}>
              {ADVISORY_LANGUAGES.map((l) => <option key={l} value={l}>{l}</option>)}
            </select>
          </label>
          <label className="block text-caption text-ink-muted">
            Depotbank
            <input type="text" value={form.depot_bank} onChange={(e) => set('depot_bank', e.target.value)} className={inputClass} />
          </label>
          <label className="block text-caption text-ink-muted">
            Depot-Kontonummer
            <input type="text" value={form.depot_account_number} onChange={(e) => set('depot_account_number', e.target.value)} className={inputClass} />
          </label>
          <label className="block text-caption text-ink-muted">
            Anlageuniversum
            <select value={form.investment_universe} onChange={(e) => set('investment_universe', e.target.value as InvestmentUniverse)} className={inputClass}>
              {INVESTMENT_UNIVERSES.map((u) => <option key={u} value={u}>{u}</option>)}
            </select>
          </label>
          <label className="block text-caption text-ink-muted">
            Steuersitz (tax_jurisdiction)
            <input type="text" value={form.tax_jurisdiction} onChange={(e) => set('tax_jurisdiction', e.target.value)} placeholder="z.B. CH-ZH (leer = tax-naiv)" className={inputClass} />
          </label>
          <label className="block text-caption text-ink-muted">
            Pensionierungsjahr
            <input type="number" value={form.retirement_year} onChange={(e) => set('retirement_year', e.target.value)} className={inputClass} />
          </label>
          <label className="block text-caption text-ink-muted">
            Lebenserwartung (Jahr)
            <input type="number" value={form.life_expectancy_year} onChange={(e) => set('life_expectancy_year', e.target.value)} className={inputClass} />
          </label>
          <label className="block text-caption text-ink-muted">
            Geburtsjahr Kunde
            <input type="number" value={form.client_birth_year} onChange={(e) => set('client_birth_year', e.target.value)} className={inputClass} />
          </label>
          <label className="block text-caption text-ink-muted">
            Geschlecht
            <select value={form.client_sex} onChange={(e) => set('client_sex', e.target.value as '' | ClientSex)} className={inputClass}>
              <option value="">—</option>
              {CLIENT_SEXES.map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
          </label>
          <label className="col-span-2 flex items-center gap-2 text-caption text-ink-muted">
            <input type="checkbox" checked={form.use_mortality_simulation} onChange={(e) => set('use_mortality_simulation', e.target.checked)} />
            Mortalitäts-Simulation verwenden
          </label>

          {errors.length > 0 && (
            <ul role="alert" aria-live="assertive" className="col-span-2 list-disc rounded border border-status-rot/40 bg-status-rot/5 p-3 pl-8 text-caption text-status-rot">
              {errors.map((msg, idx) => <li key={idx}>{msg}</li>)}
            </ul>
          )}

          <div className="col-span-2 flex justify-end">
            <button type="submit" disabled={saving} className="rounded bg-ink px-4 py-2 text-caption text-paper disabled:opacity-50">
              {saving ? 'Speichere…' : 'Mandat speichern'}
            </button>
          </div>
        </form>
      ) : null}
    </article>
  );
}
