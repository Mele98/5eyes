/**
 * U-FINMA-3 (Roadmap-Punkt 3): Sektion 17 — Eignungspruefung.
 *
 * Macht den juengsten SuitabilityCheck im Advisory-Report sichtbar:
 * - Status-Pill (passed/mismatch/incomplete)
 * - Geprueft von + Pflichttyp + Zeitpunkt
 * - Beurteilung (result_notes)
 * - Fehlende Informationen (wenn Pruefung incomplete)
 * - FIDLEG-Art-12-Workflow (Warnung/Bestaetigung) wenn Kunde trotz
 *   Mismatch fortgesetzt hat
 * - Referenzen-Tabelle (Risikoprofil, AdvisoryLog, RecommendationRun, etc.)
 *
 * Display-only: Die Eignungspruefung wird in der Hauptapp 5eyes_v2.html
 * erfasst, nicht hier.
 */
import type { SuitabilitySummaryData } from '@/api/types';
import { ReportPage } from '@/components/ReportPage';

interface EignungProps {
  data: SuitabilitySummaryData;
}

const RESULT_PILL: Record<
  string,
  { label: string; fg: string; bg: string }
> = {
  passed: {
    label: 'Eignung gegeben',
    fg: 'text-status-gruen',
    bg: 'bg-status-gruen/10',
  },
  mismatch: {
    label: 'Mismatch dokumentiert',
    fg: 'text-status-rot',
    bg: 'bg-status-rot/10',
  },
  incomplete: {
    label: 'Pruefung unvollstaendig',
    fg: 'text-status-gelb',
    bg: 'bg-status-gelb/10',
  },
};

const DUTY_LABEL: Record<string, string> = {
  suitability: 'Eignungspruefung (Suitability)',
  appropriateness: 'Angemessenheitspruefung (Appropriateness)',
  informational: 'Informationspruefung',
  execution_only: 'Execution-only',
};

export function Eignung({ data }: EignungProps) {
  return (
    <ReportPage
      nr={17}
      kicker="Eignungspruefung"
      title="Eignungspruefung"
      subtitle="FINMA-/FIDLEG-konforme Pruefung der Anlagestrategie gegen Risikoprofil, Kenntnisse und Erfahrung."
    >
      {!data.has_check ? (
        <EmptyState />
      ) : (
        <>
          <SummaryBox data={data} />
          {data.result_notes ? <Notes notes={data.result_notes} /> : null}
          {data.missing_information.length > 0 ? (
            <MissingInfoBlock items={data.missing_information} />
          ) : null}
          {data.client_proceeded_despite ? (
            <OverrideWorkflowBlock data={data} />
          ) : null}
          <ReferencesTable data={data} />
        </>
      )}
    </ReportPage>
  );
}

// ---------------------------------------------------------------------------

function SummaryBox({ data }: { data: SuitabilitySummaryData }) {
  const pill =
    RESULT_PILL[data.result ?? ''] ?? {
      label: 'Status unklar',
      fg: 'text-status-neutral',
      bg: 'bg-canvas-subtle',
    };
  const dutyLabel = data.duty_type ? DUTY_LABEL[data.duty_type] ?? data.duty_type : '—';
  return (
    <section
      data-testid="suitability-summary-box"
      className="grid grid-cols-1 gap-block border-l-4 border-accent bg-canvas-subtle p-6 md:grid-cols-3"
    >
      <div>
        <p className="text-micro uppercase tracking-widest text-ink-subtle">
          Ergebnis
        </p>
        <span
          className={`mt-2 inline-block rounded-card px-3 py-1 text-caption font-semibold uppercase tracking-wide ${pill.fg} ${pill.bg}`}
        >
          {pill.label}
        </span>
      </div>
      <div>
        <p className="text-micro uppercase tracking-widest text-ink-subtle">
          Geprueft von
        </p>
        <p className="mt-2 font-serif text-h3 text-ink">
          {data.checked_by_name || '—'}
        </p>
      </div>
      <div>
        <p className="text-micro uppercase tracking-widest text-ink-subtle">
          Pflichttyp / Zeitpunkt
        </p>
        <p className="mt-2 font-serif text-h3 text-ink">{dutyLabel}</p>
        <p className="mt-1 text-caption text-ink-muted">
          {formatTimestamp(data.performed_at)}
        </p>
      </div>
    </section>
  );
}

function Notes({ notes }: { notes: string }) {
  return (
    <section className="mt-section">
      <h2 className="font-serif text-h2 text-ink">Beurteilung</h2>
      <p className="mt-3 text-body text-ink-muted">{notes}</p>
    </section>
  );
}

function MissingInfoBlock({ items }: { items: string[] }) {
  return (
    <section
      data-testid="suitability-missing-info"
      className="mt-section border-l-4 border-status-gelb bg-status-gelb/10 px-5 py-4"
    >
      <p className="text-micro uppercase tracking-widest text-status-gelb">
        Fehlende Informationen zum Zeitpunkt der Pruefung
      </p>
      <ul className="mt-3 space-y-2 text-caption text-ink">
        {items.map((item, idx) => (
          <li key={idx} className="flex gap-2">
            <span aria-hidden="true" className="select-none text-status-gelb">
              •
            </span>
            <span>{item}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}

function OverrideWorkflowBlock({ data }: { data: SuitabilitySummaryData }) {
  const warningLine = data.warning_delivered
    ? `Warnung ausgehaendigt am ${formatTimestamp(data.warning_delivered_at)}`
    : 'Warnung NICHT dokumentiert ausgehaendigt';
  const ackLine = data.client_acknowledged
    ? `Kunde hat Hinweis bestaetigt am ${formatTimestamp(data.client_acknowledged_at)}`
    : 'Kundenbestaetigung NICHT dokumentiert';
  return (
    <section
      data-testid="suitability-override-workflow"
      className="mt-section border-l-4 border-status-rot bg-status-rot/10 px-5 py-4"
    >
      <p className="text-micro uppercase tracking-widest text-status-rot">
        Kunde fuhrt trotz Mismatch fort (FIDLEG Art. 12)
      </p>
      <ul className="mt-3 space-y-2 text-caption text-ink">
        <li className="flex gap-2">
          <span aria-hidden="true" className="select-none text-status-rot">
            •
          </span>
          <span>{warningLine}</span>
        </li>
        <li className="flex gap-2">
          <span aria-hidden="true" className="select-none text-status-rot">
            •
          </span>
          <span>{ackLine}</span>
        </li>
      </ul>
    </section>
  );
}

function ReferencesTable({ data }: { data: SuitabilitySummaryData }) {
  const refs = data.references;
  const rows: Array<{ label: string; value: string }> = [];
  if (refs.risk_assessment_id) {
    rows.push({ label: 'Risikoprofil-Assessment', value: refs.risk_assessment_id });
  }
  if (refs.knowledge_assessment_id) {
    rows.push({
      label: 'Kenntnisse-Assessment',
      value: refs.knowledge_assessment_id,
    });
  }
  if (refs.advisory_log_id) {
    rows.push({
      label: 'Beratungsprotokoll-Eintrag',
      value: data.linked_log_present
        ? refs.advisory_log_id
        : `${refs.advisory_log_id} (nicht gefunden)`,
    });
  }
  if (refs.recommendation_run_id) {
    rows.push({ label: 'Empfehlungs-Run', value: refs.recommendation_run_id });
  }
  if (refs.document_id) {
    rows.push({ label: 'Beleg-Dokument', value: refs.document_id });
  }
  if (rows.length === 0) {
    return null;
  }
  return (
    <section className="mt-section">
      <h2 className="font-serif text-h2 text-ink">Verknuepfte Datensaetze</h2>
      <table
        data-testid="suitability-references"
        className="mt-3 w-full text-caption"
      >
        <thead>
          <tr className="border-b border-rule">
            <th className="pb-2 pr-4 text-left font-medium uppercase tracking-widest text-micro text-ink-subtle">
              Datensatz
            </th>
            <th className="pb-2 text-left font-medium uppercase tracking-widest text-micro text-ink-subtle">
              Referenz
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row, idx) => (
            <tr key={idx} className="border-b border-rule last:border-b-0">
              <td className="py-2 pr-4 text-ink">{row.label}</td>
              <td className="py-2 font-mono text-ink-muted">{row.value}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

function EmptyState() {
  return (
    <section
      data-testid="suitability-empty-state"
      className="border-l-4 border-status-neutral bg-canvas-subtle px-5 py-4"
    >
      <p className="font-serif text-h3 text-ink">
        Noch keine Eignungspruefung dokumentiert
      </p>
      <p className="mt-2 text-body text-ink-muted">
        Vor der Umsetzung der Anlagestrategie ist eine FINMA-konforme
        Eignungspruefung (Suitability nach FIDLEG) durchzufuehren und im
        System zu hinterlegen. Sie erscheint danach an dieser Stelle.
      </p>
    </section>
  );
}

function formatTimestamp(iso: string | null): string {
  if (!iso) return '—';
  // Akzeptiert "2026-05-22T14:30:00Z" oder "2026-05-22T14:30:00.000Z"
  const m = iso.match(/^(\d{4})-(\d{2})-(\d{2})/);
  if (!m) return iso;
  return `${m[3]}.${m[2]}.${m[1]}`;
}
