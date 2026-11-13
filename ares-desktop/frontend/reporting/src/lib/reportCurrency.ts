/**
 * G7 N-894-10: Mandatswaehrung des Berichts (advisory_report ``mandate_currency``)
 * fuer alle Betragsformatter im React-Bericht. Ohne Provider: CHF.
 */
import { createContext, useContext } from 'react';

export const DEFAULT_REPORT_CURRENCY = 'CHF';

export const ReportCurrencyContext = createContext<string>(DEFAULT_REPORT_CURRENCY);

/** Normalisierte Mandatswaehrung aus dem Bericht-Payload. */
export function reportCurrencyFrom(report: { mandate_currency?: string | null } | null | undefined): string {
  const raw = String(report?.mandate_currency ?? '').toUpperCase().trim();
  return raw || DEFAULT_REPORT_CURRENCY;
}

export function useReportCurrency(): string {
  return useContext(ReportCurrencyContext);
}
