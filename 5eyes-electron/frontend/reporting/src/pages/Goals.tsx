/**
 * U-FE-4: Sektion 11 — Zielbasierte Optimierung.
 *
 * Großer Achievement-Score-KPI plus Goals-Tabelle mit Status-Pills
 * (Erreichbar / Knapp / Schwierig / Daten ausstehend).
 *
 * Monte-Carlo-Pfade-Hinweis wenn data_pending=True (kommt in
 * U-FE-Charts mit Recharts-Bändern).
 */
import type { GoalBasedInvestingData, GoalEntry, GoalStatus } from '@/api/types';
import { AmpelPill } from '@/components/AmpelPill';
import { ReportPage } from '@/components/ReportPage';
import { formatBpsAsPct, formatChfRappen } from '@/lib/format';

interface GoalsProps {
  data: GoalBasedInvestingData;
}

export function Goals({ data }: GoalsProps) {
  const goals = data.goals ?? [];
  return (
    <ReportPage
      nr={11}
      kicker="Zielbasierte Optimierung"
      title="Zielbasierte Optimierung"
      subtitle="Erreichungswahrscheinlichkeit pro Mandant-Ziel mit gewichtetem Gesamt-Score."
    >
      <AchievementScoreKpi scoreBps={data.goal_achievement_score_bps} />

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
                <Th>Ziel</Th>
                <Th>Typ</Th>
                <Th align="right">Zielwert</Th>
                <Th>Status</Th>
                <Th align="right">Wahrscheinlichkeit</Th>
              </tr>
            </thead>
            <tbody>
              {goals.map((g) => (
                <GoalRow key={g.goal_id || g.label} g={g} />
              ))}
            </tbody>
          </table>
        </section>
      )}

      <McPathsHint data={data} />
    </ReportPage>
  );
}

// ---------------------------------------------------------------------------

function AchievementScoreKpi({ scoreBps }: { scoreBps: number | null | undefined }) {
  const display = formatBpsAsPct(scoreBps, { decimals: 0 });
  return (
    <section className="border-l-4 border-accent bg-canvas-subtle px-6 py-5">
      <p className="text-micro uppercase tracking-widest text-ink-subtle">
        Gewichteter Zielerreichungs-Score
      </p>
      <p className="mt-2 font-serif text-display text-ink">{display}</p>
    </section>
  );
}

function GoalRow({ g }: { g: GoalEntry }) {
  return (
    <tr className="border-b border-rule last:border-b-0">
      <td className="py-4 pr-4 align-top font-semibold text-ink">
        {g.label || '—'}
      </td>
      <td className="py-4 pr-4 align-top text-ink-muted">{g.goal_type || '—'}</td>
      <td className="py-4 pr-4 text-right align-top font-mono text-ink">
        {formatChfRappen(g.target_amount_rappen)}
      </td>
      <td className="py-4 pr-4 align-top">
        <GoalStatusPill status={g.status} />
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

function Th({
  children,
  align = 'left',
}: {
  children: React.ReactNode;
  align?: 'left' | 'right';
}) {
  return (
    <th
      className={[
        'pb-3 font-medium uppercase tracking-widest text-micro text-ink-subtle',
        align === 'right' ? 'pr-0 text-right' : 'pr-4 text-left',
      ].join(' ')}
    >
      {children}
    </th>
  );
}
