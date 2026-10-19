/**
 * 5eyes Reporting Design-Tokens (Sprint U-P22.1).
 *
 * Diese Konstanten spiegeln die Tailwind-Theme-Werte als JS-importierbare
 * Werte. Wird von Chart-Komponenten (Recharts) gebraucht, die Inline-Styles
 * statt Utility-Classes benötigen.
 *
 * Branding-Disziplin: alle Tokens sind 5eyes-eigen, KEINE Dritt-Marken-
 * Farben (per Memory-Regel).
 *
 * Quelle der Wahrheit ist `tailwind.config.ts` — beide müssen synchron
 * bleiben. Bei Drift: tokens.ts aktualisieren.
 */

export const colors = {
  canvas: {
    DEFAULT: '#FAFAF6',
    subtle:  '#F4F3EE',
    panel:   '#FFFFFF',
  },
  ink: {
    DEFAULT: '#0F1C2E',
    muted:   '#3B475A',
    subtle:  '#6F7A8A',
  },
  accent: {
    DEFAULT: '#2C5F5F',
    subtle:  '#7FA5A5',
  },
  rule: {
    DEFAULT: '#E5E4DE',
    strong:  '#C8C6BD',
  },
  gold: {
    DEFAULT: '#B39455',
    subtle:  '#D9C79A',
  },
  status: {
    gruen:   '#4E6F58',
    gelb:    '#B59243',
    rot:     '#9E4747',
    neutral: '#7A8395',
  },
} as const;

export const typography = {
  serif: 'Cormorant Garamond, Source Serif Pro, Georgia, serif',
  sans:  'Inter, Source Sans Pro, -apple-system, BlinkMacSystemFont, sans-serif',
  mono:  'JetBrains Mono, Source Code Pro, Consolas, monospace',
} as const;

/**
 * AA-UX-COLORS-001: Anlageklassen-Farben -- identisch mit den CSS-Tokens
 * `--ac-*` der App (5eyes_v2.html, :root bzw. [data-theme=dark]); Gleichlauf
 * prüft 5eyes-backend/tests/test_monolith_asset_class_colors.py.
 * Helligkeitsstufen statt Blau-Varianten, damit die Klassen auch bei
 * Rot-Grün-Schwäche unterscheidbar bleiben. KEIN Grün (Grün = „besser als IST").
 */
export const assetClass = {
  eq:  '#1F3A5F', // Aktien – Navy
  bd:  '#B39455', // Obligationen – Gold
  re:  '#7A4A2E', // Immobilien – Terrakotta (dunkler als #8A5A3C: Protanopie-Abstand zu Oliv)
  alt: '#5E6B45', // Alternative (inkl. Gold/PE) – Oliv
  liq: '#8E97A8', // Liquidität – Grau
  oth: '#6B4E71', // Übrige/nicht zugeordnet – Aubergine
} as const;

/** Dark-Variante: HSL-Helligkeit +18 Punkte (Aktien +20 für 3:1 auf dunkler Fläche). */
export const assetClassDark = {
  eq:  '#3D6DB0',
  bd:  '#CFBC94',
  re:  '#BA7349',
  alt: '#8EA06C',
  liq: '#C2C7D0',
  oth: '#9B79A2',
} as const;

export type AssetClassKey = keyof typeof assetClass;

/**
 * Engine-Key / Anzeigename -> Token-Schlüssel. Gleiche Regeln wie
 * `assetClassKey()` im Monolith (Private Equity VOR „equit").
 */
export function assetClassKey(label: string | null | undefined): AssetClassKey {
  const k = String(label ?? '').toLowerCase();
  if (k === 'eq' || k === 'bd' || k === 're' || k === 'alt' || k === 'liq' || k === 'oth') return k;
  if (k.includes('private equity') || k.includes('private_equity')) return 'alt';
  if (k.includes('aktie') || k.includes('equit')) return 'eq';
  if (k.includes('oblig') || k.includes('anleihe') || k.includes('bond')) return 'bd';
  if (k.includes('immob') || k.includes('real_estate') || k.includes('realestate')) return 're';
  if (k.includes('liquid') || k.includes('cash')) return 'liq';
  if (k.includes('altern') || k.includes('gold') || k.includes('edelmetall')) return 'alt';
  return 'oth';
}

/** SOLL-Strategie = Brand-Akzent Gold (Text-tauglich: 5.0:1 auf Weiss). */
export const soll = {
  DEFAULT: '#8A6A1F',
  dark:    '#D9B869',
} as const;

/** Chart-Palette: matte, nicht-konkurrierende Farben für Bar/Line-Charts. */
export const chartPalette = {
  primary:   colors.accent.DEFAULT,
  secondary: colors.gold.DEFAULT,
  neutral:   colors.ink.muted,
  ist:       colors.ink.DEFAULT,
  soll:      soll.DEFAULT,
  drift:     colors.gold.DEFAULT,
  grid:      colors.rule.DEFAULT,
  axisLabel: colors.ink.subtle,
} as const;
