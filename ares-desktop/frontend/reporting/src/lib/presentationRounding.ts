/**
 * G7 -- gemeinsamer Rundungsformatter (Policy "ares-rounding/1") fuer den
 * React-Report. Identischer Vertrag zu
 *   - ares-backend/core/presentation_rounding.py (PDF/Backend)
 *   - ares-desktop/frontend/presentation-rounding.js  (Classic-App)
 * gekoppelt ueber den Golden-Vektor
 * ares-backend/core/presentation_rounding_golden.json (presentationRounding.test.ts
 * und test_presentation_rounding_parity.py lesen ihn).
 *
 * Exakte Dezimalarithmetik (BigInt), ROUND_HALF_UP symmetrisch, kein
 * toFixed/Math.round auf Anzeigewerten; Zahlen ueber String(n). Auf 0
 * gerundet ohne Vorzeichen; Apostroph U+0027; keine Angabe -> U+2014.
 * Typografie "screen" (Default, App): Minus U+2212, U+00A0 vor "%".
 */

export const POLICY_VERSION = 'ares-rounding/1';
export const NO_VALUE = '—';
export const CANONICAL_ASSET_CLASS_ORDER = [
  'equities', 'bonds', 'real_estate', 'alternatives', 'liquidity',
] as const;

export type Typography = 'plain' | 'screen';
export interface FormatOptions { typography?: Typography; signed?: boolean }
interface Dec { neg: boolean; coef: bigint; exp: number }
export type Numeric = number | string | bigint | null | undefined;

const TYPO: Record<Typography, { minus: string; pctSep: string }> = {
  plain: { minus: '-', pctSep: ' ' },
  screen: { minus: '−', pctSep: ' ' },
};
export const CURRENCY_EXPONENTS: Record<string, number> = {
  CHF: 2, EUR: 2, USD: 2, GBP: 2, SEK: 2, NOK: 2, DKK: 2, CAD: 2, AUD: 2, JPY: 0,
};
const NUM_RE = /^([+-]?)(\d*)(?:\.(\d*))?(?:e([+-]?\d+))?$/i;
const ZERO = BigInt(0);
const ONE = BigInt(1);
const TWO = BigInt(2);
const TEN = BigInt(10);

function glyphs(t?: Typography) {
  return TYPO[t ?? 'screen'];
}
function pow10(n: number): bigint {
  let r = ONE;
  for (let i = 0; i < n; i += 1) r *= TEN;
  return r;
}
function isDec(v: unknown): v is Dec {
  return typeof v === 'object' && v !== null && typeof (v as Dec).coef === 'bigint';
}

export function toDecimal(value: Numeric | Dec): Dec | null {
  if (value === null || value === undefined || typeof value === 'boolean') return null;
  if (isDec(value)) return value;
  if (typeof value === 'bigint') return { neg: value < ZERO, coef: value < ZERO ? -value : value, exp: 0 };
  let s: string;
  if (typeof value === 'number') {
    if (!Number.isFinite(value)) return null;
    s = String(value);
  } else {
    s = String(value).trim();
    if (!s) return null;
  }
  const m = NUM_RE.exec(s);
  if (!m || (m[2] === '' && (m[3] === undefined || m[3] === ''))) return null;
  const frac = m[3] ?? '';
  const coef = BigInt((m[2] || '0') + frac);
  return { neg: m[1] === '-' && coef !== ZERO, coef, exp: (m[4] ? parseInt(m[4], 10) : 0) - frac.length };
}
function scale(d: Dec, k: number): Dec {
  return { neg: d.neg, coef: d.coef, exp: d.exp + k };
}
function roundUnits(d: Dec, decimals: number): { neg: boolean; units: bigint } {
  const shift = d.exp + decimals;
  let units: bigint;
  if (shift >= 0) units = d.coef * pow10(shift);
  else {
    const p = pow10(-shift);
    const q = d.coef / p;
    const r = d.coef % p;
    units = TWO * r >= p ? q + ONE : q;
  }
  return { neg: d.neg && units !== ZERO, units };
}
function group(intDigits: string): string {
  return intDigits.replace(/\B(?=(\d{3})+(?!\d))/g, "'");
}
function digits(units: bigint, decimals: number): string {
  let s = units.toString();
  if (decimals <= 0) return group(s);
  while (s.length <= decimals) s = `0${s}`;
  return `${group(s.slice(0, s.length - decimals))}.${s.slice(s.length - decimals)}`;
}

export function formatDecimal(value: Numeric | Dec, decimals = 0, opts: FormatOptions = {}): string {
  const d = toDecimal(value);
  if (!d) return NO_VALUE;
  const r = roundUnits(d, decimals);
  const body = digits(r.units, decimals);
  if (r.neg) return glyphs(opts.typography).minus + body;
  if (opts.signed && r.units !== ZERO) return `+${body}`;
  return body;
}
export function formatPercent(valuePct: Numeric | Dec, decimals = 1, opts: FormatOptions = {}): string {
  const core = formatDecimal(valuePct, decimals, opts);
  return core === NO_VALUE ? core : `${core}${glyphs(opts.typography).pctSep}%`;
}
export function formatPercentBps(bps: Numeric, decimals = 1, opts: FormatOptions = {}): string {
  const d = toDecimal(bps);
  if (!d) return NO_VALUE;
  return formatPercent(scale(d, -2), decimals, opts);
}
export function formatProbabilityPct(valuePct: Numeric, opts: FormatOptions = {}): string {
  return formatPercent(valuePct, 0, opts);
}
export function currencyExponent(currency: string): number {
  const c = String(currency ?? '').toUpperCase().trim();
  if (!(c in CURRENCY_EXPONENTS)) throw new Error(`Minor-Unit-Exponent unbekannt: ${currency}`);
  return CURRENCY_EXPONENTS[c];
}
export function minorExponent(currency: string): number {
  const c = String(currency ?? '').toUpperCase().trim();
  return c in CURRENCY_EXPONENTS ? CURRENCY_EXPONENTS[c] : 2;
}
function unitOf(currency: string): string {
  const c = String(currency ?? '').toUpperCase().trim();
  if (!c) throw new Error('Waehrung ist Pflicht');
  return c;
}
export function formatMoneyMinor(
  minor: Numeric, currency: string, exponent: number, decimals: number | null = null,
  opts: FormatOptions = {},
): string {
  const unit = unitOf(currency);
  const d = toDecimal(minor);
  if (!d) return NO_VALUE;
  const shown = decimals == null ? exponent : decimals;
  return `${unit} ${formatDecimal(scale(d, -exponent), shown, opts)}`;
}
export function formatSignedMoneyMinor(
  minor: Numeric, currency: string, exponent: number, decimals: number | null = null,
  opts: FormatOptions = {},
): string {
  const unit = unitOf(currency);
  const d = toDecimal(minor);
  if (!d) return NO_VALUE;
  const shown = decimals == null ? exponent : decimals;
  const r = roundUnits(scale(d, -exponent), shown);
  const body = digits(r.units, shown);
  if (r.units === ZERO) return `${unit} ${body}`;
  return `${r.neg ? glyphs(opts.typography).minus : '+'}${unit} ${body}`;
}
function absGreaterEqualMillion(d: Dec): boolean {
  const shift = d.exp - 6;
  if (shift >= 0) return d.coef !== ZERO;
  return d.coef >= pow10(-shift);
}
export function formatCompactAmount(major: Numeric | Dec, opts: FormatOptions = {}): string {
  const d = toDecimal(major);
  if (!d) return NO_VALUE;
  if (absGreaterEqualMillion(d)) return `${formatDecimal(scale(d, -6), 2, opts)} Mio.`;
  return formatDecimal(d, 0, opts);
}
export function formatMoneyCompactMinor(
  minor: Numeric, currency: string, exponent: number, opts: FormatOptions = {},
): string {
  const unit = String(currency ?? '').toUpperCase().trim();
  const d = toDecimal(minor);
  if (!d) return NO_VALUE;
  return `${unit} ${formatCompactAmount(scale(d, -exponent), opts)}`;
}

/** Largest Remainder; Einheit = 10^-decimals Prozent; Gleichstand = Eingabereihenfolge. */
export function apportionUnits(values: Numeric[], decimals: number, targetUnits: bigint | null): bigint[] {
  const ds = values.map((v) => {
    const d = toDecimal(v);
    if (!d) throw new Error('Apportionierung braucht Werte');
    if (d.neg) throw new Error('Apportionierung nur fuer nicht-negative Gewichte');
    return scale(d, decimals - 2);
  });
  let e = 0;
  ds.forEach((d) => { if (d.exp < e) e = d.exp; });
  const p = pow10(-e);
  const ints = ds.map((d) => d.coef * pow10(d.exp - e));
  const units = ints.map((v) => v / p);
  const rems = ints.map((v) => v % p);
  const sum = ints.reduce((a, b) => a + b, ZERO);
  const target = targetUnits ?? roundUnits({ neg: false, coef: sum, exp: e }, 0).units;
  const missing = target - units.reduce((a, b) => a + b, ZERO);
  const withRem = rems.filter((r) => r !== ZERO).length;
  if (missing < ZERO || missing > BigInt(withRem)) throw new Error('Ziel der Apportionierung unvereinbar');
  const order = units.map((_, i) => i).sort((a, b) => {
    if (rems[a] !== rems[b]) return rems[a] > rems[b] ? -1 : 1;
    return a - b;
  });
  for (let k = 0; BigInt(k) < missing; k += 1) units[order[k]] += ONE;
  return units;
}
function targetUnitsFromDisplay(targetDisplay: Numeric, decimals: number): bigint | null {
  if (targetDisplay === null || targetDisplay === undefined) return null;
  const d = toDecimal(targetDisplay);
  if (!d) throw new Error('targetDisplay fehlt');
  return roundUnits(d, decimals).units;
}
function unitsToDecimal(u: bigint, decimals: number): Dec {
  return { neg: false, coef: u, exp: -decimals };
}
export function formatApportionedPercentBps(
  values: Numeric[], decimals = 1, opts: FormatOptions & { targetDisplay?: Numeric } = {},
): string[] {
  const units = apportionUnits(values, decimals, targetUnitsFromDisplay(opts.targetDisplay, decimals));
  return units.map((u) => formatPercent(unitsToDecimal(u, decimals), decimals, opts));
}
const ASSET_KEYS: Record<string, string> = {
  aktien: 'equities', equities: 'equities', obligationen: 'bonds', anleihen: 'bonds', bonds: 'bonds',
  immobilien: 'real_estate', real_estate: 'real_estate', 'real estate': 'real_estate', alternative: 'alternatives',
  alternativen: 'alternatives', alternatives: 'alternatives', liquiditaet: 'liquidity', 'liquidität': 'liquidity',
  liquidity: 'liquidity',
};
export function assetClassKey(label: unknown): string {
  const raw = String(label ?? '').trim();
  return ASSET_KEYS[raw.toLowerCase()] ?? raw;
}
function wholeUnits(minor: Numeric, exponent: number): bigint {
  const d = toDecimal(minor);
  if (!d) return ZERO;
  const r = roundUnits(scale(d, -exponent), 0);
  return r.neg ? -r.units : r.units;
}
/** Largest Remainder; Gleichstand: groesseres Gewicht, dann Label, dann Position. */
export function splitLargestRemainder(total: bigint, weights: Numeric[], labels: string[]): bigint[] {
  const clean = weights.map((w) => BigInt(Math.max(0, Math.round(Number(w) || 0))));
  const sum = clean.reduce((a, b) => a + b, ZERO);
  if (sum <= ZERO || total <= ZERO) return clean.map(() => ZERO);
  const floors = clean.map((w) => (total * w) / sum);
  const rems = clean.map((w) => (total * w) % sum);
  const order = clean.map((_, i) => i).sort((a, b) => {
    if (rems[a] !== rems[b]) return rems[a] > rems[b] ? -1 : 1;
    if (clean[a] !== clean[b]) return clean[a] > clean[b] ? -1 : 1;
    if (labels[a] !== labels[b]) return labels[a] < labels[b] ? -1 : 1;
    return a - b;
  });
  const missing = total - floors.reduce((a, b) => a + b, ZERO);
  for (let k = 0; BigInt(k) < missing; k += 1) floors[order[k]] += ONE;
  return floors;
}
/** Soll-Betraege in ganzen Einheiten (identisch zu core/presentation_rounding.py). */
export function presentationAmounts(
  advisoryMinor: Numeric, baseMinor: Numeric, weights: Numeric[], labels: unknown[], exponent = 2,
) {
  const adv = Math.max(0, Math.round(Number(advisoryMinor) || 0));
  const baseRaw = baseMinor === null || baseMinor === undefined ? adv : Math.max(0, Math.round(Number(baseMinor) || 0));
  const base = wholeUnits(Math.min(baseRaw, adv), exponent);
  const advisory = wholeUnits(adv, exponent);
  const keys = labels.map(assetClassKey);
  const buckets = base > ZERO ? splitLargestRemainder(base, weights, keys) : keys.map(() => ZERO);
  const reserve = advisory - base;
  return {
    advisory: Number(advisory), base: Number(base), reserve: Number(reserve > ZERO ? reserve : ZERO),
    buckets: buckets.map((u) => Number(u)),
  };
}
export function canonicalRank(key: string): number {
  const i = (CANONICAL_ASSET_CLASS_ORDER as readonly string[]).indexOf(String(key ?? ''));
  return i < 0 ? CANONICAL_ASSET_CLASS_ORDER.length : i;
}
export function presentationArtifact(raw: unknown, unit: string, display: string) {
  return { raw, unit, policy_version: POLICY_VERSION, display };
}

/** Golden-Fall ausfuehren (gleiche Funktionsnamen wie Python/Classic). */
export function runCase(fn: string, args: unknown[], typography: Typography): string | string[] {
  const o: FormatOptions = { typography };
  const a = args as Numeric[];
  const opt = (i: number, dflt: number) => (args.length > i ? Number(args[i]) : dflt);
  switch (fn) {
    case 'number': return formatDecimal(a[0], opt(1, 0), o);
    case 'signed_number': return formatDecimal(a[0], opt(1, 0), { typography, signed: true });
    case 'percent_bps': return formatPercentBps(a[0], opt(1, 1), o);
    case 'signed_percent_bps': return formatPercentBps(a[0], opt(1, 1), { typography, signed: true });
    case 'percent': return formatPercent(a[0], opt(1, 1), o);
    case 'probability_pct': return formatProbabilityPct(a[0], o);
    case 'money_minor':
      return formatMoneyMinor(a[0], String(args[1]), Number(args[2]), args.length > 3 ? Number(args[3]) : null, o);
    case 'signed_money_minor':
      return formatSignedMoneyMinor(a[0], String(args[1]), Number(args[2]), args.length > 3 ? Number(args[3]) : null, o);
    case 'money_compact_minor': return formatMoneyCompactMinor(a[0], String(args[1]), Number(args[2]), o);
    case 'apportion_percent_bps':
      return formatApportionedPercentBps(args[0] as Numeric[], Number(args[1]), {
        typography, targetDisplay: args.length > 2 ? (args[2] as Numeric) : null,
      });
    case 'presentation_amounts': {
      const pa = presentationAmounts(a[0], a[1], args[2] as Numeric[], args[3] as unknown[], opt(4, 2));
      return [String(pa.advisory), String(pa.base), String(pa.reserve), ...pa.buckets.map(String)];
    }
    case 'apportioned_sum': {
      const n = opt(1, 1);
      const u = apportionUnits(args[0] as Numeric[], n, null).reduce((x, y) => x + y, ZERO);
      return formatPercent(unitsToDecimal(u, n), n, o);
    }
    default: throw new Error(`unbekannte Golden-Funktion ${fn}`);
  }
}
