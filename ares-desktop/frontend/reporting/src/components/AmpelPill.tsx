/**
 * U-FE-2: Ampel-Pill für Status-Anzeigen.
 *
 * Mapping: backend liefert `bewertung ∈ {gruen, gelb, rot, nicht_beurteilbar}`,
 * die Pill rendert das mit mattem 5eyes-Status-Farbtoken (NICHT signal-grün/-rot).
 *
 * Wiederverwendbar in Sektion 7 (Erkenntnisse) und Sektion 11 (Goal-Status).
 */
import type { AmpelStatus } from '@/api/types';

const PALETTE: Record<
  AmpelStatus | 'unknown',
  { label: string; bg: string; text: string }
> = {
  gruen:             { label: 'OK',       bg: 'bg-status-gruen/15',   text: 'text-status-gruen' },
  gelb:              { label: 'Achtung',  bg: 'bg-status-gelb/15',    text: 'text-status-gelb' },
  rot:               { label: 'Handeln',  bg: 'bg-status-rot/15',     text: 'text-status-rot' },
  nicht_beurteilbar: { label: 'Pendent',  bg: 'bg-status-neutral/15', text: 'text-status-neutral' },
  unknown:           { label: 'Pendent',  bg: 'bg-status-neutral/15', text: 'text-status-neutral' },
};

export interface AmpelPillProps {
  status: AmpelStatus | string;
  /** Override-Label, z. B. „Erreichbar" für Goal-Status statt „OK". */
  label?: string;
  /** Optional kleinere Größe für inline-Verwendung. */
  size?: 'sm' | 'md';
}

// Sprint U-90 (2026-06-06): a11y-Mapping fuer Screen-Reader-Verbalisierung
// pro Ampel-Status. Wichtig: visuelle Farbe darf nicht der einzige
// Informationstraeger sein (WCAG 1.4.1 'Use of Color').
const ARIA_STATUS_DESCRIPTION: Record<keyof typeof PALETTE, string> = {
  gruen: 'Status gruen: keine Massnahme erforderlich',
  gelb: 'Status gelb: Achtung, Pruefung empfohlen',
  rot: 'Status rot: Handlungsbedarf',
  nicht_beurteilbar: 'Status nicht beurteilbar: Daten unvollstaendig',
  unknown: 'Status unbekannt',
};

export function AmpelPill({ status, label, size = 'sm' }: AmpelPillProps) {
  const key = (status in PALETTE ? status : 'unknown') as keyof typeof PALETTE;
  const palette = PALETTE[key];
  const padding = size === 'md' ? 'px-3 py-1' : 'px-2 py-0.5';
  return (
    <span
      role="status"
      aria-label={ARIA_STATUS_DESCRIPTION[key]}
      className={[
        'inline-flex items-center gap-1.5 rounded-full font-semibold uppercase tracking-widest',
        size === 'md' ? 'text-caption' : 'text-micro',
        padding,
        palette.bg,
        palette.text,
      ].join(' ')}
    >
      {label ?? palette.label}
    </span>
  );
}
