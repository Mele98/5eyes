/**
 * U-FE-1: Schweizer Zahlen-Formatierung für die Sub-App.
 *
 * Apostroph als Tausenderzeichen (nicht Komma/Punkt), bps → %, etc.
 * Identische Konventionen zum PDF-Helper `services/pdf/components/swiss_numbers.py`,
 * damit Web + PDF visuell identisch sind.
 */

export function formatChfRappen(
  rappen: number | null | undefined,
  options: { withUnit?: boolean } = {},
): string {
  const withUnit = options.withUnit !== false;
  if (rappen === null || rappen === undefined) return withUnit ? '—' : '0';
  const value = Math.round(Number(rappen) / 100);
  if (!Number.isFinite(value)) return withUnit ? '—' : '0';
  const formatted = value.toString().replace(/\B(?=(\d{3})+(?!\d))/g, "'");
  return withUnit ? `CHF ${formatted}` : formatted;
}

export function formatBpsAsPct(
  bps: number | null | undefined,
  options: { decimals?: number } = {},
): string {
  if (bps === null || bps === undefined) return '—';
  const decimals = options.decimals ?? 1;
  const pct = Number(bps) / 100;
  if (!Number.isFinite(pct)) return '—';
  return `${pct.toFixed(decimals)} %`;
}

export function formatBpsSignedPct(
  bps: number | null | undefined,
  options: { decimals?: number } = {},
): string {
  if (bps === null || bps === undefined) return '—';
  const decimals = options.decimals ?? 1;
  const pct = Number(bps) / 100;
  if (!Number.isFinite(pct)) return '—';
  const sign = pct >= 0 ? '+' : '';
  return `${sign}${pct.toFixed(decimals)} %`;
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
