# Storybook fuer 5eyes Reporting Sub-App

Wegweiser fuer das Storybook-Setup als visuelles Test- + Doku-Tool
fuer die Editorial-Design-Tokens und Sub-App-Komponenten.

**Stand:** 2026-06-06
**Roadmap-Punkt:** #86 (FE/DOC, opt-in)
**Komplementaer zu:** [MUTATION_TESTING.md](MUTATION_TESTING.md) (U-106)
+ [PROPERTY_BASED_TESTING.md](PROPERTY_BASED_TESTING.md) (U-107)

---

## Was ist Storybook?

Storybook ist ein interaktiver Component-Catalog. Pro Komponente
schreibst du *Stories* (Beispiele in verschiedenen Zustaenden), die
isoliert vom App-Routing rendern. Vorteile fuer 5eyes:

- **Editorial-Design-Disziplin:** Cormorant+Inter-Tokens lassen sich
  in einer Story-Galerie pruefen (Spacing, Hierarchie, Farben).
- **Komponenten-Doku** fuer Berater, die wissen wollen wie eine
  AmpelPill in `gruen|gelb|rot|nicht_beurteilbar` aussieht.
- **a11y-Audit** (axe-storybook-addon) pro Story als CI-Step.

## Setup

Opt-in (wie U-106/U-107): KEINE neue Dep in `package.json` — Berater
installieren bei Bedarf:

```powershell
cd 5eyes-electron\frontend\reporting
npx storybook@latest init --type vite
npm run storybook
```

Storybook erkennt Vite + TypeScript + Tailwind automatisch. Erst-Setup
generiert `.storybook/` Config-Folder + Stub-Stories unter
`src/stories/`.

## Branding-Disziplin

- KEINE Drittmarken in Beispiel-Daten (siehe
  [GLOSSAR.md](GLOSSAR.md#begriffe-die-nicht-auftauchen-duerfen))
- KEINE Garantie-Sprache in Story-Texten
- Editorial-Stil-Tokens aus `tailwind.config.ts` referenzieren

## Empfohlene erste Stories

| Komponente | Sprint | Pflicht-Varianten |
|------------|--------|-------------------|
| `AmpelPill` | U-FE-2 | gruen / gelb / rot / nicht_beurteilbar / unknown |
| `Sidebar` | U-P23 | 17 Sektionen, mobile-collapsed + Desktop |
| `ThemeToggle` | U-50 | light + dark |
| `ErrorBoundary` | U-87 | Default-Fallback + Custom-Fallback |
| `BarChartIstSoll` | U-FE-1 | Mit Drift + ohne Drift |

## Anzeigen-Beispiel `AmpelPill.stories.tsx`

```tsx
import type { Meta, StoryObj } from '@storybook/react';
import { AmpelPill } from '@/components/AmpelPill';

const meta = {
  title: 'Components/AmpelPill',
  component: AmpelPill,
} satisfies Meta<typeof AmpelPill>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Gruen: Story = { args: { status: 'gruen' } };
export const Gelb: Story = { args: { status: 'gelb' } };
export const Rot: Story = { args: { status: 'rot' } };
export const NichtBeurteilbar: Story = { args: { status: 'nicht_beurteilbar' } };
```

## CI-Integration (Folge-Sprint)

Storybook-CI-Build (`npm run build-storybook`) + axe-storybook-Addon
fuer a11y-Regression. Heute NICHT in CI weil package.json-Dep
required + GitHub-Pages-Deploy waere separater Sprint.

## Bewusst NICHT in Scope (U-86)

- Storybook als Dependency in `package.json` aufnehmen
- CI-Build fuer Storybook-Snapshots
- Chromatic-Visual-Regression-Service (kostenpflichtig, verstoesst
  gegen CHF-0-Disziplin ADR-005)
- Stories-Auto-Generation aus Komponenten-Files
- Pro-Sektion-Stories (heute nur Empfehlungen)

## Weiterfuehrendes

- [storybook.js docs](https://storybook.js.org)
- `5eyes-electron/frontend/reporting/DESIGN_SYSTEM.md` —
  Tailwind-Tokens-Referenz
- Roadmap-Punkt #50 (Dark-Mode) — Storybook kann beide Themes zeigen
- Roadmap-Punkt #90 (a11y) — axe-storybook-Addon als Folge
