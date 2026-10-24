/**
 * REPORT-CODE-SPLIT-001 (2026-10-18): Report-Sektionen als eigene Chunks.
 *
 * Vorher lagen alle 19 Sektionen im Haupt-Bundle (inkl. framer-motion fuer
 * die Cover-Animation, ~107 KB) -- das Bundle stand am 400-KB-Budget
 * (src/bundle-size.test.ts). Jede Sektion ist eine eigene Route und wird
 * nur auf ihrer Route gerendert, also per React.lazy ausgelagert (analog zu
 * den *Editor-Chunks in App.tsx).
 *
 * Kein zusaetzlicher Wasserfall: ReportShell ruft `preloadSection()` beim
 * Mount auf, damit der Chunk PARALLEL zum Advisory-Report-Fetch laedt.
 * Waehrend des Fetches steht ohnehin das LoadingPanel; der Suspense-
 * Fallback (`SectionSkeleton`) greift nur, wenn der Chunk ausnahmsweise
 * langsamer als die Daten ist, und belegt dieselbe Flaeche wie
 * `ReportPage` (min-h-screen, gleiche Paddings) -- kein Layout-Sprung.
 */
import { lazy, type ComponentType } from 'react';

type Loader<P> = () => Promise<{ default: ComponentType<P> }>;

/**
 * Pro Sektion EIN Loader. Dieselbe Funktion speist lazy() und preload --
 * der Browser cached das Modul, ein zweiter import() laedt nicht neu.
 */
export const SECTION_LOADERS = {
  cover: () => import('@/pages/Cover').then((m) => ({ default: m.Cover })),
  disclaimer: () => import('@/pages/Disclaimer').then((m) => ({ default: m.Disclaimer })),
  toc: () =>
    import('@/pages/Inhaltsverzeichnis').then((m) => ({ default: m.Inhaltsverzeichnis })),
  ausgangslage: () => import('@/pages/Ausgangslage').then((m) => ({ default: m.Ausgangslage })),
  positionen: () => import('@/pages/Positionen').then((m) => ({ default: m.Positionen })),
  pruefpunkte: () => import('@/pages/Pruefpunkte').then((m) => ({ default: m.Pruefpunkte })),
  erkenntnisse: () => import('@/pages/Erkenntnisse').then((m) => ({ default: m.Erkenntnisse })),
  'asset-allocation': () =>
    import('@/pages/AssetAllocation').then((m) => ({ default: m.AssetAllocation })),
  risikowaehrungen: () =>
    import('@/pages/Risikowaehrungen').then((m) => ({ default: m.Risikowaehrungen })),
  branchen: () => import('@/pages/Branchen').then((m) => ({ default: m.Branchen })),
  goals: () => import('@/pages/Goals').then((m) => ({ default: m.Goals })),
  risikoprofil: () => import('@/pages/Risikoprofil').then((m) => ({ default: m.Risikoprofil })),
  'building-blocks': () =>
    import('@/pages/BuildingBlocks').then((m) => ({ default: m.BuildingBlocks })),
  'statement-pm': () => import('@/pages/StatementPm').then((m) => ({ default: m.StatementPm })),
  'weiteres-vorgehen': () =>
    import('@/pages/WeiteresVorgehen').then((m) => ({ default: m.WeiteresVorgehen })),
  beratungsprotokoll: () =>
    import('@/pages/Beratungsprotokoll').then((m) => ({ default: m.Beratungsprotokoll })),
  kosten: () => import('@/pages/Kostenausweis').then((m) => ({ default: m.Kostenausweis })),
  compliance: () => import('@/pages/Compliance').then((m) => ({ default: m.Compliance })),
  eignung: () => import('@/pages/Eignung').then((m) => ({ default: m.Eignung })),
} as const;

export type LazySectionId = keyof typeof SECTION_LOADERS;

/** Startet das Laden des Sektions-Chunks (fire-and-forget, Fehler zeigt Suspense/ErrorBoundary). */
export function preloadSection(sectionId: string): void {
  const loader = (SECTION_LOADERS as Record<string, Loader<never> | undefined>)[sectionId];
  if (loader) {
    loader().catch(() => {
      /* Fehler tritt beim echten Render erneut auf und wird dort behandelt */
    });
  }
}

export const LazyCover = lazy(SECTION_LOADERS.cover);
export const LazyDisclaimer = lazy(SECTION_LOADERS.disclaimer);
export const LazyInhaltsverzeichnis = lazy(SECTION_LOADERS.toc);
export const LazyAusgangslage = lazy(SECTION_LOADERS.ausgangslage);
export const LazyPositionen = lazy(SECTION_LOADERS.positionen);
export const LazyPruefpunkte = lazy(SECTION_LOADERS.pruefpunkte);
export const LazyErkenntnisse = lazy(SECTION_LOADERS.erkenntnisse);
export const LazyAssetAllocation = lazy(SECTION_LOADERS['asset-allocation']);
export const LazyRisikowaehrungen = lazy(SECTION_LOADERS.risikowaehrungen);
export const LazyBranchen = lazy(SECTION_LOADERS.branchen);
export const LazyGoals = lazy(SECTION_LOADERS.goals);
export const LazyRisikoprofil = lazy(SECTION_LOADERS.risikoprofil);
export const LazyBuildingBlocks = lazy(SECTION_LOADERS['building-blocks']);
export const LazyStatementPm = lazy(SECTION_LOADERS['statement-pm']);
export const LazyWeiteresVorgehen = lazy(SECTION_LOADERS['weiteres-vorgehen']);
export const LazyBeratungsprotokoll = lazy(SECTION_LOADERS.beratungsprotokoll);
export const LazyKostenausweis = lazy(SECTION_LOADERS.kosten);
export const LazyCompliance = lazy(SECTION_LOADERS.compliance);
export const LazyEignung = lazy(SECTION_LOADERS.eignung);

/**
 * Ruhiger Platzhalter in der Geometrie von `ReportPage` (Kicker, Titel,
 * Trennlinie, Inhaltsflaeche) -- keine Animation, kein Layout-Sprung.
 */
export function SectionSkeleton() {
  return (
    <article
      data-testid="report-section-skeleton"
      aria-busy="true"
      aria-live="polite"
      className="relative mx-auto min-h-screen max-w-editorial px-page-x py-page-y print:min-h-0"
    >
      <span className="sr-only">Sektion wird geladen</span>
      <div aria-hidden="true">
        <div className="h-3 w-40 rounded-card bg-canvas-subtle" />
        <div className="mt-block border-b border-rule pb-block">
          <div className="h-9 w-2/3 rounded-card bg-canvas-subtle" />
          <div className="mt-3 h-6 w-1/2 rounded-card bg-canvas-subtle" />
        </div>
        <div className="mt-section space-y-4">
          <div className="h-4 w-full rounded-card bg-canvas-subtle" />
          <div className="h-4 w-11/12 rounded-card bg-canvas-subtle" />
          <div className="h-4 w-4/5 rounded-card bg-canvas-subtle" />
        </div>
      </div>
    </article>
  );
}
