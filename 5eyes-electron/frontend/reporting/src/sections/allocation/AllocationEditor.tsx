/**
 * Asset-Allocation-Editor (Track #67).
 *
 * Lädt die aktuelle SOLL-Allokation, lässt den Berater Ziel-Quoten und
 * Toleranzbänder editieren, validiert live (Summe 100 %, min<=Ziel<=max,
 * 0–100 %) und speichert via POST. „Generate" lässt den Optimizer einen
 * Vorschlag berechnen und füllt den Editor damit vor.
 *
 * UX-Audit Befund 15: Eingabe in Prozent (1 Nachkommastelle), intern bps.
 * Fehler stehen direkt am Feld; Speichern ist gesperrt, bis alles gültig ist.
 */
import { useCallback, useEffect, useState } from 'react';
import { ApiError } from '@/api/client';
import {
  fetchCurrentAllocation,
  generateAllocation,
  saveTargetAllocation,
} from '@/api/allocation';
import {
  ALLOCATION_BUCKETS,
  type AllocationDraft,
  type BandField,
  bpsToPct,
  bpsToPctInput,
  buildTargetAllocationPayload,
  draftFromRecord,
  fieldErrors,
  pctInputToBps,
  totalTargetBps,
  validateAllocation,
} from '@/lib/allocationForm';
import type { AllocationBucketKey, TargetAllocationRecord } from '@/api/types';

type LoadState = 'idle' | 'loading' | 'ready' | 'empty' | 'error';

type InputTexts = Record<AllocationBucketKey, Record<BandField, string>>;

const FIELD_COLUMNS: ReadonlyArray<{ field: BandField; label: string }> = [
  { field: 'min', label: 'Minimum' },
  { field: 'target', label: 'Ziel' },
  { field: 'max', label: 'Maximum' },
];

function textsFromDraft(draft: AllocationDraft): InputTexts {
  const out = {} as InputTexts;
  for (const { key } of ALLOCATION_BUCKETS) {
    out[key] = {
      target: bpsToPctInput(draft[key].target),
      min: bpsToPctInput(draft[key].min),
      max: bpsToPctInput(draft[key].max),
    };
  }
  return out;
}

interface GenerateMetrics {
  expected_return_bps: number;
  expected_volatility_bps: number;
  risky_fraction_total_bps: number;
  limiting_factor: string | null;
}

interface AllocationEditorProps {
  mandateId: string;
}

export function AllocationEditor({ mandateId }: AllocationEditorProps) {
  const [state, setState] = useState<LoadState>('idle');
  const [record, setRecord] = useState<TargetAllocationRecord | null>(null);
  const [draft, setDraftState] = useState<AllocationDraft | null>(null);
  const [texts, setTexts] = useState<InputTexts | null>(null);
  const [errors, setErrors] = useState<string[]>([]);
  const [statusMsg, setStatusMsg] = useState('');
  const [saving, setSaving] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [metrics, setMetrics] = useState<GenerateMetrics | null>(null);
  // MANUAL-SAVE-DEADEND-001: jede manuelle Speicherung braucht eine
  // Begründung (Backend prüft Qualität, FIDLEG Art. 13).
  const [reason, setReason] = useState('');
  const [saveWarnings, setSaveWarnings] = useState<string[]>([]);

  const load = useCallback(
    async (signal?: AbortSignal) => {
      setState('loading');
      setErrors([]);
      try {
        const rec = await fetchCurrentAllocation(mandateId, { signal });
        setRecord(rec);
        setDraft(draftFromRecord(rec));
        setState('ready');
      } catch (err) {
        if (err instanceof DOMException && err.name === 'AbortError') return;
        if (err instanceof ApiError && err.status === 404) {
          setState('empty');
          return;
        }
        setErrors([err instanceof ApiError ? err.detail : 'Allokation konnte nicht geladen werden.']);
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

  // Draft (bps) und Eingabetexte (Prozent) immer gemeinsam setzen.
  function setDraft(next: AllocationDraft) {
    setDraftState(next);
    setTexts(textsFromDraft(next));
  }

  function setField(key: AllocationBucketKey, field: BandField, raw: string) {
    setTexts((prev) => (prev ? { ...prev, [key]: { ...prev[key], [field]: raw } } : prev));
    const value = pctInputToBps(raw);
    setDraftState((prev) => (prev ? { ...prev, [key]: { ...prev[key], [field]: value } } : prev));
  }

  async function onGenerate() {
    setGenerating(true);
    setErrors([]);
    setStatusMsg('');
    try {
      const result = await generateAllocation(mandateId);
      setRecord(result.target_allocation);
      setDraft(draftFromRecord(result.target_allocation));
      setMetrics({
        expected_return_bps: result.expected_return_bps,
        expected_volatility_bps: result.expected_volatility_bps,
        risky_fraction_total_bps: result.risky_fraction_total_bps,
        limiting_factor: result.limiting_factor,
      });
      setState('ready');
      setStatusMsg('Optimizer-Vorschlag übernommen — prüfen und speichern.');
    } catch (err) {
      setErrors([err instanceof ApiError ? err.detail : 'Generieren fehlgeschlagen.']);
    } finally {
      setGenerating(false);
    }
  }

  async function onSave() {
    if (!draft || !record) return;
    const validationErrors = validateAllocation(draft);
    if (reason.trim().length === 0) {
      validationErrors.push('Bitte die Begründung der manuellen Anpassung erfassen.');
    }
    if (validationErrors.length > 0) {
      setErrors(validationErrors);
      return;
    }
    setSaving(true);
    setErrors([]);
    setSaveWarnings([]);
    setStatusMsg('');
    try {
      const payload = buildTargetAllocationPayload(draft, record.policy_id, {
        based_on_assessment_id: record.based_on_assessment_id,
        risky_fraction_bps: record.risky_fraction_bps,
        override_reason: reason.trim(),
      });
      const saved = await saveTargetAllocation(mandateId, payload);
      setRecord(saved);
      setDraft(draftFromRecord(saved));
      setSaveWarnings(saved.manual_override_warnings ?? []);
      setReason('');
      setStatusMsg(`SOLL-Allokation gespeichert (Version ${saved.version}).`);
    } catch (err) {
      setErrors([err instanceof ApiError ? err.detail : 'Speichern fehlgeschlagen.']);
    } finally {
      setSaving(false);
    }
  }

  const total = draft ? totalTargetBps(draft) : 0;
  const totalKnown = Number.isFinite(total);
  const totalOk = total === 10000;
  const perField = draft ? fieldErrors(draft) : {};
  const liveErrors = draft ? validateAllocation(draft) : [];
  const draftValid = liveErrors.length === 0;
  const inputClass = 'w-20 rounded border bg-canvas px-2 py-1 text-right text-body text-ink';

  return (
    <article className="mx-auto min-h-screen max-w-editorial px-page-x py-page-y">
      <header className="flex items-center justify-between">
        <div>
          <p className="text-micro uppercase tracking-widest text-ink-subtle">Asset Allocation</p>
          <h1 className="mt-block font-serif text-h1 text-ink">SOLL-Allokation bearbeiten</h1>
        </div>
        <button
          type="button"
          onClick={onGenerate}
          disabled={generating}
          className="rounded border border-rule px-4 py-2 text-caption text-ink disabled:opacity-50"
        >
          {generating ? 'Optimiere…' : 'Optimizer-Vorschlag'}
        </button>
      </header>

      <p role="status" aria-live="polite" className="mt-2 min-h-[1.25rem] text-caption text-ink-muted">
        {statusMsg}
      </p>

      {state === 'loading' || state === 'idle' ? (
        <p aria-busy="true" className="mt-block text-body text-ink-muted">Allokation wird geladen…</p>
      ) : state === 'error' ? (
        <p role="alert" aria-live="assertive" className="mt-block text-body text-status-rot">
          {errors.join(' ')}
        </p>
      ) : state === 'empty' && !draft ? (
        <p className="mt-block text-body text-ink-muted">
          Noch keine SOLL-Allokation. Mit „Optimizer-Vorschlag" eine Strategie berechnen.
        </p>
      ) : draft ? (
        <>
          <table className="mt-block w-full border-collapse text-body" aria-label="SOLL-Allokation pro Anlageklasse">
            <caption className="sr-only">Editierbare Ziel-Quoten und Toleranzbänder in Prozent</caption>
            <thead>
              <tr className="border-b border-rule text-left text-caption text-ink-subtle">
                <th scope="col" className="py-2">Anlageklasse</th>
                {FIELD_COLUMNS.map(({ field, label }) => (
                  <th key={field} scope="col" className="py-2 text-right">
                    {label} (%)
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {ALLOCATION_BUCKETS.map(({ key, label }) => {
                const rowErrors = perField[key] ?? {};
                const messages = Array.from(new Set(Object.values(rowErrors).filter(Boolean)));
                const errId = `alloc-err-${key}`;
                return [
                  <tr key={key} className={messages.length ? '' : 'border-b border-rule/50'}>
                    <td className="py-2">{label}</td>
                    {FIELD_COLUMNS.map(({ field, label: fieldLabel }) => {
                      const invalid = Boolean(rowErrors[field]);
                      return (
                        <td key={field} className="py-2 text-right">
                          <span className="inline-flex items-center gap-1">
                            <input
                              type="text"
                              inputMode="decimal"
                              aria-label={`${label} ${fieldLabel} in %`}
                              aria-invalid={invalid}
                              aria-describedby={messages.length ? errId : undefined}
                              value={texts?.[key][field] ?? ''}
                              onChange={(e) => setField(key, field, e.target.value)}
                              className={`${inputClass} ${invalid ? 'border-status-rot' : 'border-rule'}`}
                            />
                            <span aria-hidden="true" className="text-caption text-ink-muted">%</span>
                          </span>
                        </td>
                      );
                    })}
                  </tr>,
                  messages.length ? (
                    <tr key={`${key}-err`} className="border-b border-rule/50">
                      <td colSpan={4} id={errId} className="pb-2 text-caption text-status-rot">
                        {messages.join(' ')}
                      </td>
                    </tr>
                  ) : null,
                ];
              })}
              <tr className="font-semibold">
                <td className="py-2">Summe Ziel</td>
                <td />
                <td className={`py-2 text-right ${totalOk ? 'text-status-gruen' : 'text-status-rot'}`}>
                  {totalKnown ? `${bpsToPct(total)}${totalOk ? ' ✓' : ' (muss 100 % ergeben)'}` : '—'}
                </td>
                <td />
              </tr>
            </tbody>
          </table>

          {metrics && (
            <p className="mt-block text-caption text-ink-muted">
              Erwartete Rendite {bpsToPct(metrics.expected_return_bps)} · Vola{' '}
              {bpsToPct(metrics.expected_volatility_bps)} · risky{' '}
              {bpsToPct(metrics.risky_fraction_total_bps)}
              {metrics.limiting_factor ? ` · limitierend: ${metrics.limiting_factor}` : ''}
            </p>
          )}

          <label className="mt-block block text-caption text-ink-subtle" htmlFor="allocation-override-reason">
            Begründung der manuellen Anpassung (Pflicht)
          </label>
          <textarea
            id="allocation-override-reason"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            rows={3}
            className="mt-1 w-full rounded border border-rule bg-canvas px-2 py-1 text-body text-ink"
          />

          {saveWarnings.length > 0 && (
            <ul className="mt-block list-disc rounded border border-rule p-3 pl-8 text-caption text-ink-muted">
              {saveWarnings.map((msg, idx) => (
                <li key={idx}>{msg}</li>
              ))}
            </ul>
          )}

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

          <div className="mt-block flex justify-end">
            <button
              type="button"
              onClick={onSave}
              disabled={saving || !record || !draftValid}
              title={draftValid ? undefined : 'Speichern gesperrt, bis alle Felder gültig sind.'}
              className="rounded bg-ink px-4 py-2 text-caption text-paper disabled:opacity-50"
            >
              {saving ? 'Speichere…' : 'SOLL-Allokation speichern'}
            </button>
          </div>
        </>
      ) : null}
    </article>
  );
}
