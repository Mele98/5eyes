/**
 * G7 N-894-10 / Nachtrag 4 (Grundregel): Ein Betrag wird immer mit der Waehrung
 * beschriftet, in der er tatsaechlich vorliegt. Dieser Kontext liefert nur die
 * Mandatswaehrung fuer Betraege, die in Mandatswaehrung vorliegen (Engine-/
 * Allokationswerte, Ziele, Positionen des Berichts). Betraege mit eigener
 * Waehrung (Cashflow, Monte-Carlo-Rohsummen, Liquiditaetsbedarf) tragen ihre
 * Waehrung selbst. Unbekannt -> ``null`` -> Formatter zeigen "—".
 */
import { createContext, createElement, useContext, useEffect, useState, type ReactNode } from 'react';

import { fetchMandate, listMandates } from '@/api/mandate';

export const ReportCurrencyContext = createContext<string | null>(null);

function norm(raw: unknown): string | null {
  const s = String(raw ?? '').toUpperCase().trim();
  return s || null;
}

/** Mandatswaehrung aus dem Bericht-Payload; fehlt sie, unbekannt (null). */
export function reportCurrencyFrom(report: { mandate_currency?: string | null } | null | undefined): string | null {
  return norm(report?.mandate_currency);
}

/**
 * Waehrung des aktiven Mandats eines Kunden -- dieselbe Regel wie Classic
 * (ares.html loadClientById: erstes Mandat mit status 'Aktiv', sonst das erste).
 * Kein Mandat -> null.
 */
export function activeMandateCurrency(mandates: Array<{ base_currency?: string | null; status?: string | null }>): string | null {
  const active = mandates.find((m) => m && m.status === 'Aktiv') ?? mandates[0];
  return active ? norm(active.base_currency) : null;
}

export function useReportCurrency(): string | null {
  return useContext(ReportCurrencyContext);
}

/**
 * N-894-16: Editor-Routen laden die Mandatswaehrung selbst (Mandat bzw. alle
 * Mandate des Kunden) und setzen den Provider. Bis zum Laden bzw. bei mehreren
 * Waehrungen: null.
 */
export function MandateCurrencyProvider({
  mandateId,
  clientId,
  children,
}: {
  mandateId?: string;
  clientId?: string;
  children: ReactNode;
}) {
  const [currency, setCurrency] = useState<string | null>(null);
  useEffect(() => {
    let alive = true;
    const load = mandateId
      ? fetchMandate(mandateId).then((m) => norm(m.base_currency))
      : clientId
        ? listMandates(clientId).then(activeMandateCurrency)
        : Promise.resolve(null);
    load.then(
      (c) => { if (alive) setCurrency(c); },
      () => { if (alive) setCurrency(null); },
    );
    return () => { alive = false; };
  }, [mandateId, clientId]);
  return createElement(ReportCurrencyContext.Provider, { value: currency }, children);
}
