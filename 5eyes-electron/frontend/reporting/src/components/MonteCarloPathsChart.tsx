/**
 * Sprint U-12 (Roadmap-Punkt 12): SVG-Wealth-Trajectory-Chart mit
 * p5/p75-Band, p50-Median-Linie und Goal-Markern.
 *
 * Bewusst eine OWN-Komponente (kein recharts), weil:
 *  - Editorial-Stil mit klaren Schweizer-Farben (Petrol Akzent, Navy Ink)
 *  - Print-/PDF-tauglich (kein Canvas, reines SVG)
 *  - 0-Dependency (recharts ist im Bundle aber nirgends benutzt)
 *  - Sub-50ms-Render-Pfad
 *  - Volle a11y-Kontrolle ueber `<title>` und `<desc>`
 *
 * Layout
 * ------
 *   ┌────────────────────────────────────────┐
 *   │ Y-Achse Labels (CHF compact)           │
 *   │     │   ╱p75 ━━━━━━━━━━━━━━━━━ p75    │
 *   │     │  ▓▓▓▓▓▓▓▓▓ Band (p5-p75)        │
 *   │     │   ━━━━━━━━━ p50 (Median, dick)   │
 *   │     │   ╲p5  ━━━━━━━━━━━━━━━━━ p5    │
 *   │     │                                  │
 *   │     ┼────┼────┼────┼────┼────┼─────── │
 *   │     2026 2030 2034 2038 2042 2046     │
 *   │     +Goal-Markers als vertikale Linien │
 *   └────────────────────────────────────────┘
 */
import type { GoalEntry, MonteCarloPaths } from '@/api/types';
import { classifyGoals, type GoalAchievabilityStatus } from '@/lib/goalClassification';

interface MonteCarloPathsChartProps {
  paths: MonteCarloPaths;
  goals: GoalEntry[];
}

// Layout-Konstanten — passt zu Editorial-Design-Tokens
const WIDTH = 720;
const HEIGHT = 320;
const PADDING_LEFT = 70;
const PADDING_RIGHT = 24;
const PADDING_TOP = 36;
const PADDING_BOTTOM = 56;
const PLOT_W = WIDTH - PADDING_LEFT - PADDING_RIGHT;
const PLOT_H = HEIGHT - PADDING_TOP - PADDING_BOTTOM;

// Farben — Petrol-Akzent + Status-Skala. Stimmen mit tailwind-Tokens ueberein.
const COLOR_INK = '#1f2a3a';
const COLOR_INK_MUTED = '#5a6577';
const COLOR_INK_SUBTLE = '#8d97a8';
const COLOR_RULE = '#d8dde6';
const COLOR_BAND_FILL = 'rgba(46, 84, 119, 0.18)'; // Petrol-Akzent
const COLOR_P50 = '#2e5477';
const COLOR_STATUS_GRUEN = '#4E6F58';
const COLOR_STATUS_GELB = '#B59243';
const COLOR_STATUS_ROT = '#9E4747';
const COLOR_STATUS_NEUTRAL = '#5a6577';

const STATUS_COLOR: Record<GoalAchievabilityStatus, string> = {
  erreichbar: COLOR_STATUS_GRUEN,
  knapp: COLOR_STATUS_GELB,
  nicht_erreichbar: COLOR_STATUS_ROT,
  past: COLOR_STATUS_NEUTRAL,
  beyond_horizon: COLOR_STATUS_NEUTRAL,
  unknown: COLOR_STATUS_NEUTRAL,
};

export function MonteCarloPathsChart({
  paths,
  goals,
}: MonteCarloPathsChartProps) {
  const p5 = paths.p5 ?? [];
  const p50 = paths.p50 ?? [];
  const p75 = paths.p75 ?? [];
  const time_axis = paths.time_axis ?? [];

  // Defensive: wenn die Daten nicht aligned sind, rendern wir nichts.
  // Die aufrufende Komponente sollte vorher pruefen, aber wir sind robust.
  const n = time_axis.length;
  if (n < 2 || p5.length !== n || p50.length !== n || p75.length !== n) {
    return null;
  }

  // charts-2: nicht-endliche Werte (NaN/Infinity, z.B. Backend serialisiert NaN→null
  // oder Overflow) würden ungültige SVG-Koordinaten erzeugen (kaputter/leerer Chart).
  // Ein einziger nicht-finiter Wert → wir rendern nichts (Caller zeigt Empty-State).
  if (![...p5, ...p50, ...p75].every((v) => Number.isFinite(v))) {
    return null;
  }

  // y-Range = [0, max(p75) * 1.05]. 0 als Untergrenze macht die Wachstums-
  // Geschichte anschaulich (vs. min(p5) das die Bandbreite klein wirken laesst).
  const maxValue = Math.max(...p75) * 1.05;
  const minValue = 0;

  const xFor = (i: number) => PADDING_LEFT + (i / (n - 1)) * PLOT_W;
  const yFor = (v: number) =>
    PADDING_TOP + PLOT_H - ((v - minValue) / (maxValue - minValue || 1)) * PLOT_H;

  // Polyline-Strings
  const p50Line = p50.map((v, i) => `${xFor(i)},${yFor(v)}`).join(' ');

  // Band (p5..p75): Polygon top=p75 forward, bottom=p5 backward
  const bandTop = p75.map((v, i) => `${xFor(i)},${yFor(v)}`).join(' ');
  const bandBottom = [...p5]
    .map((v, i) => [xFor(i), yFor(v)] as const)
    .reverse()
    .map(([x, y]) => `${x},${y}`)
    .join(' ');
  const bandPath = `${bandTop} ${bandBottom}`;

  // Y-Achse Ticks: 5 gleichmaessig
  const yTickValues = Array.from({ length: 5 }, (_, k) =>
    Math.round((maxValue / 4) * k),
  );
  // X-Achse Ticks: maximal 6 Beschriftungen (sonst ueberfuellt)
  const xTickIndices = _spacedIndices(n, 6);

  const classifications = classifyGoals(goals, paths);

  return (
    <figure
      data-testid="mc-paths-chart"
      className="mt-section"
      aria-label="Monte-Carlo-Pfade des Vermoegens mit Quantilen p5, p50 und p75"
    >
      <svg
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        role="img"
        className="w-full h-auto"
      >
        <title>
          Monte-Carlo Wealth-Pfade: Median (p50), 5%- und 75%-Quantil ueber{' '}
          {paths.horizon_years ?? n - 1} Jahre.
        </title>
        <desc>
          {paths.n_paths ?? '?'} simulierte Pfade. Vermoegen-Trajektorie als
          Konfidenz-Band p5-p75 mit hervorgehobener Median-Linie. Goal-Marker
          zeigen Ziel-Zeitpunkt und -Wert.
        </desc>

        {/* Y-Grid + Y-Labels */}
        {yTickValues.map((v, k) => {
          const y = yFor(v);
          return (
            <g key={`y-${k}`}>
              <line
                x1={PADDING_LEFT}
                x2={WIDTH - PADDING_RIGHT}
                y1={y}
                y2={y}
                stroke={COLOR_RULE}
                strokeWidth={k === 0 ? 1 : 0.5}
              />
              <text
                x={PADDING_LEFT - 8}
                y={y}
                textAnchor="end"
                dominantBaseline="central"
                fontSize="11"
                fontFamily="ui-monospace, SFMono-Regular, monospace"
                fill={COLOR_INK_SUBTLE}
              >
                {_formatCompactChf(v)}
              </text>
            </g>
          );
        })}

        {/* Band p5-p75 */}
        <polygon
          data-testid="mc-paths-band"
          points={bandPath}
          fill={COLOR_BAND_FILL}
          stroke="none"
        />

        {/* P50 Median */}
        <polyline
          data-testid="mc-paths-p50"
          points={p50Line}
          fill="none"
          stroke={COLOR_P50}
          strokeWidth={1.8}
        />

        {/* Goal-Marker: vertikale Linie + Status-Punkt */}
        {classifications.map((c) => {
          if (c.t_index === null) return null;
          const goal = goals.find((g) => g.goal_id === c.goal_id);
          if (!goal) return null;
          const x = xFor(c.t_index);
          const yTarget = yFor(Math.min(goal.target_amount_rappen, maxValue));
          const status = c.status;
          const color = STATUS_COLOR[status];
          return (
            <g
              key={`goal-${c.goal_id}`}
              data-testid={`goal-marker-${c.goal_id}`}
              data-status={status}
            >
              <line
                x1={x}
                x2={x}
                y1={PADDING_TOP}
                y2={HEIGHT - PADDING_BOTTOM}
                stroke={color}
                strokeWidth={0.8}
                strokeDasharray="3 3"
                opacity={0.6}
              />
              <circle cx={x} cy={yTarget} r={5} fill={color} />
              <text
                x={x + 8}
                y={yTarget - 6}
                fontSize="10"
                fontFamily="ui-sans-serif, system-ui, sans-serif"
                fill={COLOR_INK}
                fontWeight={600}
              >
                {goal.label || goal.goal_id}
              </text>
            </g>
          );
        })}

        {/* X-Achse Labels */}
        {xTickIndices.map((i) => (
          <text
            key={`x-${i}`}
            x={xFor(i)}
            y={HEIGHT - PADDING_BOTTOM + 16}
            textAnchor="middle"
            fontSize="11"
            fontFamily="ui-monospace, SFMono-Regular, monospace"
            fill={COLOR_INK_SUBTLE}
          >
            {time_axis[i]}
          </text>
        ))}

        {/* Achsen-Hauptlinien */}
        <line
          x1={PADDING_LEFT}
          x2={PADDING_LEFT}
          y1={PADDING_TOP}
          y2={HEIGHT - PADDING_BOTTOM}
          stroke={COLOR_INK_MUTED}
          strokeWidth={1}
        />
        <line
          x1={PADDING_LEFT}
          x2={WIDTH - PADDING_RIGHT}
          y1={HEIGHT - PADDING_BOTTOM}
          y2={HEIGHT - PADDING_BOTTOM}
          stroke={COLOR_INK_MUTED}
          strokeWidth={1}
        />
      </svg>

      {/* Legende */}
      <figcaption
        data-testid="mc-paths-legend"
        className="mt-3 flex flex-wrap gap-x-6 gap-y-1 text-caption text-ink-muted"
      >
        <span className="inline-flex items-center gap-2">
          <span
            aria-hidden="true"
            className="inline-block h-2 w-3"
            style={{ background: COLOR_BAND_FILL, border: `1px solid ${COLOR_P50}` }}
          />
          Band p5–p75 (90% des Pfade-Korridors)
        </span>
        <span className="inline-flex items-center gap-2">
          <span
            aria-hidden="true"
            className="inline-block h-0.5 w-4"
            style={{ background: COLOR_P50 }}
          />
          Median p50
        </span>
        <span className="inline-flex items-center gap-2">
          <span aria-hidden="true" className="inline-block h-2 w-2 rounded-full" style={{ background: COLOR_STATUS_GRUEN }} />
          Ziel erreichbar
        </span>
        <span className="inline-flex items-center gap-2">
          <span aria-hidden="true" className="inline-block h-2 w-2 rounded-full" style={{ background: COLOR_STATUS_GELB }} />
          Knapp
        </span>
        <span className="inline-flex items-center gap-2">
          <span aria-hidden="true" className="inline-block h-2 w-2 rounded-full" style={{ background: COLOR_STATUS_ROT }} />
          Schwierig
        </span>
      </figcaption>
    </figure>
  );
}

// ---------------------------------------------------------------------------
// Internals — exportiert nur fuer Tests (via __test_utils, falls noetig).
// ---------------------------------------------------------------------------

function _formatCompactChf(rappen: number): string {
  if (rappen === 0) return 'CHF 0';
  const value = Math.round(rappen / 100);
  const abs = Math.abs(value);
  if (abs >= 1_000_000) return `CHF ${(value / 1_000_000).toFixed(1)} M`;
  if (abs >= 1_000) return `CHF ${(value / 1_000).toFixed(0)} k`;
  return `CHF ${value}`;
}

/**
 * Liefert ~ n_max gleichmaessig verteilte Indizes in [0, length-1] (mit
 * Endpunkten). Anti-Cluster fuer X-Achsen-Ticks.
 */
function _spacedIndices(length: number, n_max: number): number[] {
  if (length <= n_max) return Array.from({ length }, (_, i) => i);
  const step = (length - 1) / (n_max - 1);
  const out = new Set<number>();
  for (let k = 0; k < n_max; k++) {
    out.add(Math.round(k * step));
  }
  return Array.from(out).sort((a, b) => a - b);
}
