/**
 * Sprint U-12 (Roadmap-Punkt 12): SVG-Wealth-Trajectory-Chart mit
 * Quantil-Faecher, p50-Median-Linie und Goal-Markern.
 *
 * REPORT-FAN-CHART-BANDS-001 (2026-10-18): zwei SYMMETRISCHE Baender
 * P10–P90 (zentrale 80 % der Pfade) und P25–P75 (zentrale 50 %), wie die
 * P10/P90-Kennzahlen der App. Vorher: ein Band p5–p75, beschriftet als
 * "90 %" -- tatsaechlich 70 % und asymmetrisch (unten 5 %, oben 25 %
 * abgeschnitten). Liefert ein aelterer Payload kein p10/p25/p90, zeigt
 * der Chart weiterhin p5–p75, aber korrekt als "70 %, asymmetrisch".
 * Zielmarker oberhalb der Skala werden nicht mehr still an den Rand
 * geklemmt: die Skala waechst bis GOAL_SCALE_CAP x Faecher-Maximum mit,
 * darueber steht ein Randmarker mit Pfeil und exaktem Zielwert.
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
 *   │ Y-Achse Labels (CHF, runde Schritte)   │
 *   │     │   ╱p90 ░░░░░░░░░░░░░░░ P10–P90  │
 *   │     │  ▓▓▓▓▓▓▓▓▓ Band P25–P75         │
 *   │     │   ━━━━━━━━━ p50 (Median, dick)   │
 *   │     │   ╲p10 ░░░░░░░░░░░░░░░          │
 *   │     ┼────┼────┼────┼────┼────┼─────── │
 *   │     2026 2030 2034 2038 2042 2046     │
 *   │     +Goal-Markers als vertikale Linien │
 *   └────────────────────────────────────────┘
 */
import type { GoalEntry, MonteCarloPaths } from '@/api/types';
import {
  fanAboveScaleText,
  fanEndLabelText,
  fanGoalPillText,
  fanGoalProbability,
  fanRangeSentence,
  fanSpreadLabelYs,
  type FanEndKey,
} from '@/lib/fanAnnotations';
import { formatChfRappen } from '@/lib/format';
import { classifyGoals, type GoalAchievabilityStatus } from '@/lib/goalClassification';

interface MonteCarloPathsChartProps {
  paths: MonteCarloPaths;
  goals: GoalEntry[];
  /**
   * AA-UX-HONEST-FAN-001: Report-Projection-Gate (`projections_hidden`).
   * true -> kein Faecher, keine Endwerte, keine Ziel-Pillen, kein Satz.
   */
  projectionsHidden?: boolean;
}

// Layout-Konstanten — passt zu Editorial-Design-Tokens
const WIDTH = 720;
const HEIGHT = 320;
// Platz fuer "CHF 12.25 Mio." (14 Zeichen x ~6.6px bei 11px Monospace)
const PADDING_LEFT = 100;
// AA-UX-HONEST-FAN-001: Platz fuer Endwert-Beschriftungen am rechten Rand
// ("12.25 Mio. · Median" = 18 Zeichen x ~5.6px bei 10px).
const PADDING_RIGHT = 112;
const END_LABEL_GAP = 12;
const PADDING_TOP = 36;
const PADDING_BOTTOM = 56;
const PLOT_W = WIDTH - PADDING_LEFT - PADDING_RIGHT;
const PLOT_H = HEIGHT - PADDING_TOP - PADDING_BOTTOM;

// Farben — Petrol-Akzent + Status-Skala.
const COLOR_INK = '#1f2a3a';
const COLOR_INK_MUTED = '#5a6577';
const COLOR_INK_SUBTLE = '#8d97a8';
const COLOR_RULE = '#d8dde6';
// Zwei verschachtelte Baender: aussen (P10–P90) heller, innen (P25–P75)
// liegt darueber -- die Deckkraft addiert sich im Kernbereich sichtbar.
const COLOR_BAND_OUTER_FILL = 'rgba(46, 84, 119, 0.12)'; // Petrol-Akzent
const COLOR_BAND_INNER_FILL = 'rgba(46, 84, 119, 0.22)';
const COLOR_P50 = '#2e5477';
const COLOR_STATUS_GRUEN = '#4E6F58';
const COLOR_STATUS_GELB = '#B59243';
const COLOR_STATUS_ROT = '#9E4747';
const COLOR_STATUS_NEUTRAL = '#5a6577';

/**
 * Zielwerte bis zu GOAL_SCALE_CAP x (oberer Faecherrand) erweitern die
 * y-Skala; hoehere Ziele wuerden den Faecher zur Linie stauchen und
 * bekommen stattdessen einen Randmarker (Pfeil + exakter Wert).
 */
export const GOAL_SCALE_CAP = 2;

/** Hoechstens so viele y-Intervalle (=> hoechstens 5 Tick-Beschriftungen). */
const MAX_Y_INTERVALS = 4;

const TABULAR_NUMS = { fontVariantNumeric: 'tabular-nums' } as const;

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
  projectionsHidden = false,
}: MonteCarloPathsChartProps) {
  // AA-UX-HONEST-FAN-001: Gate fail-closed -- bei ausgeblendeten Projektionen
  // bzw. veralteter/blockierter Allokation weder Faecher noch Beschriftung.
  if (
    projectionsHidden ||
    paths.projection_status === 'stale' ||
    paths.projection_status === 'blocked'
  ) {
    return null;
  }
  const p5 = paths.p5 ?? [];
  const p50 = paths.p50 ?? [];
  const p75 = paths.p75 ?? [];
  const time_axis = paths.time_axis ?? [];

  // Defensive: wenn die Daten nicht aligned sind, rendern wir nichts.
  // Die aufrufende Komponente sollte vorher pruefen, aber wir sind robust.
  // p5/p50/p75 bleiben Pflicht: die Ziel-Klassifikation basiert darauf.
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

  const fan = selectFanBands(paths, n);
  if (fan === null) return null;

  const classifications = classifyGoals(goals, paths);

  // y-Range = [0, runde Obergrenze]. 0 als Untergrenze macht die Wachstums-
  // Geschichte anschaulich (vs. min(p5) das die Bandbreite klein wirken laesst).
  // Ziele im Horizont bis GOAL_SCALE_CAP x Faecher-Maximum erweitern die Skala.
  const fanMax = Math.max(...fan.outerHi, ...p50);
  const goalTargetsInHorizon = classifications
    .filter((c) => c.t_index !== null)
    .map((c) => goals.find((g) => g.goal_id === c.goal_id)?.target_amount_rappen)
    .filter((v): v is number => typeof v === 'number' && Number.isFinite(v));
  const { maxValue, step: yStep } = computeYScale(fanMax, goalTargetsInHorizon);
  const minValue = 0;

  const xFor = (i: number) => PADDING_LEFT + (i / (n - 1)) * PLOT_W;
  const yFor = (v: number) =>
    PADDING_TOP + PLOT_H - ((v - minValue) / (maxValue - minValue || 1)) * PLOT_H;

  // Polyline-Strings
  const p50Line = p50.map((v, i) => `${xFor(i)},${yFor(v)}`).join(' ');
  const outerBandPath = bandPolygon(fan.outerLo, fan.outerHi, xFor, yFor);
  const innerBandPath =
    fan.innerLo && fan.innerHi
      ? bandPolygon(fan.innerLo, fan.innerHi, xFor, yFor)
      : null;

  // Y-Achse Ticks: Vielfache eines runden Schritts (1/2/2.5/5 x 10^k)
  const yTickValues = Array.from(
    { length: Math.round(maxValue / yStep) + 1 },
    (_, k) => k * yStep,
  );
  const formatYTick = makeYTickFormatter(maxValue, yStep);
  // X-Achse Ticks: maximal 6 Beschriftungen (sonst ueberfuellt)
  const xTickIndices = _spacedIndices(n, 6);
  const anyGoalAboveScale = goalTargetsInHorizon.some((v) => v > maxValue);

  // Endwerte am rechten Rand (Median immer; P90/P10 nur beim symmetrischen
  // Faecher -- das Legacy-Band p5–p75 bekommt keine P10/P90-Etiketten).
  const last = n - 1;
  const endEntries: Array<{ key: FanEndKey; rappen: number }> = fan.symmetric
    ? [
        { key: 'p90', rappen: fan.outerHi[last] },
        { key: 'p50', rappen: p50[last] },
        { key: 'p10', rappen: fan.outerLo[last] },
      ]
    : [{ key: 'p50', rappen: p50[last] }];
  const endYs = fanSpreadLabelYs(
    endEntries.map((e) => yFor(e.rappen)),
    END_LABEL_GAP,
    PADDING_TOP,
    HEIGHT - PADDING_BOTTOM,
  );
  const rangeSentence = fan.symmetric
    ? fanRangeSentence(time_axis[last], fan.outerLo[last] / 100, fan.outerHi[last] / 100)
    : '';

  return (
    <figure
      data-testid="mc-paths-chart"
      className="mt-section"
      aria-label={`Monte-Carlo-Pfade des Vermoegens mit Quantilen ${fan.quantileList}`}
    >
      <svg
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        role="img"
        className="w-full h-auto"
      >
        <title>
          {`Monte-Carlo Wealth-Pfade über ${paths.horizon_years ?? n - 1} Jahre: Median (P50), ${
            fan.outerLegend
          }${fan.innerLegend ? `, ${fan.innerLegend}` : ''}.`}
        </title>
        <desc>
          {`${paths.n_paths ?? '?'} simulierte Pfade. Goal-Marker zeigen Ziel-Zeitpunkt und -Wert.`}
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
                data-testid="mc-paths-y-tick"
                x={PADDING_LEFT - 8}
                y={y}
                textAnchor="end"
                dominantBaseline="central"
                fontSize="11"
                fontFamily="ui-monospace, SFMono-Regular, monospace"
                fill={COLOR_INK_SUBTLE}
                style={TABULAR_NUMS}
              >
                {formatYTick(v)}
              </text>
            </g>
          );
        })}

        {/* Aeusseres Band (P10–P90, bzw. Legacy p5–p75) */}
        <polygon
          data-testid="mc-paths-band"
          points={outerBandPath}
          fill={COLOR_BAND_OUTER_FILL}
          stroke="none"
        />
        {/* Inneres Band (P25–P75) */}
        {innerBandPath !== null ? (
          <polygon
            data-testid="mc-paths-band-inner"
            points={innerBandPath}
            fill={COLOR_BAND_INNER_FILL}
            stroke="none"
          />
        ) : null}

        {/* P50 Median */}
        <polyline
          data-testid="mc-paths-p50"
          points={p50Line}
          fill="none"
          stroke={COLOR_P50}
          strokeWidth={2.5}
        />

        {/* Endwerte direkt am rechten Rand statt in einer Legende */}
        {endEntries.map((e, k) => (
          <text
            key={`end-${e.key}`}
            data-testid={`mc-paths-end-label-${e.key}`}
            x={WIDTH - PADDING_RIGHT + 6}
            y={endYs[k]}
            textAnchor="start"
            dominantBaseline="central"
            fontSize="10"
            fontFamily="ui-sans-serif, system-ui, sans-serif"
            fill={e.key === 'p50' ? COLOR_P50 : COLOR_INK_MUTED}
            fontWeight={e.key === 'p50' ? 600 : 400}
            style={TABULAR_NUMS}
          >
            {fanEndLabelText(e.rappen / 100, e.key)}
          </text>
        ))}

        {/* Goal-Marker: vertikale Linie + Status-Punkt (bzw. Randmarker) */}
        {classifications.map((c) => {
          if (c.t_index === null) return null;
          const goal = goals.find((g) => g.goal_id === c.goal_id);
          if (!goal) return null;
          const x = xFor(c.t_index);
          const aboveScale = goal.target_amount_rappen > maxValue;
          const yTarget = yFor(Math.min(goal.target_amount_rappen, maxValue));
          const status = c.status;
          const color = STATUS_COLOR[status];
          // Labels am rechten Rand nach links ausrichten (sonst abgeschnitten)
          const nearRightEdge = x > WIDTH - PADDING_RIGHT - 160;
          const labelAnchor = nearRightEdge ? 'end' : 'start';
          // Ziel-Pille: „Ruhestand · 82 %" (Wahrscheinlichkeit nur, wenn
          // belastbar bewertet -- sonst nur das Label).
          const prob = goalProbability(goal);
          const pillText = fanGoalPillText(
            goal.label || goal.goal_id,
            prob?.pct ?? null,
            prob?.estimate ?? false,
          );
          const pillW = Math.round(pillText.length * 5.6 + 14);
          const pillH = 16;
          const pillX = nearRightEdge ? x - 8 - pillW : x + 8;
          const pillCy = aboveScale
            ? yTarget + 14
            : Math.max(PADDING_TOP + pillH / 2, yTarget - 12);
          return (
            <g
              key={`goal-${c.goal_id}`}
              data-testid={`goal-marker-${c.goal_id}`}
              data-status={status}
              data-above-scale={aboveScale ? 'true' : 'false'}
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
              {aboveScale ? (
                // Randmarker: Ziel liegt oberhalb der Skala -> Pfeil nach
                // oben + exakter Zielwert statt eines irrefuehrend am
                // Rand "aufliegenden" Punkts.
                <polygon
                  data-testid={`goal-marker-arrow-${c.goal_id}`}
                  points={`${x},${yTarget - 8} ${x - 6},${yTarget + 3} ${x + 6},${yTarget + 3}`}
                  fill={color}
                />
              ) : (
                <circle cx={x} cy={yTarget} r={5} fill={color} />
              )}
              <g data-testid={`goal-marker-pill-${c.goal_id}`}>
                <rect
                  x={pillX}
                  y={pillCy - pillH / 2}
                  width={pillW}
                  height={pillH}
                  rx={pillH / 2}
                  fill="#ffffff"
                  fillOpacity={0.94}
                  stroke={color}
                  strokeWidth={1}
                />
                <text
                  x={pillX + pillW / 2}
                  y={pillCy}
                  textAnchor="middle"
                  dominantBaseline="central"
                  fontSize="10"
                  fontFamily="ui-sans-serif, system-ui, sans-serif"
                  fill={COLOR_INK}
                  fontWeight={600}
                  style={TABULAR_NUMS}
                >
                  {pillText}
                </text>
              </g>
              {aboveScale ? (
                <text
                  data-testid={`goal-marker-value-${c.goal_id}`}
                  x={nearRightEdge ? x - 8 : x + 8}
                  y={pillCy + pillH / 2 + 10}
                  textAnchor={labelAnchor}
                  fontSize="10"
                  fontFamily="ui-sans-serif, system-ui, sans-serif"
                  fill={COLOR_INK_MUTED}
                  style={TABULAR_NUMS}
                >
                  {fanAboveScaleText(goal.target_amount_rappen / 100)}
                </text>
              ) : null}
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
            style={TABULAR_NUMS}
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

      {rangeSentence ? (
        <p
          data-testid="mc-paths-range-sentence"
          className="mt-3 text-body text-ink"
          style={TABULAR_NUMS}
        >
          {rangeSentence}
        </p>
      ) : null}

      {/* Legende */}
      <figcaption
        data-testid="mc-paths-legend"
        className="mt-3 flex flex-wrap gap-x-6 gap-y-1 text-caption text-ink-muted"
      >
        <span className="inline-flex items-center gap-2" data-testid="mc-paths-legend-outer">
          <span
            aria-hidden="true"
            className="inline-block h-2 w-3"
            style={{ background: COLOR_BAND_OUTER_FILL, border: `1px solid ${COLOR_P50}` }}
          />
          {fan.outerLegend}
        </span>
        {fan.innerLegend !== null ? (
          <span className="inline-flex items-center gap-2" data-testid="mc-paths-legend-inner">
            <span
              aria-hidden="true"
              className="inline-block h-2 w-3"
              style={{ background: COLOR_BAND_INNER_FILL, border: `1px solid ${COLOR_P50}` }}
            />
            {fan.innerLegend}
          </span>
        ) : null}
        <span className="inline-flex items-center gap-2">
          <span
            aria-hidden="true"
            className="inline-block h-0.5 w-4"
            style={{ background: COLOR_P50 }}
          />
          Median (P50)
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
        {anyGoalAboveScale ? (
          <span className="inline-flex items-center gap-2" data-testid="mc-paths-legend-above-scale">
            <span aria-hidden="true">▲</span>
            Ziel über der Skala (Wert beschriftet)
          </span>
        ) : null}
      </figcaption>
    </figure>
  );
}

// ---------------------------------------------------------------------------
// Internals — exportiert fuer Tests.
// ---------------------------------------------------------------------------

interface FanBands {
  /** true = P10–P90/P25–P75; false = Legacy p5–p75 (asymmetrisch). */
  symmetric: boolean;
  outerLo: number[];
  outerHi: number[];
  innerLo: number[] | null;
  innerHi: number[] | null;
  outerLegend: string;
  innerLegend: string | null;
  quantileList: string;
}

/**
 * Waehlt die Faecher-Baender. Bevorzugt P10–P90 + P25–P75 (symmetrisch,
 * 80 % / 50 %). Fehlen p10/p25/p90 komplett (aelterer Payload), faellt der
 * Chart auf p5–p75 zurueck -- korrekt beschriftet als 70 %, asymmetrisch.
 * Sind sie nur teilweise oder fehlerhaft vorhanden: null (kein Chart),
 * statt still ein anderes Band zu zeigen. Erwartet bereits validierte
 * p5/p50/p75 der Laenge n.
 */
export function selectFanBands(paths: MonteCarloPaths, n: number): FanBands | null {
  const p5 = paths.p5 ?? [];
  const p75 = paths.p75 ?? [];
  const p10 = paths.p10 ?? [];
  const p25 = paths.p25 ?? [];
  const p90 = paths.p90 ?? [];
  const present = [p10, p25, p90].filter((a) => a.length > 0).length;
  if (present === 0) {
    return {
      symmetric: false,
      outerLo: p5,
      outerHi: p75,
      innerLo: null,
      innerHi: null,
      outerLegend: 'Bandbreite P5–P75 (70 % der Verläufe, asymmetrisch)',
      innerLegend: null,
      quantileList: 'P5, P50 und P75',
    };
  }
  const valid = [p10, p25, p90].every(
    (a) => a.length === n && a.every((v) => Number.isFinite(v)),
  );
  if (!valid) return null;
  return {
    symmetric: true,
    outerLo: p10,
    outerHi: p90,
    innerLo: p25,
    innerHi: p75,
    outerLegend: 'Bandbreite P10–P90 (8 von 10 Verläufen)',
    innerLegend: 'Kernbereich P25–P75 (5 von 10 Verläufen)',
    quantileList: 'P10, P25, P50, P75 und P90',
  };
}

/**
 * Erfolgswahrscheinlichkeit fuer die Ziel-Pille -- gleiche Regel wie die App
 * (fanGoalProbability): kanonisch `probability_bps` bei `priority_funded`.
 * Der Report kennt keinen Simulations-Fallback (null), Altbewertung bzw.
 * ausserhalb des Horizonts -> nur Label.
 */
export function goalProbability(goal: GoalEntry): { pct: number; estimate: boolean } | null {
  const bps = goal.probability_bps;
  return fanGoalProbability(
    {
      probability: typeof bps === 'number' && Number.isFinite(bps) ? bps / 10000 : null,
      evaluation_scope: goal.evaluation_scope,
      outside_simulation_horizon: goal.outside_simulation_horizon,
    },
    null,
  );
}

function bandPolygon(
  lo: number[],
  hi: number[],
  xFor: (i: number) => number,
  yFor: (v: number) => number,
): string {
  // Polygon: oberer Rand vorwaerts, unterer Rand rueckwaerts
  const top = hi.map((v, i) => `${xFor(i)},${yFor(v)}`);
  const bottom = lo.map((v, i) => `${xFor(i)},${yFor(v)}`).reverse();
  return [...top, ...bottom].join(' ');
}

/**
 * Runde Achsenschritte 1/2/2.5/5 x 10^k: kleinster solcher Schritt >= raw.
 */
export function niceStep(raw: number): number {
  if (!(raw > 0) || !Number.isFinite(raw)) return 1;
  const exp = Math.floor(Math.log10(raw));
  const base = 10 ** exp;
  for (const m of [1, 2, 2.5, 5]) {
    const candidate = m * base;
    // Toleranz gegen Float-Rauschen (z.B. 3 * 0.1)
    if (candidate >= raw * (1 - 1e-12)) return candidate;
  }
  return 10 * base;
}

/**
 * y-Skala: Obergrenze = kleinstes Vielfaches eines runden Schritts, das
 * 105 % von max(Faecher-Maximum, Ziele <= GOAL_SCALE_CAP x Faecher-Maximum)
 * abdeckt; hoechstens MAX_Y_INTERVALS Intervalle.
 */
export function computeYScale(
  fanMax: number,
  goalTargets: number[],
): { maxValue: number; step: number } {
  const safeFanMax = fanMax > 0 && Number.isFinite(fanMax) ? fanMax : 1;
  const cap = safeFanMax * GOAL_SCALE_CAP;
  const inScaleGoals = goalTargets.filter((v) => v > 0 && v <= cap);
  const top = Math.max(safeFanMax, ...inScaleGoals) * 1.05;
  const step = niceStep(top / MAX_Y_INTERVALS);
  const maxValue = Math.ceil(top / step - 1e-9) * step;
  return { maxValue, step };
}

/**
 * Achsenbeschriftung mit EINER festen Nachkommastellenzahl fuer die ganze
 * Achse (keine springenden Stellen). Ab 1 Mio. CHF in "Mio." mit genau so
 * vielen Stellen, wie der Schritt braucht (0.25 Mio. -> 2, 0.5 -> 1,
 * 1 -> 0); darunter voller CHF-Betrag im Report-Format (Apostroph).
 */
export function makeYTickFormatter(
  maxValueRappen: number,
  stepRappen: number,
): (rappen: number) => string {
  const MIO_RAPPEN = 1_000_000 * 100;
  if (maxValueRappen < MIO_RAPPEN) {
    return (rappen) => formatChfRappen(rappen);
  }
  const stepMio = stepRappen / MIO_RAPPEN;
  let decimals = 0;
  while (
    decimals < 3 &&
    Math.abs(stepMio * 10 ** decimals - Math.round(stepMio * 10 ** decimals)) > 1e-9
  ) {
    decimals += 1;
  }
  return (rappen) => {
    if (rappen === 0) return 'CHF 0';
    return `CHF ${(rappen / MIO_RAPPEN).toFixed(decimals)} Mio.`;
  };
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
