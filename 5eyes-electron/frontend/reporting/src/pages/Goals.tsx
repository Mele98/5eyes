/**
 * U-FE-4: Sektion 11 — Zielbasierte Optimierung.
 *
 * Grosse KPI «Erfolgswahrscheinlichkeit gesamt», Monte-Carlo-Pfade-Chart (p5/p50/p75)
 * mit Goal-Markern (Sprint U-12, Roadmap-Punkt 12) und Goals-Tabelle
 * mit Status-Pills.
 */
import { useMemo, useState } from 'react';

import type { GoalBasedInvestingData, GoalEntry, GoalStatus } from '@/api/types';
import { AmpelPill } from '@/components/AmpelPill';
import { MonteCarloPathsChart } from '@/components/MonteCarloPathsChart';
import { ReportPage } from '@/components/ReportPage';
import { formatBpsAsPct, formatChfRappen } from '@/lib/format';
import {
  nextSortConfig,
  sortGoals,
  type SortColumn,
  type SortConfig,
} from '@/lib/sortGoals';

interface GoalsProps {
  data: GoalBasedInvestingData;
}

export function Goals({ data }: GoalsProps) {
  const goals = data.goals ?? [];
  // Sprint U-48: Three-State-Sort (asc/desc/reset) pro Spalte
  const [sortConfig, setSortConfig] = useState<SortConfig | null>(null);
  const sortedGoals = useMemo(
    () => sortGoals(goals, sortConfig),
    [goals, sortConfig],
  );
  const handleSort = (column: SortColumn) => {
    setSortConfig((prev) => nextSortConfig(prev, column));
  };
  const mc = data.monte_carlo_paths;
  // U-12: Chart erscheint NUR wenn der Aggregator echte Pfade liefert.
  // Bei data_pending=true bleibt der Hinweis-Block (`McPathsHint`).
  // charts-1: Pfad-Arrays müssen dieselbe Länge wie time_axis haben — sonst
  // gibt MonteCarloPathsChart null zurück (Längen-Check dort) und der Chart-Slot
  // bliebe leer ohne Hinweis. Längengleichheit hier mitprüfen.
  const hasRealPaths =
    !!mc &&
    !mc.data_pending &&
    !!mc.time_axis &&
    mc.time_axis.length >= 2 &&
    !!mc.p5 &&
    !!mc.p50 &&
    !!mc.p75 &&
    mc.p5.length === mc.time_axis.length &&
    mc.p50.length === mc.time_axis.length &&
    mc.p75.length === mc.time_axis.length;

  return (
    <ReportPage
      nr={11}
      kicker="Zielbasierte Optimierung"
      title="Zielbasierte Optimierung"
      subtitle="Erfolgswahrscheinlichkeit je Ziel (nach Priorität) und Plan-Solvenz aller Ziele gemeinsam."
    >
      <AchievementScoreKpi scoreBps={data.goal_achievement_score_bps} />
      <PlanSolvencyKpi plan={data.plan_solvency ?? null} />

      {hasRealPaths ? (
        <MonteCarloPathsChart paths={mc!} goals={goals} />
      ) : (
        <McPathsHint data={data} />
      )}

      {goals.length === 0 ? (
        <p className="mt-section italic text-caption text-ink-subtle">
          Keine Ziele erfasst.
        </p>
      ) : (
        <section className="mt-section">
          <h2 className="font-serif text-h2 text-ink">Ziele</h2>
          <table className="mt-3 w-full text-caption">
            <thead>
              <tr className="border-b border-rule">
                <SortableTh column="label" sortConfig={sortConfig} onSort={handleSort}>Ziel</SortableTh>
                <SortableTh column="type" sortConfig={sortConfig} onSort={handleSort}>Typ</SortableTh>
                <SortableTh column="target" sortConfig={sortConfig} onSort={handleSort} align="right">Zielwert</SortableTh>
                <SortableTh column="status" sortConfig={sortConfig} onSort={handleSort}>Status</SortableTh>
                <SortableTh column="probability" sortConfig={sortConfig} onSort={handleSort} align="right" title={SUCCESS_PROBABILITY_TOOLTIP}>Erfolgs-Wkt.</SortableTh>
              </tr>
            </thead>
            <tbody>
              {sortedGoals.map((g) => (
                <GoalRow key={g.goal_id || g.label} g={g} />
              ))}
            </tbody>
          </table>
          <p className="mt-3 text-caption text-ink-muted" data-testid="goals-scope-note">
            <span className="font-semibold text-ink">Erfolgswahrscheinlichkeit (Erfolgs-Wkt.):</span>{' '}
            {SUCCESS_PROBABILITY_TOOLTIP}. Auf jedem simulierten Verlauf werden
            die Ziele in der festgelegten Rangfolge finanziert (Rang 1 zuerst).
            Ein Ziel gilt als erreicht, wenn es nach allen höher priorisierten
            Zielen vollständig finanziert ist.
          </p>
          {data.target_allocation_stale ? null : <FailureCauses goals={goals} />}
        </section>
      )}
    </ReportPage>
  );
}

// UX-1 (Befund 8): eine Primärkennzahl mit derselben Definition wie im
// Monolithen (5eyes_v2.html, GOAL_SUCCESS_PROBABILITY_TOOLTIP).
const SUCCESS_PROBABILITY_TOOLTIP =
  'Anteil der simulierten Verläufe, in denen das Ziel vollständig erreicht wird';

// ---------------------------------------------------------------------------
// Sprint U-48: SortableTh — klickbarer Header mit Sort-Indicator
// ---------------------------------------------------------------------------

function SortableTh({
  children,
  column,
  sortConfig,
  onSort,
  align = 'left',
  title,
}: {
  children: React.ReactNode;
  column: SortColumn;
  sortConfig: SortConfig | null;
  onSort: (column: SortColumn) => void;
  align?: 'left' | 'right';
  title?: string;
}) {
  const isActive = sortConfig?.column === column;
  const indicator = isActive
    ? (sortConfig.direction === 'asc' ? ' ▲' : ' ▼')
    : '';
  return (
    <th
      title={title}
      className={[
        'pb-3 font-medium uppercase tracking-widest text-micro text-ink-subtle',
        align === 'right' ? 'pr-0 text-right' : 'pr-4 text-left',
      ].join(' ')}
    >
      <button
        type="button"
        data-testid={`goals-sort-${column}`}
        onClick={() => onSort(column)}
        className={[
          'inline-flex items-baseline',
          align === 'right' ? 'flex-row-reverse' : '',
          'cursor-pointer hover:text-ink focus:outline-none focus:underline',
          isActive ? 'text-ink' : '',
        ].join(' ')}
        aria-sort={
          isActive
            ? (sortConfig.direction === 'asc' ? 'ascending' : 'descending')
            : 'none'
        }
      >
        <span>{children}</span>
        <span className="ml-1 text-[10px]">{indicator}</span>
      </button>
    </th>
  );
}

// ---------------------------------------------------------------------------

function AchievementScoreKpi({ scoreBps }: { scoreBps: number | null | undefined }) {
  const display = formatBpsAsPct(scoreBps, { decimals: 0 });
  return (
    <section className="border-l-4 border-accent bg-canvas-subtle px-6 py-5">
      <p className="text-micro uppercase tracking-widest text-ink-subtle">
        Erfolgswahrscheinlichkeit gesamt (gewichtet)
      </p>
      <p className="mt-2 font-serif text-display text-ink">{display}</p>
      <p className="mt-1 text-caption text-ink-muted">
        Nach Zielgewicht gemittelte Erfolgswahrscheinlichkeit aller Ziele.
      </p>
    </section>
  );
}

/**
 * GOAL-ACHIEVABILITY-ATTRIBUTION-001: der gemeinsame Planwert erscheint genau
 * einmal und klar beschriftet — nie als Zielzeile.
 */
function PlanSolvencyKpi({ plan }: { plan: GoalBasedInvestingData['plan_solvency'] }) {
  if (!plan) return null;
  return (
    <section
      className="mt-4 border-l-4 border-rule bg-canvas-subtle px-6 py-4"
      data-testid="plan-solvency-kpi"
    >
      <p className="text-micro uppercase tracking-widest text-ink-subtle">
        {plan.label || 'Plan-Solvenz (alle Ziele gemeinsam)'}
      </p>
      <p className="mt-1 font-serif text-h2 text-ink">
        {formatBpsAsPct(plan.probability_bps, { decimals: 0 })}
      </p>
      <p className="mt-1 text-caption text-ink-muted">
        Anteil der simulierten Verläufe, in denen alle Ziele gemeinsam finanziert sind.
      </p>
    </section>
  );
}

function GoalRow({ g }: { g: GoalEntry }) {
  const legacy = g.evaluation_scope === 'legacy_aggregate_unknown';
  return (
    <tr className="border-b border-rule last:border-b-0">
      <td className="py-4 pr-4 align-top font-semibold text-ink">
        {g.label || '—'}
      </td>
      <td className="py-4 pr-4 align-top text-ink-muted">{g.goal_type || '—'}</td>
      <td className="py-4 pr-4 text-right align-top font-mono text-ink">
        {/* PB-03: Renditeziel/Maximierung haben keinen Rappen-Zielwert (Backend 0)
            → "CHF 0" wäre irreführend; dann "—". */}
        {g.target_amount_rappen ? formatChfRappen(g.target_amount_rappen) : '—'}
      </td>
      <td className="py-4 pr-4 align-top">
        {legacy ? (
          // Altbewertung: gemeinsamer Planwert, keine Ampel.
          <AmpelPill status="nicht_beurteilbar" label="Altbewertung" />
        ) : (
          <GoalStatusPill status={g.status} />
        )}
      </td>
      <td className="py-4 text-right align-top font-mono text-ink">
        {formatBpsAsPct(g.probability_bps)}
      </td>
    </tr>
  );
}

const GOAL_STATUS_LABEL: Record<GoalStatus | string, string> = {
  erreichbar: 'Erreichbar',
  knapp: 'Knapp',
  nicht_erreichbar: 'Schwierig',
  data_pending: 'Daten ausstehend',
  '': 'Daten ausstehend',
};

function GoalStatusPill({ status }: { status: GoalStatus | string }) {
  // Mapping Goal-Status → Ampel
  const ampelMap: Record<string, 'gruen' | 'gelb' | 'rot' | 'nicht_beurteilbar'> = {
    erreichbar: 'gruen',
    knapp: 'gelb',
    nicht_erreichbar: 'rot',
    data_pending: 'nicht_beurteilbar',
    '': 'nicht_beurteilbar',
  };
  const ampel = ampelMap[status] ?? 'nicht_beurteilbar';
  return <AmpelPill status={ampel} label={GOAL_STATUS_LABEL[status] ?? 'Daten ausstehend'} />;
}

/**
 * GOAL-FAILURE-DISTRIBUTION-REPORT-001: verfehlte Verläufe je Ziel nach dem
 * ersten eingetretenen Ereignis (Engine v10). Beschreibend, keine
 * Kausalaussage. Ziele ohne Verteilung (Altbestand, `null`) oder ohne
 * verfehlte Verläufe (`[]`) erscheinen nicht; ohne solche Ziele kein Block.
 */
const FAILURE_CAUSE_INTRO =
  'In den simulierten Verläufen, in denen das Ziel verfehlt wird, tritt zuerst ein';
const FAILURE_CAUSE_NOTE =
  'Anteile der verfehlten Verläufe nach dem ersten eingetretenen Ereignis; ' +
  'beschreibt den Verlauf, keine Ursache im engeren Sinn.';

function FailureCauses({ goals }: { goals: GoalEntry[] }) {
  const rows = goals.filter(
    (g) => Array.isArray(g.failure_cause_summary) && g.failure_cause_summary.length > 0,
  );
  if (rows.length === 0) return null;
  return (
    <div className="mt-4" data-testid="goal-failure-causes">
      <h3 className="font-semibold text-caption text-ink">
        Verfehlte Verläufe nach erstem Ereignis
      </h3>
      <ul className="mt-2 space-y-1 text-caption text-ink">
        {rows.map((g) => (
          <li key={g.goal_id || g.label} data-testid={`goal-failure-causes-${g.goal_id}`}>
            <span className="font-semibold">{g.label || 'Ziel'}:</span>{' '}
            {FAILURE_CAUSE_INTRO}:{' '}
            {(g.failure_cause_summary ?? [])
              .map((c) => `${c.label} (${formatBpsAsPct(c.share_bps, { decimals: 0 })})`)
              .join('; ')}
            .
          </li>
        ))}
      </ul>
      <p className="mt-2 text-caption text-ink-muted">{FAILURE_CAUSE_NOTE}</p>
    </div>
  );
}

function McPathsHint({ data }: { data: GoalBasedInvestingData }) {
  const mc = data.monte_carlo_paths;
  if (!mc || !mc.data_pending) return null;
  return (
    <p className="mt-section text-caption text-ink-muted">
      <span className="font-semibold text-ink">Monte-Carlo-Pfade:</span>{' '}
      {mc.note || 'In Vorbereitung.'}
    </p>
  );
}

