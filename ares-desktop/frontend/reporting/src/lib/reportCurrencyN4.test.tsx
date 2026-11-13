/**
 * G7 Nachtrag 4 (Grundregel): Ein Betrag traegt die Waehrung, in der er vorliegt.
 *
 * - MC-Pfade: Waehrung aus paths.amount_currency (Rohsumme ohne FX), nicht Mandat.
 * - Liquiditaetsbedarf: client_info.liquiditaetsbedarf_currency; unbekannt -> "—".
 * - N-894-14: Gruppenanteile gemeinsam apportioniert (69.4 % wie Soll-Tabellen).
 * - N-894-16: Editor-Routen laden die Mandatswaehrung (Provider); neue Cashflows
 *   in Mandatswaehrung, ohne Mandat Server-Default.
 */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';

vi.mock('@/api/mandate', () => ({
  fetchMandate: vi.fn(async () => ({ base_currency: 'eur' })),
  listMandates: vi.fn(async () => [
    { status: 'Inaktiv', base_currency: 'USD' },
    { status: 'Aktiv', base_currency: 'JPY' },
  ]),
}));
vi.mock('@/api/cashflow', () => ({
  fetchCashflows: vi.fn(async () => []),
  fetchDerivedCashflows: vi.fn(async () => []),
  createCashflow: vi.fn(),
  updateCashflow: vi.fn(),
  deleteCashflow: vi.fn(),
}));

import type { PositionGroup } from '@/api/types';
import { MonteCarloPathsChart } from '@/components/MonteCarloPathsChart';
import { Ausgangslage } from '@/pages/Ausgangslage';
import { Positionen } from '@/pages/Positionen';
import { CashflowEditor } from '@/sections/cashflow/CashflowEditor';
import { makeAusgangslage, makeGoalsWithPaths, makePositionen } from '@/test/fixtures';
import { MandateCurrencyProvider, ReportCurrencyContext, activeMandateCurrency, useReportCurrency } from './reportCurrency';

const plain = (t: string | null) => String(t ?? '').replace(/−/g, '-').replace(/ /g, ' ');

afterEach(() => vi.clearAllMocks());

describe('Grundregel: Waehrung der Quelle', () => {
  it('MC-Faecher/Achse in paths.amount_currency, auch wenn der Bericht JPY ist', () => {
    const gbi = makeGoalsWithPaths();
    const { container } = render(
      <ReportCurrencyContext.Provider value="JPY">
        <MonteCarloPathsChart paths={gbi.monte_carlo_paths} goals={[]} />
      </ReportCurrencyContext.Provider>,
    );
    const text = plain(container.textContent);
    expect(text).toMatch(/CHF \d/);
    expect(text).not.toMatch(/JPY \d/);
  });

  it('MC ohne bekannte Waehrung: keine geratene Einheit', () => {
    const gbi = makeGoalsWithPaths();
    const paths = { ...gbi.monte_carlo_paths, amount_currency: null };
    const { container } = render(
      <ReportCurrencyContext.Provider value="EUR">
        <MonteCarloPathsChart paths={paths} goals={[]} />
      </ReportCurrencyContext.Provider>,
    );
    expect(plain(container.textContent)).not.toMatch(/(CHF|EUR) \d/);
  });

  it('Liquiditaetsbedarf in liquiditaetsbedarf_currency; fehlt sie -> "—"', () => {
    const data = makeAusgangslage();
    const { container, rerender } = render(
      <ReportCurrencyContext.Provider value="EUR">
        <Ausgangslage data={data} />
      </ReportCurrencyContext.Provider>,
    );
    expect(plain(container.textContent)).toContain("CHF 66'000");
    rerender(
      <ReportCurrencyContext.Provider value="EUR">
        <Ausgangslage data={{ ...data, client_info: { ...data.client_info, liquiditaetsbedarf_currency: null } }} />
      </ReportCurrencyContext.Provider>,
    );
    expect(plain(container.textContent)).not.toContain("66'000");
  });

  it('N-894-14: Gruppenanteile apportioniert (69.4 % statt 69.3 %)', () => {
    const base = makePositionen();
    const shares: Array<[PositionGroup['key'], string, number]> = [
      ['equities', 'Aktien', 6933], ['bonds', 'Obligationen', 1751], ['real_estate', 'Immobilien', 551],
      ['alternatives', 'Alternative', 563], ['liquidity', 'Liquidität', 202],
    ];
    const groups = shares.map(([key, label, share_bps]) => ({ ...base.groups[0], key, label, share_bps, positions: [] }));
    const { container } = render(
      <ReportCurrencyContext.Provider value="CHF">
        <Positionen data={{ ...base, groups }} />
      </ReportCurrencyContext.Provider>,
    );
    const text = plain(container.textContent);
    expect(text).toContain('69.4 %');
    expect(text).not.toContain('69.3 %');
  });
});

describe('N-894-16: Editor-Routen mit Waehrungs-Provider', () => {
  function Show() {
    return <span data-testid="ccy">{useReportCurrency() ?? 'null'}</span>;
  }

  it('Mandats-Route laedt base_currency, Kunden-Route das aktive Mandat', async () => {
    const { unmount } = render(<MandateCurrencyProvider mandateId="m1"><Show /></MandateCurrencyProvider>);
    await waitFor(() => expect(screen.getByTestId('ccy').textContent).toBe('EUR'));
    unmount();
    render(<MandateCurrencyProvider clientId="c1"><Show /></MandateCurrencyProvider>);
    await waitFor(() => expect(screen.getByTestId('ccy').textContent).toBe('JPY'));
    expect(activeMandateCurrency([])).toBeNull();
  });

  it('neuer Cashflow: Label und Waehrung aus dem Mandat (EUR), ohne Mandat Server-Default', async () => {
    const { unmount } = render(
      <ReportCurrencyContext.Provider value="EUR">
        <CashflowEditor clientId="c1" />
      </ReportCurrencyContext.Provider>,
    );
    await screen.findByText(/Noch keine manuellen Cashflows/);
    fireEvent.click(screen.getByRole('button', { name: 'Neuer Cashflow' }));
    expect(screen.getByText(/Betrag \(EUR\)/)).toBeInTheDocument();
    unmount();
    render(<CashflowEditor clientId="c1" />);
    await screen.findByText(/Noch keine manuellen Cashflows/);
    fireEvent.click(screen.getByRole('button', { name: 'Neuer Cashflow' }));
    expect(screen.getByText(/Betrag \(CHF\)/)).toBeInTheDocument();
  });
});
