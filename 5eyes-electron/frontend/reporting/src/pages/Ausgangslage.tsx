/**
 * U-FE-1: Sektion 4 — Ausgangslage.
 *
 * Editorial 2-Spalten-Layout:
 * - Links: 7 Label-Wert-Paare aus client_info
 * - Rechts: 5 Vermögens-Kategorien aus wealth_summary
 * - Unten: 6 KPI-Karten (Risky-Fraction, Zielerreichung, Vol, Return, MaxDD, VaR 95)
 *
 * Default-Disziplin: 0/None wird als „—" gerendert (z. B. Alter 0).
 */
import type { AusgangslageData } from '@/api/types';
import { ReportPage } from '@/components/ReportPage';
import {
  formatAge,
  formatBpsAsPct,
  formatChfRappen,
  formatHorizon,
} from '@/lib/format';

interface AusgangslageProps {
  data: AusgangslageData;
}

export function Ausgangslage({ data }: AusgangslageProps) {
  const ci = data.client_info;
  const w = data.wealth_summary;
  const m = data.key_metrics;

  const kpis = ([
    ['Risky-Fraction', m.risky_fraction_bps],
    ['Zielerreichung', m.zielerreichung_bps],
    ['Erw. Volatilität', m.exp_vol_bps],
    ['Erw. Rendite', m.exp_return_bps],
    ['Max Drawdown', m.max_drawdown_bps],
    ['VaR 95 %', m.var_95_bps],
  ] as Array<[string, number | null]>).filter(
    (entry): entry is [string, number] => entry[1] != null,
  );

  return (
    <ReportPage
      nr={4}
      kicker="Ausgangslage"
      title="Ausgangslage"
      subtitle="Kundeninformation, Vermögensstruktur und Kennzahlen des Mandats."
    >
      <div className="grid gap-block lg:grid-cols-2">
        <ClientInfoBlock ci={ci} />
        <WealthSummaryBlock w={w} />
      </div>

      {/* PA-04: nur befüllte Kennzahlen rendern. Mehrere Metriken sind backend-
          seitig (noch) null; alle 6 Karten zu zeigen ergab 5x „—" und wirkte
          unfertig. Sind keine Kennzahlen vorhanden, entfällt der ganze Block. */}
      {kpis.length > 0 && (
        <>
          <h2 className="mt-section font-serif text-h2 text-ink">Kennzahlen</h2>
          <div className="mt-3 grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-6">
            {kpis.map(([label, bps]) => (
              <KpiCard key={label} label={label} value={formatBpsAsPct(bps)} />
            ))}
          </div>
        </>
      )}
    </ReportPage>
  );
}

// ---------------------------------------------------------------------------

function ClientInfoBlock({ ci }: { ci: AusgangslageData['client_info'] }) {
  const rows: Array<[string, string]> = [
    ['Alter', formatAge(ci.alter)],
    ['Anlagehorizont', formatHorizon(ci.anlagehorizont_jahre)],
    ['Risikoprofil', ci.risikoprofil || '—'],
    ['Anlageziel', ci.anlageziel || '—'],
    ['Liquiditätsbedarf', formatChfRappen(ci.liquiditaetsbedarf_rappen)],
    ['Steuerdomizil', ci.steuerdomizil || '—'],
    ['Referenzwährung', ci.referenzwaehrung || 'CHF'],
  ];
  return (
    <section className="border border-rule bg-canvas-panel p-5">
      <p className="text-micro uppercase tracking-widest text-ink-subtle">
        Kundeninformation
      </p>
      <dl className="mt-3 space-y-3">
        {rows.map(([label, value]) => (
          <div
            key={label}
            className="grid grid-cols-[minmax(0,1fr)_auto] gap-4 border-b border-rule pb-3 last:border-b-0 last:pb-0"
          >
            <dt className="text-caption text-ink-muted">{label}</dt>
            <dd className="text-right text-caption font-semibold text-ink">
              {value}
            </dd>
          </div>
        ))}
      </dl>
    </section>
  );
}

function WealthSummaryBlock({ w }: { w: AusgangslageData['wealth_summary'] }) {
  const rows: Array<[string, number]> = [
    ['Gesamtvermögen', w.gesamtvermoegen_rappen],
    ['Beratungsvermögen', w.beratungsvermoegen_rappen],
    ['Immobilien', w.immobilien_rappen],
    ['Vorsorge', w.vorsorge_rappen],
    ['Kredite', w.kredite_rappen],
  ];
  return (
    <section className="border border-rule bg-canvas-panel p-5">
      <p className="text-micro uppercase tracking-widest text-ink-subtle">
        Vermögensstruktur
      </p>
      <dl className="mt-3 space-y-3">
        {rows.map(([label, value]) => (
          <div
            key={label}
            className="grid grid-cols-[minmax(0,1fr)_auto] gap-4 border-b border-rule pb-3 last:border-b-0 last:pb-0"
          >
            <dt className="text-caption text-ink-muted">{label}</dt>
            <dd className="text-right font-mono text-caption text-ink">
              {formatChfRappen(value)}
            </dd>
          </div>
        ))}
      </dl>
    </section>
  );
}

interface KpiCardProps {
  label: string;
  value: string;
}

function KpiCard({ label, value }: KpiCardProps) {
  return (
    <div className="border border-rule bg-canvas-subtle p-3">
      <p className="text-micro uppercase tracking-widest text-ink-subtle">
        {label}
      </p>
      <p className="mt-1 font-mono text-body text-ink">{value}</p>
    </div>
  );
}
