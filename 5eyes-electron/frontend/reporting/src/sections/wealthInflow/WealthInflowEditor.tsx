/**
 * Vermögenszuflüsse-Editor (Roadmap #54).
 *
 * Erfassung erwarteter Zuflüsse (Erbschaft, Bonus, Säule 3b, Verkaufserlös)
 * pro Kunde. CRUD via Drawer-Form. Wiederkehrende Zuflüsse brauchen Frequenz +
 * Dauer (Backend _validate_recurring).
 */
import { useCallback, useEffect, useState } from 'react';
import { ApiError } from '@/api/client';
import {
  createWealthInflow,
  deleteWealthInflow,
  fetchWealthInflows,
  updateWealthInflow,
} from '@/api/wealthInflow';
import {
  WEALTH_INFLOW_FREQUENCIES,
  WEALTH_INFLOW_SOURCE_TYPES,
  buildWealthInflowPayload,
  rappenToChf,
  validateWealthInflow,
  type WealthInflowFormInput,
} from '@/lib/wealthInflowForm';
import type {
  WealthInflowFrequency,
  WealthInflowRecord,
  WealthInflowSourceType,
} from '@/api/types';

type LoadState = 'idle' | 'loading' | 'ready' | 'error';

function emptyInput(): WealthInflowFormInput {
  return {
    label: '',
    source_type: 'Erbschaft',
    amountChf: '',
    expected_year: '2030',
    is_recurring: false,
    frequency: 'jaehrlich',
    duration_years: '',
    value_mode: 'nominal',
    notes: '',
  };
}

function inputFromRecord(rec: WealthInflowRecord): WealthInflowFormInput {
  return {
    label: rec.label,
    source_type: (rec.source_type as WealthInflowSourceType) ?? 'Andere',
    amountChf: String(rec.amount_rappen / 100),
    expected_year: String(rec.expected_year),
    is_recurring: rec.is_recurring === 1,
    frequency: (rec.frequency as WealthInflowFrequency) ?? 'jaehrlich',
    duration_years: rec.duration_years != null ? String(rec.duration_years) : '',
    value_mode: rec.value_mode === 'real' ? 'real' : 'nominal',
    notes: rec.notes ?? '',
  };
}

interface WealthInflowEditorProps {
  clientId: string;
}

export function WealthInflowEditor({ clientId }: WealthInflowEditorProps) {
  const [state, setState] = useState<LoadState>('idle');
  const [rows, setRows] = useState<WealthInflowRecord[]>([]);
  const [error, setError] = useState('');
  const [statusMsg, setStatusMsg] = useState('');
  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState<WealthInflowRecord | null>(null);

  const load = useCallback(
    async (signal?: AbortSignal) => {
      setState('loading');
      setError('');
      try {
        const data = await fetchWealthInflows(clientId, { signal });
        setRows(data);
        setState('ready');
      } catch (err) {
        if (err instanceof DOMException && err.name === 'AbortError') return;
        setError(err instanceof ApiError ? err.detail : 'Zuflüsse konnten nicht geladen werden.');
        setState('error');
      }
    },
    [clientId],
  );

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load]);

  async function onDelete(rec: WealthInflowRecord) {
    setStatusMsg('');
    try {
      await deleteWealthInflow(rec.id);
      setStatusMsg(`Zufluss „${rec.label}" gelöscht.`);
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : 'Löschen fehlgeschlagen.');
    }
  }

  return (
    <article className="mx-auto min-h-screen max-w-editorial px-page-x py-page-y">
      <header className="flex items-center justify-between">
        <div>
          <p className="text-micro uppercase tracking-widest text-ink-subtle">Vermögenszuflüsse</p>
          <h1 className="mt-block font-serif text-h1 text-ink">Erwartete Zuflüsse</h1>
        </div>
        <button
          type="button"
          onClick={() => {
            setEditing(null);
            setFormOpen(true);
          }}
          className="rounded bg-ink px-4 py-2 text-caption text-paper"
        >
          Neuer Zufluss
        </button>
      </header>

      <p role="status" aria-live="polite" className="mt-2 min-h-[1.25rem] text-caption text-ink-muted">
        {statusMsg}
      </p>

      {state === 'loading' || state === 'idle' ? (
        <p aria-busy="true" className="mt-block text-body text-ink-muted">Zuflüsse werden geladen…</p>
      ) : state === 'error' ? (
        <p role="alert" aria-live="assertive" className="mt-block text-body text-status-rot">{error}</p>
      ) : rows.length === 0 ? (
        <p className="mt-block text-body text-ink-muted">
          Noch keine Zuflüsse erfasst. Mit „Neuer Zufluss" den ersten anlegen.
        </p>
      ) : (
        <table className="mt-block w-full border-collapse text-body" aria-label="Erwartete Vermögenszuflüsse">
          <caption className="sr-only">Liste der erfassten Zuflüsse</caption>
          <thead>
            <tr className="border-b border-rule text-left text-caption text-ink-subtle">
              <th scope="col" className="py-2">Quelle</th>
              <th scope="col" className="py-2">Bezeichnung</th>
              <th scope="col" className="py-2 text-right">Betrag</th>
              <th scope="col" className="py-2 text-right">Jahr</th>
              <th scope="col" className="py-2">Wiederkehrend</th>
              <th scope="col" className="py-2"><span className="sr-only">Aktionen</span></th>
            </tr>
          </thead>
          <tbody>
            {rows.map((rec) => (
              <tr key={rec.id} className="border-b border-rule/50">
                <td className="py-2">{rec.source_type}</td>
                <td className="py-2">{rec.label}</td>
                <td className="py-2 text-right">{rappenToChf(rec.amount_rappen)}</td>
                <td className="py-2 text-right">{rec.expected_year}</td>
                <td className="py-2">{rec.is_recurring === 1 ? `${rec.frequency} (${rec.duration_years}J)` : '—'}</td>
                <td className="py-2 text-right">
                  <button
                    type="button"
                    onClick={() => {
                      setEditing(rec);
                      setFormOpen(true);
                    }}
                    className="rounded border border-rule px-2 py-1 text-caption text-ink"
                    aria-label={`Zufluss „${rec.label}" bearbeiten`}
                  >
                    Bearbeiten
                  </button>
                  <button
                    type="button"
                    onClick={() => onDelete(rec)}
                    className="ml-2 rounded border border-rule px-2 py-1 text-caption text-status-rot"
                    aria-label={`Zufluss „${rec.label}" löschen`}
                  >
                    Löschen
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <WealthInflowFormDrawer
        open={formOpen}
        clientId={clientId}
        editing={editing}
        onClose={() => setFormOpen(false)}
        onSaved={() => {
          setStatusMsg(editing ? 'Zufluss aktualisiert.' : 'Zufluss angelegt.');
          void load();
        }}
      />
    </article>
  );
}

interface DrawerProps {
  open: boolean;
  clientId: string;
  editing: WealthInflowRecord | null;
  onClose: () => void;
  onSaved: () => void;
}

function WealthInflowFormDrawer({ open, clientId, editing, onClose, onSaved }: DrawerProps) {
  const [form, setForm] = useState<WealthInflowFormInput>(() => emptyInput());
  const [errors, setErrors] = useState<string[]>([]);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (open) {
      setForm(editing ? inputFromRecord(editing) : emptyInput());
      setErrors([]);
      setSaving(false);
    }
  }, [open, editing]);

  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault();
        onClose();
      }
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [open, onClose]);

  if (!open) return null;

  const set = <K extends keyof WealthInflowFormInput>(field: K, value: WealthInflowFormInput[K]): void => {
    setForm((prev) => ({ ...prev, [field]: value }));
  };

  async function onSubmit() {
    const validationErrors = validateWealthInflow(form);
    if (validationErrors.length > 0) {
      setErrors(validationErrors);
      return;
    }
    setSaving(true);
    setErrors([]);
    try {
      const payload = buildWealthInflowPayload(form);
      if (editing) {
        await updateWealthInflow(editing.id, payload);
      } else {
        await createWealthInflow(clientId, payload);
      }
      onSaved();
      onClose();
    } catch (err) {
      setErrors([err instanceof ApiError ? err.detail : 'Speichern fehlgeschlagen.']);
    } finally {
      setSaving(false);
    }
  }

  const inputClass = 'mt-1 w-full rounded border border-rule bg-canvas px-2 py-1 text-body text-ink';

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/40" onClick={onClose}>
      <div
        role="dialog"
        aria-modal="true"
        aria-label={editing ? 'Zufluss bearbeiten' : 'Neuen Zufluss anlegen'}
        className="h-full w-full max-w-lg overflow-y-auto bg-canvas-panel p-6 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between">
          <h2 className="font-serif text-h2 text-ink">{editing ? 'Zufluss bearbeiten' : 'Neuer Zufluss'}</h2>
          <button type="button" onClick={onClose} aria-label="Schliessen" className="px-2 py-1 text-ink-muted">✕</button>
        </div>

        <div className="mt-block space-y-3">
          <div className="grid grid-cols-2 gap-3">
            <label className="block text-caption text-ink-muted">
              Quelle
              <select value={form.source_type} onChange={(e) => set('source_type', e.target.value as WealthInflowSourceType)} className={inputClass}>
                {WEALTH_INFLOW_SOURCE_TYPES.map((s) => <option key={s} value={s}>{s}</option>)}
              </select>
            </label>
            <label className="block text-caption text-ink-muted">
              Wertbasis
              <select value={form.value_mode} onChange={(e) => set('value_mode', e.target.value as 'nominal' | 'real')} className={inputClass}>
                <option value="nominal">nominal</option>
                <option value="real">real</option>
              </select>
            </label>
          </div>
          <label className="block text-caption text-ink-muted">
            Bezeichnung
            <input type="text" value={form.label} onChange={(e) => set('label', e.target.value)} className={inputClass} />
          </label>
          <div className="grid grid-cols-2 gap-3">
            <label className="block text-caption text-ink-muted">
              Betrag (CHF)
              <input type="number" value={form.amountChf} onChange={(e) => set('amountChf', e.target.value)} className={inputClass} />
            </label>
            <label className="block text-caption text-ink-muted">
              Erwartetes Jahr
              <input type="number" value={form.expected_year} onChange={(e) => set('expected_year', e.target.value)} className={inputClass} />
            </label>
          </div>
          <label className="flex items-center gap-2 text-caption text-ink-muted">
            <input type="checkbox" checked={form.is_recurring} onChange={(e) => set('is_recurring', e.target.checked)} />
            Wiederkehrend
          </label>
          {form.is_recurring && (
            <div className="grid grid-cols-2 gap-3">
              <label className="block text-caption text-ink-muted">
                Frequenz
                <select value={form.frequency} onChange={(e) => set('frequency', e.target.value as WealthInflowFrequency)} className={inputClass}>
                  {WEALTH_INFLOW_FREQUENCIES.filter((f) => f !== 'einmalig').map((f) => <option key={f} value={f}>{f}</option>)}
                </select>
              </label>
              <label className="block text-caption text-ink-muted">
                Dauer (Jahre)
                <input type="number" min={1} max={99} value={form.duration_years} onChange={(e) => set('duration_years', e.target.value)} className={inputClass} />
              </label>
            </div>
          )}
          <label className="block text-caption text-ink-muted">
            Notizen
            <textarea value={form.notes} onChange={(e) => set('notes', e.target.value)} rows={2} className={inputClass} />
          </label>
        </div>

        {errors.length > 0 && (
          <ul role="alert" aria-live="assertive" className="mt-block list-disc rounded border border-status-rot/40 bg-status-rot/5 p-3 pl-8 text-caption text-status-rot">
            {errors.map((msg, idx) => <li key={idx}>{msg}</li>)}
          </ul>
        )}

        <div className="mt-block flex justify-end gap-2">
          <button type="button" onClick={onClose} className="rounded border border-rule px-4 py-2 text-caption text-ink">Abbrechen</button>
          <button type="button" onClick={onSubmit} disabled={saving} className="rounded bg-ink px-4 py-2 text-caption text-paper disabled:opacity-50">
            {saving ? 'Speichere…' : 'Speichern'}
          </button>
        </div>
      </div>
    </div>
  );
}
