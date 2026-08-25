/**
 * Asset-Allocation-Editor (Track #67).
 *
 * Lädt die aktuelle SOLL-Allokation, lässt den Berater Ziel-Quoten und
 * Toleranzbänder (in bps) editieren, validiert clientseitig (Summe 10000,
 * min<=target<=max) und speichert via POST. „Generate" lässt den Optimizer
 * einen Vorschlag berechnen und füllt den Editor damit vor.
 *
 * Editiert wird in Basispunkten (exakt; 10000 = 100%), mit Prozent-Anzeige.
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
  bpsToPct,
  buildTargetAllocationPayload,
  draftFromRecord,
  totalTargetBps,
  validateAllocation,
} from '@/lib/allocationForm';
import type { AllocationBucketKey, TargetAllocationRecord } from '@/api/types';

type LoadState = 'idle' | 'loading' | 'ready' | 'empty' | 'error';

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
  const [draft, setDraft] = useState<AllocationDraft | null>(null);
  const [errors, setErrors] = useState<string[]>([]);
  const [statusMsg, setStatusMsg] = useState('');
  const [saving, setSaving] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [metrics, setMetrics] = useState<GenerateMetrics | null>(null);

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

  function setField(key: AllocationBucketKey, field: 'target' | 'min' | 'max', value: number) {
    setDraft((prev) => (prev ? { ...prev, [key]: { ...prev[key], [field]: value } } : prev));
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
    if (validationErrors.length > 0) {
      setErrors(validationErrors);
      return;
    }
    setSaving(true);
    setErrors([]);
    setStatusMsg('');
    try {
      const payload = buildTargetAllocationPayload(draft, record.policy_id, {
        based_on_assessment_id: record.based_on_assessment_id,
        risky_fraction_bps: record.risky_fraction_bps,
      });
      const saved = await saveTargetAllocation(mandateId, payload);
      setRecord(saved);
      setDraft(draftFromRecord(saved));
      setStatusMsg(`SOLL-Allokation gespeichert (Version ${saved.version}).`);
    } catch (err) {
      setErrors([err instanceof ApiError ? err.detail : 'Speichern fehlgeschlagen.']);
    } finally {
      setSaving(false);
    }
  }

  const total = draft ? totalTargetBps(draft) : 0;
  const totalOk = total === 10000;
  const inputClass = 'w-24 rounded border border-rule bg-canvas px-2 py-1 text-right text-body text-ink';

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
            <caption className="sr-only">Editierbare Ziel-Quoten und Toleranzbänder in Basispunkten</caption>
            <thead>
              <tr className="border-b border-rule text-left text-caption text-ink-subtle">
                <th scope="col" className="py-2">Anlageklasse</th>
                <th scope="col" className="py-2 text-right">Ziel (bps)</th>
                <th scope="col" className="py-2 text-right">Ziel %</th>
                <th scope="col" className="py-2 text-right">Min (bps)</th>
                <th scope="col" className="py-2 text-right">Max (bps)</th>
              </tr>
            </thead>
            <tbody>
              {ALLOCATION_BUCKETS.map(({ key, label }) => (
                <tr key={key} className="border-b border-rule/50">
                  <td className="py-2">{label}</td>
                  <td className="py-2 text-right">
                    <input
                      type="number"
                      aria-label={`${label} Ziel in bps`}
                      value={draft[key].target}
                      onChange={(e) => setField(key, 'target', Number(e.target.value))}
                      className={inputClass}
                    />
                  </td>
                  <td className="py-2 text-right text-ink-muted">{bpsToPct(draft[key].target)}</td>
                  <td className="py-2 text-right">
                    <input
                      type="number"
                      aria-label={`${label} Min in bps`}
                      value={draft[key].min}
                      onChange={(e) => setField(key, 'min', Number(e.target.value))}
                      className={inputClass}
                    />
                  </td>
                  <td className="py-2 text-right">
                    <input
                      type="number"
                      aria-label={`${label} Max in bps`}
                      value={draft[key].max}
                      onChange={(e) => setField(key, 'max', Number(e.target.value))}
                      className={inputClass}
                    />
                  </td>
                </tr>
              ))}
              <tr className="font-semibold">
                <td className="py-2">Summe</td>
                <td className={`py-2 text-right ${totalOk ? 'text-status-gruen' : 'text-status-rot'}`}>
                  {total} bps
                </td>
                <td className={`py-2 text-right ${totalOk ? 'text-status-gruen' : 'text-status-rot'}`}>
                  {bpsToPct(total)}
                </td>
                <td colSpan={2} />
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
              disabled={saving || !record}
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
