/**
 * Hilfsrechner für Pensionsausgabe-Ziele (Track #64).
 *
 * Ruft POST /mandates/{id}/goals/calculate-max-pension-spending und zeigt
 * die maximal tragbare Entnahme + die Begründungs-Schritte (reasoning[]).
 * Default value_mode = "real" (konservativer/tieferer Wert, Backend-Default).
 *
 * 409-Fälle (kein aktuelles Risikoprofil / Beratungsvermögen ≤ 0 CHF) werden
 * als Hinweis gerendert, nicht als harter Fehler.
 */
import { useState } from 'react';
import { ApiError } from '@/api/client';
import { calculateMaxPensionSpending } from '@/api/goals';
import type {
  GoalValueMode,
  MaxPensionSpendingResponse,
} from '@/api/types';

function formatChf(rappen: number): string {
  const chf = Math.round(rappen / 100);
  return `CHF ${chf.toLocaleString('de-CH')}`;
}

interface MaxPensionSpendingPanelProps {
  mandateId: string;
  /** Optionaler Callback: übernimmt den errechneten Jahresbetrag (Rappen). */
  onApply?: (annualRappen: number) => void;
}

export function MaxPensionSpendingPanel({
  mandateId,
  onApply,
}: MaxPensionSpendingPanelProps) {
  const [retirementYear, setRetirementYear] = useState<number>(2035);
  const [lifeExpectancyYear, setLifeExpectancyYear] = useState<number>(2060);
  const [safetyMargin, setSafetyMargin] = useState<number>(0);
  const [valueMode, setValueMode] = useState<GoalValueMode>('real');
  const [status, setStatus] = useState<'idle' | 'loading' | 'ready' | 'hint' | 'error'>('idle');
  const [message, setMessage] = useState<string>('');
  const [result, setResult] = useState<MaxPensionSpendingResponse | null>(null);

  async function onCalculate() {
    setStatus('loading');
    setMessage('');
    setResult(null);
    try {
      const res = await calculateMaxPensionSpending(mandateId, {
        retirement_year: retirementYear,
        life_expectancy_year: lifeExpectancyYear,
        value_mode: valueMode,
        safety_margin_pct: safetyMargin,
      });
      setResult(res);
      setStatus('ready');
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        setStatus('hint');
        setMessage(err.detail);
        return;
      }
      setStatus('error');
      setMessage(err instanceof ApiError ? err.detail : 'Berechnung fehlgeschlagen.');
    }
  }

  return (
    <section
      aria-labelledby="max-pension-heading"
      className="rounded-card border border-rule bg-canvas-subtle p-4"
    >
      <h3 id="max-pension-heading" className="font-serif text-h3 text-ink">
        Maximal tragbare Pensionsausgabe
      </h3>
      <p className="mt-1 text-caption text-ink-muted">
        Errechnet die maximale Entnahme aus dem Beratungsvermögen über die
        Pensionierungsdauer (konservativ, real).
      </p>

      <div className="mt-block grid grid-cols-2 gap-3">
        <label className="text-caption text-ink-muted">
          Pensionierungsjahr
          <input
            type="number"
            value={retirementYear}
            min={1900}
            max={2200}
            onChange={(e) => setRetirementYear(Number(e.target.value))}
            className="mt-1 w-full rounded border border-rule bg-canvas px-2 py-1 text-body text-ink"
          />
        </label>
        <label className="text-caption text-ink-muted">
          Lebenserwartung (Jahr)
          <input
            type="number"
            value={lifeExpectancyYear}
            min={1900}
            max={2200}
            onChange={(e) => setLifeExpectancyYear(Number(e.target.value))}
            className="mt-1 w-full rounded border border-rule bg-canvas px-2 py-1 text-body text-ink"
          />
        </label>
        <label className="text-caption text-ink-muted">
          Sicherheitsmarge (%)
          <input
            type="number"
            value={safetyMargin}
            min={0}
            max={50}
            onChange={(e) => setSafetyMargin(Number(e.target.value))}
            className="mt-1 w-full rounded border border-rule bg-canvas px-2 py-1 text-body text-ink"
          />
        </label>
        <label className="text-caption text-ink-muted">
          Wertbasis
          <select
            value={valueMode}
            onChange={(e) => setValueMode(e.target.value as GoalValueMode)}
            className="mt-1 w-full rounded border border-rule bg-canvas px-2 py-1 text-body text-ink"
          >
            <option value="real">real</option>
            <option value="nominal">nominal</option>
          </select>
        </label>
      </div>

      <button
        type="button"
        onClick={onCalculate}
        disabled={status === 'loading'}
        className="mt-block rounded bg-ink px-4 py-2 text-caption text-paper disabled:opacity-50"
      >
        {status === 'loading' ? 'Berechne…' : 'Berechnen'}
      </button>

      <p role="status" aria-live="polite" className="mt-2 text-caption">
        {status === 'hint' && <span className="text-status-gelb">{message}</span>}
        {status === 'error' && <span className="text-status-rot">{message}</span>}
      </p>

      {status === 'ready' && result && (
        <div className="mt-block border-t border-rule pt-3">
          <p className="text-body text-ink">
            Max. monatlich: <strong>{formatChf(result.max_monthly_chf_rappen)}</strong>
            {' · '}jährlich: <strong>{formatChf(result.max_annual_chf_rappen)}</strong>
          </p>
          <p className="mt-1 text-caption text-ink-muted">
            {result.years_in_retirement} Jahre in der Pension · Wertbasis {result.value_mode}
          </p>
          {result.reasoning.length > 0 && (
            <ul className="mt-2 list-disc pl-5 text-caption text-ink-muted">
              {result.reasoning.map((line, idx) => (
                <li key={idx}>{line}</li>
              ))}
            </ul>
          )}
          {onApply && (
            <button
              type="button"
              onClick={() => onApply(result.max_annual_chf_rappen)}
              className="mt-2 rounded border border-rule px-3 py-1 text-caption text-ink"
            >
              Jahresbetrag übernehmen
            </button>
          )}
        </div>
      )}
    </section>
  );
}
