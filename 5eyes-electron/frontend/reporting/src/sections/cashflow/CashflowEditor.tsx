/**
 * Cashflow-Editor (Track #68).
 *
 * Editierbare Cashflows (CRUD) + read-only abgeleitete Cashflows (aus Vermögen,
 * klar als "automatisch" gekennzeichnet). Cashflows hängen am CLIENT.
 * valid_until ist INKLUSIV.
 */
import { useCallback, useEffect, useState } from 'react';
import { ApiError } from '@/api/client';
import {
  createCashflow,
  deleteCashflow,
  fetchCashflows,
  fetchDerivedCashflows,
  updateCashflow,
} from '@/api/cashflow';
import {
  CASHFLOW_FREQUENCIES,
  buildCashflowPayload,
  rappenToChf,
  validateCashflow,
  type CashflowFormInput,
} from '@/lib/cashflowForm';
import type {
  CashflowNature,
  CashflowRecord,
  CashflowType,
  DerivedCashflow,
} from '@/api/types';

type LoadState = 'idle' | 'loading' | 'ready' | 'error';

interface CashflowEditorProps {
  clientId: string;
}

export function CashflowEditor({ clientId }: CashflowEditorProps) {
  const [state, setState] = useState<LoadState>('idle');
  const [cashflows, setCashflows] = useState<CashflowRecord[]>([]);
  const [derived, setDerived] = useState<DerivedCashflow[]>([]);
  const [error, setError] = useState('');
  const [statusMsg, setStatusMsg] = useState('');
  // Löschfehler unabhängig vom LoadState sichtbar (gleiche Klasse wie GOAL-9/WI-1).
  const [actionError, setActionError] = useState('');
  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState<CashflowRecord | null>(null);

  const load = useCallback(
    async (signal?: AbortSignal) => {
      setState('loading');
      setError('');
      try {
        const [cf, der] = await Promise.all([
          fetchCashflows(clientId, { signal }),
          fetchDerivedCashflows(clientId, { signal }).catch(() => [] as DerivedCashflow[]),
        ]);
        setCashflows(cf);
        setDerived(der);
        setState('ready');
      } catch (err) {
        if (err instanceof DOMException && err.name === 'AbortError') return;
        setError(err instanceof ApiError ? err.detail : 'Cashflows konnten nicht geladen werden.');
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

  async function onDelete(cf: CashflowRecord) {
    setStatusMsg('');
    setActionError('');
    try {
      await deleteCashflow(clientId, cf.id);
      setStatusMsg(`Cashflow „${cf.label}" gelöscht.`);
      await load();
    } catch (err) {
      setActionError(err instanceof ApiError ? err.detail : 'Löschen fehlgeschlagen.');
    }
  }

  return (
    <article className="mx-auto min-h-screen max-w-editorial px-page-x py-page-y">
      <header className="flex items-center justify-between">
        <div>
          <p className="text-micro uppercase tracking-widest text-ink-subtle">Cashflows</p>
          <h1 className="mt-block font-serif text-h1 text-ink">Cashflow-Erfassung</h1>
        </div>
        <button
          type="button"
          onClick={() => {
            setEditing(null);
            setFormOpen(true);
          }}
          className="rounded bg-ink px-4 py-2 text-caption text-paper"
        >
          Neuer Cashflow
        </button>
      </header>

      <p role="status" aria-live="polite" className="mt-2 min-h-[1.25rem] text-caption text-ink-muted">
        {statusMsg}
      </p>
      {actionError && (
        <p role="alert" aria-live="assertive" className="mt-1 text-caption text-status-rot">
          {actionError}
        </p>
      )}

      {state === 'loading' || state === 'idle' ? (
        <p aria-busy="true" className="mt-block text-body text-ink-muted">Cashflows werden geladen…</p>
      ) : state === 'error' ? (
        <p role="alert" aria-live="assertive" className="mt-block text-body text-status-rot">{error}</p>
      ) : (
        <>
          {cashflows.length === 0 ? (
            <p className="mt-block text-body text-ink-muted">
              Noch keine manuellen Cashflows. Mit „Neuer Cashflow" den ersten erfassen.
            </p>
          ) : (
            <table className="mt-block w-full border-collapse text-body" aria-label="Manuelle Cashflows">
              <caption className="sr-only">Editierbare Cashflows des Kunden</caption>
              <thead>
                <tr className="border-b border-rule text-left text-caption text-ink-subtle">
                  <th scope="col" className="py-2">Art</th>
                  <th scope="col" className="py-2">Bezeichnung</th>
                  <th scope="col" className="py-2 text-right">Betrag</th>
                  <th scope="col" className="py-2">Frequenz</th>
                  <th scope="col" className="py-2">Bis (inkl.)</th>
                  <th scope="col" className="py-2"><span className="sr-only">Aktionen</span></th>
                </tr>
              </thead>
              <tbody>
                {cashflows.map((cf) => (
                  <tr key={cf.id} className="border-b border-rule/50">
                    <td className="py-2">{cf.cashflow_type === 'Income' ? 'Einnahme' : 'Ausgabe'}</td>
                    <td className="py-2">{cf.label}</td>
                    <td className="py-2 text-right">{rappenToChf(cf.amount_rappen)}</td>
                    <td className="py-2">{cf.frequency}</td>
                    <td className="py-2">{cf.valid_until ?? '—'}</td>
                    <td className="py-2 text-right">
                      <button
                        type="button"
                        onClick={() => {
                          setEditing(cf);
                          setFormOpen(true);
                        }}
                        className="rounded border border-rule px-2 py-1 text-caption text-ink"
                        aria-label={`Cashflow „${cf.label}" bearbeiten`}
                      >
                        Bearbeiten
                      </button>
                      <button
                        type="button"
                        onClick={() => onDelete(cf)}
                        className="ml-2 rounded border border-rule px-2 py-1 text-caption text-status-rot"
                        aria-label={`Cashflow „${cf.label}" löschen`}
                      >
                        Löschen
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}

          {derived.length > 0 && (
            <section className="mt-block" aria-labelledby="derived-heading">
              <h2 id="derived-heading" className="font-serif text-h3 text-ink">
                Automatisch aus Vermögen abgeleitet
              </h2>
              <p className="mt-1 text-caption text-ink-muted">
                ⚙ Schreibgeschützt — diese Cashflows ergeben sich aus den Vermögenspositionen
                (Hypothekarzins, Amortisation, Miet-/Zinserträge).
              </p>
              <table className="mt-2 w-full border-collapse text-body" aria-label="Abgeleitete Cashflows (read-only)">
                <thead>
                  <tr className="border-b border-rule text-left text-caption text-ink-subtle">
                    <th scope="col" className="py-2">Art</th>
                    <th scope="col" className="py-2">Bezeichnung</th>
                    <th scope="col" className="py-2 text-right">Betrag</th>
                    <th scope="col" className="py-2">Frequenz</th>
                  </tr>
                </thead>
                <tbody>
                  {derived.map((d) => (
                    <tr key={d.id} className="border-b border-rule/50 text-ink-muted">
                      <td className="py-2">
                        <span aria-hidden="true">⚙ </span>
                        {d.cashflow_type === 'Income' ? 'Einnahme' : 'Ausgabe'}
                      </td>
                      <td className="py-2">{d.label}</td>
                      <td className="py-2 text-right">{rappenToChf(d.amount_rappen)}</td>
                      <td className="py-2">{d.frequency}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </section>
          )}
        </>
      )}

      <CashflowFormDrawer
        open={formOpen}
        clientId={clientId}
        editing={editing}
        onClose={() => setFormOpen(false)}
        onSaved={() => {
          setStatusMsg(editing ? 'Cashflow aktualisiert.' : 'Cashflow angelegt.');
          void load();
        }}
      />
    </article>
  );
}

interface CashflowFormDrawerProps {
  open: boolean;
  clientId: string;
  editing: CashflowRecord | null;
  onClose: () => void;
  onSaved: () => void;
}

function inputFromRecord(rec: CashflowRecord | null): CashflowFormInput {
  if (!rec) {
    return {
      cashflow_type: 'Expense',
      label: '',
      amountChf: '',
      frequency: 'jährlich',
      nature: 'wiederkehrend',
      valid_from: '',
      valid_until: '',
      is_inflation_linked: false,
      notes: '',
    };
  }
  return {
    cashflow_type: (rec.cashflow_type as CashflowType) ?? 'Expense',
    label: rec.label,
    amountChf: String(rec.amount_rappen / 100),
    frequency: rec.frequency,
    nature: (rec.nature as CashflowNature) ?? 'wiederkehrend',
    valid_from: rec.valid_from ?? '',
    valid_until: rec.valid_until ?? '',
    is_inflation_linked: rec.is_inflation_linked === 1,
    notes: rec.notes ?? '',
  };
}

function CashflowFormDrawer({
  open,
  clientId,
  editing,
  onClose,
  onSaved,
}: CashflowFormDrawerProps) {
  const [form, setForm] = useState<CashflowFormInput>(() => inputFromRecord(editing));
  const [errors, setErrors] = useState<string[]>([]);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (open) {
      setForm(inputFromRecord(editing));
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

  const set = <K extends keyof CashflowFormInput>(field: K, value: CashflowFormInput[K]): void => {
    setForm((prev) => ({ ...prev, [field]: value }));
  };

  async function onSubmit() {
    const validationErrors = validateCashflow(form);
    if (validationErrors.length > 0) {
      setErrors(validationErrors);
      return;
    }
    setSaving(true);
    setErrors([]);
    try {
      const payload = buildCashflowPayload(form);
      if (editing) {
        await updateCashflow(clientId, editing.id, payload);
      } else {
        await createCashflow(clientId, payload);
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
        aria-label={editing ? 'Cashflow bearbeiten' : 'Neuen Cashflow anlegen'}
        className="h-full w-full max-w-lg overflow-y-auto bg-canvas-panel p-6 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between">
          <h2 className="font-serif text-h2 text-ink">
            {editing ? 'Cashflow bearbeiten' : 'Neuer Cashflow'}
          </h2>
          <button type="button" onClick={onClose} aria-label="Schliessen" className="px-2 py-1 text-ink-muted">
            ✕
          </button>
        </div>

        <div className="mt-block space-y-3">
          <div className="grid grid-cols-2 gap-3">
            <label className="block text-caption text-ink-muted">
              Art
              <select
                value={form.cashflow_type}
                onChange={(e) => set('cashflow_type', e.target.value as CashflowType)}
                className={inputClass}
              >
                <option value="Income">Einnahme</option>
                <option value="Expense">Ausgabe</option>
              </select>
            </label>
            <label className="block text-caption text-ink-muted">
              Frequenz
              <select
                value={form.frequency}
                onChange={(e) => set('frequency', e.target.value)}
                className={inputClass}
              >
                {CASHFLOW_FREQUENCIES.map((f) => (
                  <option key={f} value={f}>{f}</option>
                ))}
              </select>
            </label>
          </div>
          <label className="block text-caption text-ink-muted">
            Bezeichnung
            <input
              type="text"
              value={form.label}
              onChange={(e) => set('label', e.target.value)}
              className={inputClass}
            />
          </label>
          <label className="block text-caption text-ink-muted">
            Betrag (CHF)
            <input
              type="number"
              value={form.amountChf}
              onChange={(e) => set('amountChf', e.target.value)}
              className={inputClass}
            />
          </label>
          <div className="grid grid-cols-2 gap-3">
            <label className="block text-caption text-ink-muted">
              Gültig ab
              <input
                type="date"
                value={form.valid_from ?? ''}
                onChange={(e) => set('valid_from', e.target.value)}
                className={inputClass}
              />
            </label>
            <label className="block text-caption text-ink-muted">
              Gültig bis (inkl.)
              <input
                type="date"
                value={form.valid_until ?? ''}
                onChange={(e) => set('valid_until', e.target.value)}
                className={inputClass}
              />
            </label>
          </div>
          <label className="flex items-center gap-2 text-caption text-ink-muted">
            <input
              type="checkbox"
              checked={form.is_inflation_linked ?? false}
              onChange={(e) => set('is_inflation_linked', e.target.checked)}
            />
            Teuerungsindexiert
          </label>
          <label className="block text-caption text-ink-muted">
            Notizen
            <textarea
              value={form.notes ?? ''}
              onChange={(e) => set('notes', e.target.value)}
              rows={2}
              className={inputClass}
            />
          </label>
        </div>

        {errors.length > 0 && (
          <ul
            role="alert"
            aria-live="assertive"
            className="mt-block list-disc rounded border border-status-rot/40 bg-status-rot/5 p-3 pl-8 text-caption text-status-rot"
          >
            {errors.map((msg, idx) => (
              <li key={idx}>{msg}</li>
            ))}
          </ul>
        )}

        <div className="mt-block flex justify-end gap-2">
          <button type="button" onClick={onClose} className="rounded border border-rule px-4 py-2 text-caption text-ink">
            Abbrechen
          </button>
          <button
            type="button"
            onClick={onSubmit}
            disabled={saving}
            className="rounded bg-ink px-4 py-2 text-caption text-paper disabled:opacity-50"
          >
            {saving ? 'Speichere…' : 'Speichern'}
          </button>
        </div>
      </div>
    </div>
  );
}
