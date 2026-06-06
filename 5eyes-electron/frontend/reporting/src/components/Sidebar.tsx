import { useState } from 'react';
import { NavLink } from 'react-router-dom';

export interface ReportSectionLink {
  id: string;
  nr: number;
  title: string;
  path: string;
}

export const REPORT_SECTIONS: ReportSectionLink[] = [
  { id: 'cover', nr: 1, title: 'Titelblatt', path: '' },
  { id: 'disclaimer', nr: 2, title: 'Disclaimer', path: 'disclaimer' },
  { id: 'toc', nr: 3, title: 'Inhaltsverzeichnis', path: 'toc' },
  { id: 'ausgangslage', nr: 4, title: 'Ausgangslage', path: 'ausgangslage' },
  { id: 'positionen', nr: 5, title: 'Positionen', path: 'positionen' },
  { id: 'pruefpunkte', nr: 6, title: 'Depotcheck', path: 'pruefpunkte' },
  { id: 'erkenntnisse', nr: 7, title: 'Erkenntnisse', path: 'erkenntnisse' },
  { id: 'asset-allocation', nr: 8, title: 'Asset Allocation', path: 'asset-allocation' },
  { id: 'risikowaehrungen', nr: 9, title: 'Risikowährungen', path: 'risikowaehrungen' },
  { id: 'branchen', nr: 10, title: 'Branchen', path: 'branchen' },
  { id: 'goals', nr: 11, title: 'Goal-Based Investing', path: 'goals' },
  { id: 'risikoprofil', nr: 12, title: 'Risikoprofil', path: 'risikoprofil' },
  { id: 'building-blocks', nr: 13, title: 'Building Blocks', path: 'building-blocks' },
  { id: 'statement-pm', nr: 14, title: 'Statement PM', path: 'statement-pm' },
  { id: 'weiteres-vorgehen', nr: 15, title: 'Weiteres Vorgehen', path: 'weiteres-vorgehen' },
  { id: 'beratungsprotokoll', nr: 16, title: 'Beratungsprotokoll', path: 'beratungsprotokoll' },
  // Sprint Compliance-Dashboard (2026-06-05): aggregiert die 5
  // Audit-Sektionen 19-23 (Suitability/Methodology/Recommendation/
  // MandateLock/LiquidityCascade) in einer Berater-Übersicht.
  { id: 'compliance', nr: 17, title: 'Compliance-Audit', path: 'compliance' },
];

interface SidebarProps {
  mandateId: string;
  activeSection: string;
}

export function Sidebar({ mandateId, activeSection }: SidebarProps) {
  const [isOpen, setIsOpen] = useState(false);

  return (
    <aside
      data-testid="report-sidebar"
      aria-label="Beratungsreport-Navigation"
      className="no-print border-b border-rule bg-canvas/95 lg:sticky lg:top-0 lg:h-screen lg:overflow-y-auto lg:border-b-0 lg:border-r"
    >
      <div className="flex items-center justify-between px-6 py-5 lg:block lg:px-6 lg:py-12">
        <div>
          <p className="font-serif text-h3 text-ink">5eyes</p>
          <p className="mt-1 text-micro uppercase text-ink-subtle">
            Advisory Report
          </p>
        </div>
        <button
          type="button"
          aria-label={isOpen ? 'Navigation schliessen' : 'Navigation oeffnen'}
          aria-expanded={isOpen}
          aria-controls="report-sidebar-nav"
          onClick={() => setIsOpen((value) => !value)}
          className="grid h-10 w-10 place-items-center border border-rule bg-canvas-panel lg:hidden"
        >
          <span aria-hidden="true" className="space-y-1.5">
            <span className="block h-px w-5 bg-ink" />
            <span className="block h-px w-5 bg-ink" />
            <span className="block h-px w-5 bg-ink" />
          </span>
        </button>
      </div>

      <nav
        id="report-sidebar-nav"
        aria-label="Berichtssektionen"
        className={`${isOpen ? 'block' : 'hidden'} px-6 pb-6 lg:block lg:pb-12`}
      >
        <ol className="space-y-1">
          {REPORT_SECTIONS.map((section) => {
            const isActive = section.id === activeSection;
            return (
              <li key={section.id}>
                <NavLink
                  to={sectionHref(mandateId, section)}
                  end
                  className={[
                    'grid grid-cols-[2.25rem_minmax(0,1fr)] gap-3 border-l px-3 py-2 text-caption transition-colors duration-soft',
                    'focus:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2',
                    isActive
                      ? 'border-accent text-ink'
                      : 'border-transparent text-ink-subtle hover:border-rule-strong hover:text-ink',
                  ].join(' ')}
                  onClick={() => setIsOpen(false)}
                >
                  <span aria-hidden="true" className="font-mono text-micro">
                    {String(section.nr).padStart(2, '0')}
                  </span>
                  <span>
                    <span className="sr-only">Sektion {section.nr}: </span>
                    {section.title}
                  </span>
                </NavLink>
              </li>
            );
          })}
        </ol>
      </nav>
    </aside>
  );
}

function sectionHref(mandateId: string, section: ReportSectionLink): string {
  const base = `/mandates/${mandateId}/report`;
  return section.path ? `${base}/${section.path}` : base;
}
