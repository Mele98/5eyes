/**
 * U-FE-1: Schweizer Zahlen-Formatierung für die Sub-App.
 *
 * Apostroph als Tausenderzeichen (nicht Komma/Punkt), bps → %, etc.
 * Identische Konventionen zum PDF-Helper `services/pdf/components/swiss_numbers.py`,
 * damit Web + PDF visuell identisch sind.
 *
 * AA-UX-FORMAT-001: EIN Zahlenformat-Vertrag für App (Monolith ares.html,
 * Funktionen fmtNumber/fmtPct/fmtSignedPct/fmtProbPct/fmtSharpe) und Report.
 * Beide Implementierungen werden in
 * ares-backend/tests/test_monolith_number_format_contract.py mit denselben
 * Fällen ausgeführt (Node, Type-Stripping) -- Abweichung = roter Test.
 *
 *  - Prozent: feste Nachkommastellen (Default 1), Dezimalpunkt wie de-CH,
 *    geschütztes Leerzeichen (U+00A0) vor „%": 1234 bps -> „12.3 %".
 *  - Minus immer U+2212 („−"), nie Bindestrich; „+" nur bei signierten
 *    Werten; ein auf 0 gerundeter Wert trägt kein Vorzeichen.
 *  - Wahrscheinlichkeiten ganzzahlig, Sharpe-Ratio 2 Stellen.
 *  - CHF kompakt ab 1 Mio. immer „Mio." mit 2 Stellen („CHF 2.85 Mio.").
 *  - Tausendertrennung IMMER gerades Apostroph U+0027 („CHF 1'250'000",
 *    CIO-Entscheid 2026-10-19; robust in PDF/CSV/Excel, wie die Backend-PDFs).
 *    Nie toLocaleString('de-CH') direkt verwenden (ICU liefert U+2019).
 *    Eingaben akzeptieren beide Zeichen: parseNumberInputCH().
 */

import {
  formatCompactAmount,
  formatDecimal,
  formatPercentBps,
  formatStoredAmount,
  formatProbabilityPct,
} from './presentationRounding.ts';

// G7: alle Rundungen laufen ueber presentationRounding.ts (Policy
// ares-rounding/1, Decimal ROUND_HALF_UP; identisch zu Classic und PDF).
export const MINUS = '−';
const SCREEN = { typography: 'screen' as const };
// G7 Nachtrag 4 (Grundregel): Jeder Geldformatter verlangt die Waehrung, in der
// der Betrag vorliegt; ``null`` = unbekannt -> "—" (keine geratene Einheit).

/**
 * Eingabe -> Zahl. Akzeptiert ' und ' (U+2019/U+02BC) als Tausendertrennung,
 * Leerzeichen, Dezimalkomma und U+2212 als Minus. Leer/ungueltig -> null.
 */
export function parseNumberInputCH(value: string | null | undefined): number | null {
  const t = String(value ?? '')
    .replace(/^\s*CHF\s*/i, '')
    .replace(/['\u2019\u02BC\s]/g, '')
    .replace(/\u2212/g, '-')
    .replace(',', '.');
  if (t === '') return null;
  const n = Number(t);
  return Number.isFinite(n) ? n : null;
}

/** Ganze CHF aus Rappen: „CHF 12'345" (gerades Apostroph). */
export function formatChfFromRappen(rappen: number, currency: string | null): string {
  if (!currency) return '—';
  return formatStoredAmount(rappen, currency, 0, SCREEN);
}

/** Zahl mit fester Nachkommastellenzahl, Apostroph-Gruppierung, U+2212. */
export function fmtNumber(value: number | null | undefined, decimals = 0): string {
  if (value === null || value === undefined) return '—';
  return formatDecimal(value, decimals, SCREEN);
}

/** bps -> „12.3 %" (feste Nachkommastellen). */
export function fmtPct(bps: number | null | undefined, decimals = 1): string {
  if (bps === null || bps === undefined) return '—';
  return formatPercentBps(bps, decimals, SCREEN);
}

/** bps -> „+12.3 %" / „−12.3 %" / „0.0 %". */
export function fmtSignedPct(bps: number | null | undefined, decimals = 1): string {
  if (bps === null || bps === undefined) return '—';
  return formatPercentBps(bps, decimals, { ...SCREEN, signed: true });
}

/** Wahrscheinlichkeit in Prozentpunkten (0..100) -> ganzzahlig „73 %". */
export function fmtProbPct(pct: number | null | undefined): string {
  if (pct === null || pct === undefined) return '—';
  return formatProbabilityPct(pct, SCREEN);
}

/** Sharpe-Ratio: 2 Stellen. */
export function fmtSharpe(value: number | null | undefined): string {
  return fmtNumber(value, 2);
}

/**
 * CHF-Betrag kompakt OHNE Waehrungspraefix: „2.85 Mio." / „850'000"
 * (Monolith: formatCompactCHFAmount). Nicht-endlich -> „—".
 */
export function fmtChfCompactAmount(chf: number | null | undefined): string {
  if (chf === null || chf === undefined) return '—';
  return formatCompactAmount(chf, SCREEN);
}

/** CHF (ganze Franken) kompakt: ab 1 Mio. „CHF 2.85 Mio.", darunter voll. */
export function fmtChfCompact(chf: number | null | undefined, currency: string | null): string {
  const amount = fmtChfCompactAmount(chf);
  return amount === '—' || !currency ? '—' : `${currency} ${amount}`;
}

export function formatChfRappen(
  rappen: number | null | undefined,
  options: { withUnit?: boolean; currency: string | null },
): string {
  const withUnit = options.withUnit !== false;
  const currency = options.currency;
  if (rappen === null || rappen === undefined || !Number.isFinite(Number(rappen))) return withUnit ? '—' : '0';
  if (!currency) {
    // Waehrung unbekannt: mit Einheit "—", ohne Einheit nur die Zahl (Achsen).
    return withUnit ? '—' : formatStoredAmount(Number(rappen), 'EUR', 0, SCREEN).slice('EUR '.length); // nur Zahl, EUR = Exponent-2-Platzhalter
  }
  const text = formatStoredAmount(Number(rappen), currency, 0, SCREEN);
  return withUnit ? text : text.slice(currency.length + 1);
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

/**
 * H9 Nachtrag 2: Horizont-Beschriftung "Ende JJJJ" wie in der Hauptapp
 * (projectionEndOfYearText). Projektionslabels markieren den Stand zu
 * Jahresbeginn; der letzte Punkt ist der Stand nach dem letzten inklusiven
 * Jahr -- Label 2041 = "Ende 2040".
 */
export function formatEndOfYear(label: string | number | null | undefined): string {
  const year = Number.parseInt(String(label ?? ''), 10);
  return Number.isFinite(year) ? `Ende ${year - 1}` : String(label ?? '');
}
