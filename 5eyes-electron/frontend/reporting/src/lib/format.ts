/**
 * U-FE-1: Schweizer Zahlen-Formatierung für die Sub-App.
 *
 * Apostroph als Tausenderzeichen (nicht Komma/Punkt), bps → %, etc.
 * Identische Konventionen zum PDF-Helper `services/pdf/components/swiss_numbers.py`,
 * damit Web + PDF visuell identisch sind.
 *
 * AA-UX-FORMAT-001: EIN Zahlenformat-Vertrag für App (Monolith 5eyes_v2.html,
 * Funktionen fmtNumber/fmtPct/fmtSignedPct/fmtProbPct/fmtSharpe) und Report.
 * Beide Implementierungen werden in
 * 5eyes-backend/tests/test_monolith_number_format_contract.py mit denselben
 * Fällen ausgeführt (Node, Type-Stripping) -- Abweichung = roter Test.
 *
 *  - Prozent: feste Nachkommastellen (Default 1), Dezimalpunkt wie de-CH,
 *    geschütztes Leerzeichen (U+00A0) vor „%": 1234 bps -> „12.3 %".
 *  - Minus immer U+2212 („−"), nie Bindestrich; „+" nur bei signierten
 *    Werten; ein auf 0 gerundeter Wert trägt kein Vorzeichen.
 *  - Wahrscheinlichkeiten ganzzahlig, Sharpe-Ratio 2 Stellen.
 *  - CHF kompakt ab 1 Mio. immer „Mio." mit 2 Stellen („CHF 2.85 Mio.").
 */

export const MINUS = '−';
const PCT_SUFFIX = ' %';

function groupThousands(intPart: string): string {
  return intPart.replace(/\B(?=(\d{3})+(?!\d))/g, "'");
}

/** Zahl mit fester Nachkommastellenzahl, Apostroph-Gruppierung, U+2212. */
export function fmtNumber(value: number | null | undefined, decimals = 0): string {
  if (value === null || value === undefined) return '—';
  const n = Number(value);
  if (!Number.isFinite(n)) return '—';
  const fixed = Math.abs(n).toFixed(decimals);
  const [intPart, frac] = fixed.split('.');
  const body = frac !== undefined ? `${groupThousands(intPart)}.${frac}` : groupThousands(intPart);
  return n < 0 && Number(fixed) !== 0 ? `${MINUS}${body}` : body;
}

/** bps -> „12.3 %" (feste Nachkommastellen). */
export function fmtPct(bps: number | null | undefined, decimals = 1): string {
  if (bps === null || bps === undefined) return '—';
  const n = Number(bps);
  if (!Number.isFinite(n)) return '—';
  return `${fmtNumber(n / 100, decimals)}${PCT_SUFFIX}`;
}

/** bps -> „+12.3 %" / „−12.3 %" / „0.0 %". */
export function fmtSignedPct(bps: number | null | undefined, decimals = 1): string {
  const core = fmtPct(bps, decimals);
  if (core === '—') return core;
  const n = Number(bps);
  const rounded = Number((Math.abs(n) / 100).toFixed(decimals));
  return n > 0 && rounded !== 0 ? `+${core}` : core;
}

/** Wahrscheinlichkeit in Prozentpunkten (0..100) -> ganzzahlig „73 %". */
export function fmtProbPct(pct: number | null | undefined): string {
  if (pct === null || pct === undefined) return '—';
  const n = Number(pct);
  if (!Number.isFinite(n)) return '—';
  return `${fmtNumber(Math.round(n), 0)}${PCT_SUFFIX}`;
}

/** Sharpe-Ratio: 2 Stellen. */
export function fmtSharpe(value: number | null | undefined): string {
  return fmtNumber(value, 2);
}

/** CHF (ganze Franken) kompakt: ab 1 Mio. „CHF 2.85 Mio.", darunter voll. */
export function fmtChfCompact(chf: number | null | undefined): string {
  if (chf === null || chf === undefined) return '—';
  const n = Number(chf);
  if (!Number.isFinite(n)) return '—';
  const a = Math.abs(n);
  const sign = n < 0 && Math.round(a) > 0 ? MINUS : '';
  if (a >= 1_000_000) return `CHF ${sign}${fmtNumber(a / 1_000_000, 2)} Mio.`;
  return `CHF ${sign}${fmtNumber(Math.round(a), 0)}`;
}

export function formatChfRappen(
  rappen: number | null | undefined,
  options: { withUnit?: boolean } = {},
): string {
  const withUnit = options.withUnit !== false;
  if (rappen === null || rappen === undefined) return withUnit ? '—' : '0';
  const value = Math.round(Number(rappen) / 100);
  if (!Number.isFinite(value)) return withUnit ? '—' : '0';
  const formatted = fmtNumber(value, 0);
  return withUnit ? `CHF ${formatted}` : formatted;
}

export function formatBpsAsPct(
  bps: number | null | undefined,
  options: { decimals?: number } = {},
): string {
  return fmtPct(bps, options.decimals ?? 1);
}

export function formatBpsSignedPct(
  bps: number | null | undefined,
  options: { decimals?: number } = {},
): string {
  return fmtSignedPct(bps, options.decimals ?? 1);
}

export function formatInteger(value: number | null | undefined): string {
  if (value === null || value === undefined) return '—';
  const n = Math.round(Number(value));
  if (!Number.isFinite(n)) return '—';
  return n.toString();
}

export function formatAge(age: number | null | undefined): string {
  if (age === null || age === undefined) return '—';
  const n = Math.round(Number(age));
  if (!Number.isFinite(n) || n <= 0) return '—';
  return `${n} Jahre`;
}

export function formatHorizon(years: number | null | undefined): string {
  if (years === null || years === undefined) return '—';
  const n = Math.round(Number(years));
  if (!Number.isFinite(n) || n <= 0) return '—';
  return `${n} Jahre`;
}
