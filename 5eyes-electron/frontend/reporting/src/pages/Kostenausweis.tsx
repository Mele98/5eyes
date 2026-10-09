/**
 * CERT-COST-PUBLICATION-001 (COST-PUBLICATION-001, 2026-10-09): Sektion 17 —
 * FIDLEG Art. 8/9 Ex-ante-Kostenausweis.
 *
 * Derselbe geschuetzte Backend-Report, den der Standalone- und der
 * Advisory-PDF bereits zeigen (services/cost_disclosure.py::
 * calculate_cost_disclosure(), services/advisory_report.py:411) -- diese
 * Seite rendert NUR, berechnet nichts neu (spec Section 13: "Keine zweite
 * Kostenberechnung in React, Monolith oder PDF einfuehren").
 *
 * Currency-/null-/frequency-sichere Darstellung (COST-RENDER-SEMANTICS-001):
 * - Betraege nutzen IMMER data.currency, nie ein hartkodiertes "CHF".
 * - rate_bps=null wird als "—" dargestellt, nie als "0.00 %".
 * - frequency ist der bereits lokalisierte Backend-Text, unveraendert
 *   uebernommen (nie auf "p.a." zusammengefaltet).
 * - audit_degraded=true zeigt einen sichtbaren Blocked-Status statt die
 *   Zahlen als vollstaendig/verlaesslich darzustellen
 *   (COST-PUBLICATION-GATE-001).
 */
import type { CostDisclosureData, CostDisclosureItem } from '@/api/types';
import { ReportPage } from '@/components/ReportPage';
import { formatBpsAsPct } from '@/lib/format';

interface KostenausweisProps {
  data: CostDisclosureData;
}

/** Lokaler, currency-bewusster Rappen-Formatter -- bewusst NICHT der
 * geteilte `formatChfRappen()` aus lib/format.ts, der (wie der Monolith vor
 * diesem Fix) die Einheit hartkodiert auf "CHF" setzt. Diese Sektion ist die
 * einzige im Reporting-App, die eine vom Mandat abweichende Fremdwaehrung
 * (EUR/USD) korrekt ausweisen muss. */
function formatMoneyRappen(rappen: number | null | undefined, currency: string): string {
  if (rappen === null || rappen === undefined) return '—';
  const value = Math.round(Number(rappen) / 100);
  if (!Number.isFinite(value)) return '—';
  const formatted = value.toString().replace(/\B(?=(\d{3})+(?!\d))/g, "'");
  const unit = (currency || 'CHF').toUpperCase().trim() || 'CHF';
  return `${unit} ${formatted}`;
}

function formatRate(rateBps: number | null): string {
  if (rateBps === null || rateBps === undefined) return '—';
  return formatBpsAsPct(rateBps, { decimals: 2 });
}

export function Kostenausweis({ data }: KostenausweisProps) {
  const currency = (data?.currency || 'CHF').toUpperCase().trim() || 'CHF';
  const totals = data?.totals;
  const items = data?.cost_items ?? [];
  const warnings = (data?.warnings ?? []).filter(Boolean);
  const isDegraded = Boolean(data?.audit_degraded);
  const isPending = Boolean(data?.data_pending);

  return (
    <ReportPage
      nr={17}
      kicker="FIDLEG Kostentransparenz"
      title="Kostenausweis ex-ante"
      subtitle="Voraussichtliche Kosten der empfohlenen Finanzdienstleistung und des Zielportfolios."
    >
      {isDegraded ? (
        <StatusBanner
          tone="blocked"
          title="Kostenausweis nicht verfügbar"
          body="Die Kostenberechnung ist fehlgeschlagen (degraded evidence). Dieser Bericht darf unter dem Publikations-Gate nicht als client-ready Dokument gelten, solange keine vollständige Kostenbasis vorliegt."
        />
      ) : isPending ? (
        <StatusBanner
          tone="pending"
          title="Daten ausstehend"
          body={warnings[0] || 'Noch keine Portfolioempfehlung vorhanden; ein konkreter Ex-ante-Kostenausweis kann noch nicht berechnet werden.'}
        />
      ) : (
        <>
          <dl className="grid grid-cols-2 gap-3 border border-rule bg-canvas-subtle p-4 md:grid-cols-4">
            <SummaryTile label="Anlagebasis" value={formatMoneyRappen(data.advisory_wealth_rappen, currency)} />
            <SummaryTile label="Einmalig" value={formatMoneyRappen(totals?.one_time_rappen, currency)} />
            <SummaryTile label="Laufend p.a." value={formatMoneyRappen(totals?.annual_rappen, currency)} />
            <SummaryTile label="Erstes Jahr" value={formatMoneyRappen(totals?.first_year_rappen, currency)} />
          </dl>

          {items.length === 0 ? (
            <p className="mt-block italic text-caption text-ink-subtle">
              Keine Kostenposten ausweisbar.
            </p>
          ) : (
            <table className="mt-block w-full text-caption" aria-label="Kostenausweis-Positionen">
              <caption className="sr-only">
                Kostenposten des Ex-ante-Kostenausweises, mit Turnus, Satz, Betrag und Berechnungsbasis.
              </caption>
              <thead>
                <tr className="border-b border-rule">
                  <th scope="col" className="pb-2 pr-3 text-left font-medium uppercase tracking-widest text-micro text-ink-subtle">Kostenart</th>
                  <th scope="col" className="pb-2 pr-3 text-right font-medium uppercase tracking-widest text-micro text-ink-subtle">Turnus</th>
                  <th scope="col" className="pb-2 pr-3 text-right font-medium uppercase tracking-widest text-micro text-ink-subtle">Satz</th>
                  <th scope="col" className="pb-2 pr-3 text-right font-medium uppercase tracking-widest text-micro text-ink-subtle">Betrag</th>
                  <th scope="col" className="pb-2 text-left font-medium uppercase tracking-widest text-micro text-ink-subtle">Basis</th>
                </tr>
              </thead>
              <tbody>
                {items.map((item) => (
                  <CostItemRow key={item.key} item={item} currency={currency} />
                ))}
              </tbody>
            </table>
          )}

          {warnings.length > 0 ? (
            <div className="mt-block border-l-4 border-accent bg-canvas-subtle px-5 py-4">
              <p className="text-micro uppercase tracking-widest text-ink-subtle">
                Annahmen und Datenqualität
              </p>
              <ul className="mt-2 space-y-1 text-caption text-ink-muted">
                {warnings.map((w, idx) => (
                  <li key={idx}>{w}</li>
                ))}
              </ul>
            </div>
          ) : null}
        </>
      )}

      <p className="mt-section border-t border-rule pt-3 text-micro text-ink-subtle">
        {data?.fidleg_basis || 'Art. 8/9 FIDLEG; Art. 8/14 FIDLEV'}
        {data?.source_run_id ? ` · Snapshot ${data.source_run_id}` : ''}
      </p>
    </ReportPage>
  );
}

function SummaryTile({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-micro font-semibold uppercase tracking-widest text-ink-subtle">{label}</dt>
      <dd className="mt-1 font-mono text-h3 text-ink">{value}</dd>
    </div>
  );
}

function CostItemRow({ item, currency }: { item: CostDisclosureItem; currency: string }) {
  const label = item.is_estimate ? `${item.label} *` : item.label;
  // COST-RENDER-SEMANTICS-001: frequency ist bereits der lokalisierte
  // Backend-Text (einmalig/jährlich/monatlich/quartalsweise/"nicht
  // erfasst") -- unveraendert uebernommen, nie auf "p.a." zusammengefaltet.
  const frequency = item.frequency?.trim() || 'nicht erfasst';
  return (
    <tr className="border-b border-rule last:border-b-0">
      <td className="py-2 pr-3 align-top text-ink">{label}</td>
      <td className="py-2 pr-3 text-right align-top text-ink-muted">{frequency}</td>
      <td className="py-2 pr-3 text-right align-top font-mono text-ink">{formatRate(item.rate_bps)}</td>
      <td className="py-2 pr-3 text-right align-top font-mono font-semibold text-ink">
        {formatMoneyRappen(item.amount_rappen, currency)}
      </td>
      <td className="py-2 align-top text-micro text-ink-subtle">{item.basis_label || '—'}</td>
    </tr>
  );
}

// Volle Klassennamen literal je Zweig (statt Template-Interpolation) --
// Tailwinds Content-Scan erkennt nur statische Literale zuverlaessig,
// siehe exakt dasselbe Muster in pages/Beratungsprotokoll.tsx.
function StatusBanner({
  tone,
  title,
  body,
}: {
  tone: 'pending' | 'blocked';
  title: string;
  body: string;
}) {
  if (tone === 'blocked') {
    return (
      <section className="border-l-4 border-status-rot bg-status-rot/10 px-5 py-4" role="status">
        <p className="text-micro uppercase tracking-widest text-status-rot">{title}</p>
        <p className="mt-2 text-caption text-ink-muted">{body}</p>
      </section>
    );
  }
  return (
    <section className="border-l-4 border-status-gelb bg-status-gelb/10 px-5 py-4" role="status">
      <p className="text-micro uppercase tracking-widest text-status-gelb">{title}</p>
      <p className="mt-2 text-caption text-ink-muted">{body}</p>
    </section>
  );
}
