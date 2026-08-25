import type { Config } from 'tailwindcss';

/**
 * Tailwind-Konfiguration mit Design-Tokens der 5eyes Reporting-Sub-App.
 *
 * Designstil (per Spec):
 *  - Swiss Private Banking, institutionell, minimalistisch
 *  - viel Weissraum, editoriales Layout, präzise Typografie
 *  - Offwhite Hintergrund, sehr dunkles Navy, dezentes Petrol
 *  - matte Gold-Akzente optional
 *  - KEIN knalliges Blau, KEIN Fintech-Look
 *
 * Branding-Disziplin: alle Tokens sind 5eyes-eigen, KEINE Dritt-Marken-
 * Farben oder -Schriften (Memory-Regel).
 */
const config: Config = {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  // Sprint U-50 (2026-06-06): Dark-Mode via class-Strategy.
  // ThemeProvider toggled `.dark` Klasse auf <html>.
  // Editorial-Stil bleibt — Dark-Mode ist eine RUHIGE Variante,
  // kein knalliger Modus.
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        // Hintergrund — sehr ruhig, nie pures Weiss
        canvas: {
          DEFAULT: '#FAFAF6', // Offwhite — Cover/Body
          subtle:  '#F4F3EE', // Section-Background dezenter
          panel:   '#FFFFFF', // Karten/Charts auf Canvas
        },
        // Tiefes Navy — Headlines & Text
        ink: {
          DEFAULT: '#0F1C2E', // Sehr dunkles Navy — Body-Text
          muted:   '#3B475A', // Sekundärtext
          subtle:  '#6F7A8A', // Hilfslabels
        },
        // Petrol/Teal — Akzent für Headers, KPI-Pulls
        accent: {
          DEFAULT: '#2C5F5F', // Tiefes Petrol
          subtle:  '#7FA5A5', // Hover/Background-Versionen
        },
        // Linien & Trennelemente
        rule: {
          DEFAULT: '#E5E4DE',
          strong:  '#C8C6BD',
        },
        // Gold-Akzent — sehr sparsam (z.B. Verdict-GREEN-Pill)
        gold: {
          DEFAULT: '#B39455',
          subtle:  '#D9C79A',
        },
        // Status-Farben für Ampeln (matt, NICHT signal-grün/-rot)
        status: {
          gruen: '#4E6F58',
          gelb:  '#B59243',
          rot:   '#9E4747',
          neutral: '#7A8395',
        },
      },
      fontFamily: {
        // Serif für Headlines — institutionell, ruhig
        serif: [
          'Cormorant Garamond',
          'Source Serif Pro',
          'Georgia',
          'serif',
        ],
        // Sans für Body & UI — moderne, klare Lesbarkeit
        sans: [
          'Inter',
          'Source Sans Pro',
          '-apple-system',
          'BlinkMacSystemFont',
          'Segoe UI',
          'sans-serif',
        ],
        // Tabular Numbers für Tabellen + KPI-Karten
        mono: [
          'JetBrains Mono',
          'Source Code Pro',
          'Consolas',
          'monospace',
        ],
      },
      fontSize: {
        // Editoriale Hierarchie — wenige, klare Stufen
        'display': ['3.5rem', { lineHeight: '1.05', letterSpacing: '-0.02em' }],
        'h1':      ['2.25rem', { lineHeight: '1.15', letterSpacing: '-0.015em' }],
        'h2':      ['1.5rem',  { lineHeight: '1.25' }],
        'h3':      ['1.125rem',{ lineHeight: '1.35' }],
        'body':    ['0.9375rem',{ lineHeight: '1.55' }],
        'caption': ['0.8125rem',{ lineHeight: '1.4', letterSpacing: '0.01em' }],
        'micro':   ['0.6875rem',{ lineHeight: '1.3', letterSpacing: '0.04em' }],
      },
      spacing: {
        // Viel Whitespace — institutionelle Ruhe
        'page-x': '4rem',
        'page-y': '5rem',
        'section': '4rem',
        'block':   '2rem',
      },
      maxWidth: {
        'editorial': '64rem', // Print-äquivalentes Layout
      },
      borderRadius: {
        // Sparsam, nie zu rund — keine Fintech-Pills
        'card': '4px',
        'pill': '999px',
      },
      transitionDuration: {
        'soft': '400ms',
      },
      transitionTimingFunction: {
        'editorial': 'cubic-bezier(0.25, 0.1, 0.25, 1)',
      },
    },
  },
  plugins: [],
};

export default config;
