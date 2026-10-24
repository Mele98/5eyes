/**
 * U-FE-1: Gemeinsamer Article-Wrapper für die Sektionen 2-14.
 *
 * Stellt sicher dass alle Sektionen das gleiche Editorial-Layout haben:
 * - Kicker („Sektion N · …") oben in Micro-Caps
 * - Display-Titel (Serif, ink)
 * - Optionaler Subtitle (Serif italic, muted)
 * - Trennlinie
 * - Inhalt
 * - Optional `toolbar`-Slot oben rechts (für EditButton aus PR C)
 */
import type { ReactNode } from 'react';

export interface ReportPageProps {
  nr: number;
  kicker: string;
  title: string;
  subtitle?: string;
  children: ReactNode;
  /** Rechts-oben-Slot für Berater-Aktionen (z. B. EditButton).
      `print:hidden` — landet nicht im PDF/Druck. */
  toolbar?: ReactNode;
}

export function ReportPage({
  nr,
  kicker,
  title,
  subtitle,
  children,
  toolbar,
}: ReportPageProps) {
  return (
    <article className="relative mx-auto min-h-screen max-w-editorial px-page-x py-page-y print:min-h-0">
      {toolbar ? <div className="no-print print:hidden">{toolbar}</div> : null}
      <p className="text-micro uppercase tracking-widest text-ink-subtle">
        Sektion {nr} · {kicker}
      </p>
      <header className="mt-block border-b border-rule pb-block">
        <h1 className="font-serif text-h1 text-ink">{title}</h1>
        {subtitle ? (
          <p className="mt-3 max-w-3xl font-serif text-h3 italic text-ink-muted">
            {subtitle}
          </p>
        ) : null}
      </header>
      <div className="mt-section">{children}</div>
    </article>
  );
}

/**
 * Editorial-Note: kleine Box mit Akzent-Linie links — für Berater-Anmerkungen.
 * Auto-Default-Text wird gedimmt-kursiv gerendert.
 */
export interface EditorialNoteProps {
  title: string;
  body: string;
}

export function EditorialNote({ title, body }: EditorialNoteProps) {
  return (
    <aside className="border-l-4 border-accent bg-canvas-subtle px-5 py-4">
      <p className="text-micro uppercase tracking-widest text-ink-subtle">
        {title}
      </p>
      <p className="mt-3 text-body text-ink-muted">
        {body || 'Keine Anmerkung erfasst.'}
      </p>
    </aside>
  );
}
