/**
 * Sprint U-16 (2026-06-06): 5eyes-Wordmark als SVG-Komponente.
 *
 * Pure-SVG Editorial-Wordmark — KEINE PNG/Asset-Datei. Damit ist die
 * Skalierung verlustfrei + die Druck-Auflosung perfekt + keine externe
 * Asset-Pflege.
 *
 * Branding-Disziplin:
 *  - Eigene Typografie (Cormorant Garamond + Inter sind aktivierbar via CSS)
 *  - KEINE Drittmarken-Schriften
 *  - 5eyes-Tokens (ink/accent) statt knalliges Blau
 *  - Skalierbar via viewBox + width-Prop
 *
 * Diese Komponente ist als **Platzhalter** gedacht. Sollte der User
 * spaeter ein dediziertes Logo-Asset liefern (SVG mit Pfad-Daten),
 * tauscht man hier nur die Pfade — Komponenten-API bleibt stabil.
 */

export interface LogoProps {
  /** Max-Breite in px. Hoehe skaliert proportional. Default 96. */
  width?: number;
  /** Optionaler aria-label-Override. Default 'Logo 5eyes WealthArchitekten'. */
  ariaLabel?: string;
  /** Optional zusaetzliche className. */
  className?: string;
}

const VIEWBOX_WIDTH = 240;
const VIEWBOX_HEIGHT = 80;

export function Logo({
  width = 96,
  ariaLabel = 'Logo 5eyes WealthArchitekten',
  className = '',
}: LogoProps) {
  const height = Math.round((width * VIEWBOX_HEIGHT) / VIEWBOX_WIDTH);
  return (
    <svg
      role="img"
      aria-label={ariaLabel}
      data-testid="logo-5eyes"
      width={width}
      height={height}
      viewBox={`0 0 ${VIEWBOX_WIDTH} ${VIEWBOX_HEIGHT}`}
      className={className}
      xmlns="http://www.w3.org/2000/svg"
    >
      <title>{ariaLabel}</title>
      {/* "5" — Cormorant Garamond Stil, accent-color (Petrol) */}
      <text
        x="0"
        y="62"
        fontFamily="'Cormorant Garamond', Georgia, serif"
        fontSize="68"
        fontWeight="500"
        fill="currentColor"
      >
        5
      </text>
      {/* "eyes" — Inter Stil, ink-color (Navy) */}
      <text
        x="50"
        y="62"
        fontFamily="'Inter', system-ui, sans-serif"
        fontSize="54"
        fontWeight="400"
        letterSpacing="-0.5"
        fill="currentColor"
      >
        eyes
      </text>
      {/* dezente Akzent-Linie unter dem Wordmark */}
      <line
        x1="0"
        y1="74"
        x2="180"
        y2="74"
        stroke="currentColor"
        strokeOpacity="0.25"
        strokeWidth="1"
      />
    </svg>
  );
}
