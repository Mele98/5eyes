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

/** Chart-Palette: matte, nicht-konkurrierende Farben für Bar/Line-Charts. */
export const chartPalette = {
  primary:   colors.accent.DEFAULT,
  secondary: colors.gold.DEFAULT,
  neutral:   colors.ink.muted,
  ist:       colors.ink.DEFAULT,
  soll:      colors.accent.DEFAULT,
  drift:     colors.gold.DEFAULT,
  grid:      colors.rule.DEFAULT,
  axisLabel: colors.ink.subtle,
} as const;
