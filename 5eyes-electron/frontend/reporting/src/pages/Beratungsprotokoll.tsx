/**
 * U-FINMA-2.3: Sektion 16 — Beratungsprotokoll.
 *
 * Display-only. Editor + Auto-Log-Button kommen in 2.4.
 *
 * Inhalt:
 * - Übersicht-Box (aktive Einträge · letzter Termin · Tage seit)
 * - Mismatch-Banner wenn `has_active_mismatches`
 * - Retention-Warnung wenn `!retention_audit_ok`
 * - Letzter-Eintrag-Block (Typ, Datum, Channel, Topics, Risk-Warnings,
 *   Status-Pill, Integritäts-Marker)
 * - Fallback wenn kein Eintrag erfasst
 */
import type { BeratungsprotokollData, BeratungsprotokollEntry } from '@/api/types';
import { ReportPage } from '@/components/ReportPage';

interface BeratungsprotokollProps {
  data: BeratungsprotokollData;
}

export function Beratungsprotokoll({ data }: BeratungsprotokollProps) {
  return (
    <ReportPage
      nr={16}
      kicker="Beratungsprotokoll"
      title="Beratungsprotokoll"
      subtitle="FIDLEG-konforme Dokumentation der Beratungsgespräche, Themen und Risikohinweise."
    >
      <SummaryBox data={data} />

      {data.has_active_mismatches && data.suitability_mismatches.length > 0 ? (
        <MismatchBanner mismatches={data.suitability_mismatches} />
      ) : null}

      {!data.retention_audit_ok ? <RetentionWarning /> : null}

      {data.latest_entry ? (
        <LatestEntry entry={data.latest_entry} />
      ) : (
        <NoEntryHint />
      )}
    </ReportPage>
  );
}

// ---------------------------------------------------------------------------

function SummaryBox({ data }: { data: BeratungsprotokollData }) {
  const daysText =
    data.days_since_last_review === null || data.days_since_last_review === undefined
      ? '—'
      : data.days_since_last_review === 0
      ? 'heute'
      : `vor ${data.days_since_last_review} Tagen`;

  return (
    <section className="grid grid-cols-1 gap-block border-l-4 border-accent bg-canvas-subtle p-6 md:grid-cols-3">
      <SummaryCell label="Aktive Einträge" value={String(data.total_active)} />
      <SummaryCell label="Letzter Termin" value={data.last_review_date || '—'} />
      <SummaryCell label="Letzte Beratung" value={daysText} />
    </section>
  );
}

function SummaryCell({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-micro uppercase tracking-widest text-ink-subtle">
        {label}
      </p>
      <p className="mt-2 font-serif text-h2 text-ink">{value}</p>
    </div>
  );
}

function MismatchBanner({ mismatches }: { mismatches: string[] }) {
  return (
    <section className="mt-section border-l-4 border-status-rot bg-status-rot/10 px-5 py-4">
      <p className="text-micro uppercase tracking-widest text-status-rot">
        Aktive Suitability-Hinweise
      </p>
      <ul className="mt-3 space-y-2 text-caption text-ink">
        {mismatches.map((m, idx) => (
          <li key={idx} className="flex gap-2">
            <span aria-hidden="true" className="select-none text-status-rot">
              •
            </span>
            <span>{m}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}

function RetentionWarning() {
  return (
    <section className="mt-section border-l-4 border-status-gelb bg-status-gelb/10 px-5 py-4">
      <p className="text-micro uppercase tracking-widest text-status-gelb">
        Aufbewahrungs-Hinweis
      </p>
      <p className="mt-2 text-caption text-ink-muted">
        Mindestens ein Beratungsprotokoll-Eintrag läuft in den nächsten
        30 Tagen ab. FIDLEG verlangt eine 10-Jahres-Aufbewahrung — bitte
        Archiv-Pflicht überprüfen.
      </p>
    </section>
  );
}

const STATUS_PALETTE: Record<string, { label: string; bg: string; text: string }> = {
  Empfohlen:           { label: 'Empfohlen',     bg: 'bg-status-neutral/15', text: 'text-status-neutral' },
  Beschlossen:         { label: 'Beschlossen',   bg: 'bg-status-gruen/15',   text: 'text-status-gruen' },
  Umgesetzt:           { label: 'Umgesetzt',     bg: 'bg-gold-subtle/40',    text: 'text-gold' },
  'Überarbeitung nötig':{ label: 'Überarbeitung', bg: 'bg-status-gelb/15',    text: 'text-status-gelb' },
  Abgelehnt:           { label: 'Abgelehnt',     bg: 'bg-status-rot/15',     text: 'text-status-rot' },
};

function StatusPill({ status }: { status: string }) {
  const p = STATUS_PALETTE[status] ?? {
    label: status || 'Unbekannt',
    bg: 'bg-status-neutral/15',
    text: 'text-status-neutral',
  };
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-micro font-semibold uppercase tracking-widest ${p.bg} ${p.text}`}
    >
      {p.label}
    </span>
  );
}

function LatestEntry({ entry }: { entry: BeratungsprotokollEntry }) {
  const datetime = formatSwissDateTime(entry.entry_datetime);
  const duration =
    entry.duration_minutes !== null && entry.duration_minutes !== undefined
      ? `${entry.duration_minutes} min`
      : '—';
  const channel = entry.communication_channel
    ? entry.communication_channel.charAt(0).toUpperCase() + entry.communication_channel.slice(1)
    : '—';
  const hashShort = entry.integrity_hash ? entry.integrity_hash.slice(0, 16) : '';

  return (
    <section className="mt-section border border-rule">
      <header className="flex flex-wrap items-start justify-between gap-3 border-b border-rule px-5 py-4">
        <div>
          <h2 className="font-serif text-h3 text-ink">{entry.title || '—'}</h2>
          <p className="mt-1 text-caption text-ink-muted">
            {entry.entry_type} · {datetime} · {channel} · {duration} · Version {entry.version}
          </p>
        </div>
        <StatusPill status={entry.status} />
      </header>

      {entry.description ? (
        <p className="border-b border-rule px-5 py-4 text-body text-ink">
          {entry.description}
        </p>
      ) : null}

      <dl className="grid gap-3 bg-canvas-subtle px-5 py-4 md:grid-cols-[10rem_minmax(0,1fr)]">
        {entry.topics.length > 0 ? (
          <>
            <dt className="text-micro uppercase tracking-widest text-ink-subtle">Themen</dt>
            <dd className="text-caption text-ink">{entry.topics.join(' · ')}</dd>
          </>
        ) : null}

        {entry.risk_warnings_given.length > 0 ? (
          <>
            <dt className="text-micro uppercase tracking-widest text-ink-subtle">Risiko-Hinweise</dt>
            <dd className="text-caption text-ink">
              <ul className="space-y-1">
                {entry.risk_warnings_given.map((w, idx) => (
                  <li key={idx} className="flex gap-2">
                    <span aria-hidden="true" className="select-none text-ink-subtle">
                      •
                    </span>
                    <span>{w}</span>
                  </li>
                ))}
              </ul>
            </dd>
          </>
        ) : null}

        {hashShort ? (
          <>
            <dt className="text-micro uppercase tracking-widest text-ink-subtle">Integrität</dt>
            <dd className="text-caption text-ink-muted">
              <span className="font-mono">{hashShort}…</span>{' '}
              <span className="font-semibold text-status-gruen">verifiziert</span>
            </dd>
          </>
        ) : null}
      </dl>
    </section>
  );
}

function NoEntryHint() {
  return (
    <section className="mt-section border border-rule bg-canvas-subtle px-6 py-5 text-caption italic text-ink-subtle">
      Noch kein Beratungsprotokoll für dieses Mandat erfasst. Bitte beim
      nächsten Termin einen FIDLEG-konformen Eintrag anlegen.
    </section>
  );
}

function formatSwissDateTime(iso: string | null): string {
  if (!iso) return '—';
  // ISO „2026-05-15T14:00:00.000Z" → „15.05.2026 14:00"
  try {
    const m = iso.match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/);
    if (!m) return iso;
    const [, y, mo, d, hh, mm] = m;
    return `${d}.${mo}.${y} ${hh}:${mm}`;
  } catch {
    return iso;
  }
}
