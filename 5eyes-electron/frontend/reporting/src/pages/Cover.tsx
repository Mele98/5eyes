/**
 * Cover-Seite (Sektion 1) des Advisory-Reports.
 *
 * Design-Disziplin (per Berater-Spec):
 *   - Minimalistisch, keine Stockbilder, keine Menschen, keine Skyline
 *   - Logo oben links, Titel zentriert/links als Editorial-Display
 *   - Subtiler Datums-/Kunde-/Berater-Block am unteren Drittel
 *   - Optional sehr dezente Hintergrund-Struktur
 *
 * Branding-Disziplin: keine Dritt-Marken, keine Salesbilder.
 *
 * Print-ready: identische Darstellung wie Bildschirm (siehe globals.css).
 */
import { motion } from 'framer-motion';
import type { CoverData } from '@/api/types';

interface CoverProps {
  data: CoverData;
}

export function Cover({ data }: CoverProps) {
  return (
    <article
      data-testid="report-page-cover"
      className="
        relative
        min-h-screen
        mx-auto
        max-w-editorial
        flex flex-col
        px-page-x py-page-y
      "
    >
      {/* Logo-Slot oben links — sparsam, nur Text-Wordmark.
          Tatsächliches Logo-Asset wird in U-P22.4 (Electron-Integration)
          eingebunden, heute nur typografische Wordmark als Platzhalter. */}
      <header className="flex items-center justify-between">
        <span className="font-serif text-h3 tracking-tight text-ink">
          5eyes
        </span>
        <span className="text-micro uppercase tracking-widest text-ink-subtle">
          Wealth Architects
        </span>
      </header>

      {/* Hauptblock — Titel + Subtitel, viel Whitespace.
          Editorial-Animation: weicher Fade-in beim Druck nicht sichtbar. */}
      <motion.section
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.6, ease: 'easeOut' }}
        className="flex-1 flex flex-col justify-center"
      >
        <p className="text-micro uppercase tracking-widest text-accent">
          Vertraulich · Persönlich
        </p>
        <h1
          data-testid="cover-title"
          className="mt-block font-serif text-display text-ink leading-tight"
        >
          {data.title}
        </h1>
        <p className="mt-4 font-serif text-h1 text-ink-muted italic">
          {data.subtitle}
        </p>
      </motion.section>

      {/* Datenblock am unteren Drittel — Kunde / Mandat / Datum / Berater */}
      <footer className="border-t border-rule pt-block">
        <dl className="grid grid-cols-2 gap-x-block gap-y-6 text-caption">
          <div>
            <dt className="text-micro uppercase tracking-wider text-ink-subtle">
              Kundin / Kunde
            </dt>
            <dd
              data-testid="cover-client-name"
              className="mt-2 font-serif text-h3 text-ink"
            >
              {data.client_name}
            </dd>
          </div>
          <div>
            <dt className="text-micro uppercase tracking-wider text-ink-subtle">
              Mandat-Nr.
            </dt>
            <dd className="mt-2 font-mono text-body text-ink">
              {data.mandate_number || '—'}
            </dd>
          </div>
          <div>
            <dt className="text-micro uppercase tracking-wider text-ink-subtle">
              Berater / Beraterin
            </dt>
            <dd
              data-testid="cover-advisor-name"
              className="mt-2 font-serif text-h3 text-ink"
            >
              {data.advisor_name}
            </dd>
          </div>
          <div>
            <dt className="text-micro uppercase tracking-wider text-ink-subtle">
              Berichtsdatum
            </dt>
            <dd
              data-testid="cover-report-date"
              className="mt-2 font-mono text-body text-ink"
            >
              {formatReportDate(data.report_date)}
            </dd>
          </div>
        </dl>
      </footer>
    </article>
  );
}

/**
 * Wandelt ISO-Datum (YYYY-MM-DD) in Schweizer Format (DD.MM.YYYY) um.
 * Bei ungültigem Input: liefert den Roh-String zurück, damit kein Crash
 * den Report blockiert.
 */
export function formatReportDate(iso: string): string {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(iso)) return iso || '—';
  const [year, month, day] = iso.split('-');
  return `${day}.${month}.${year}`;
}
