import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import { Sidebar, REPORT_SECTIONS } from './Sidebar';

/**
 * Sprint U-90 (2026-06-06): a11y-Tests fuer die Sub-App-Sidebar.
 *
 * Pruefen WCAG-relevante Patterns:
 *   - aside hat aria-label
 *   - nav hat aria-label + id (fuer aria-controls vom Hamburger)
 *   - hamburger-Button hat aria-label, aria-expanded, aria-controls
 *   - active NavLink hat aria-current='page'
 *   - dekorative Icons sind aria-hidden
 *   - sr-only Praefix vor Sektion-Titel ('Sektion N: ')
 *   - focus-visible-Ring-Klassen vorhanden
 */

function renderSidebar(activeSection: string = 'cover') {
  // Sprint U-90: NavLink in react-router-dom v6 setzt aria-current
  // automatisch nur wenn das URL matched. Damit unser Test gegen
  // den expliziten activeSection-Prop testet, setzen wir die
  // MemoryRouter-URL passend zur erwarteten Sektion.
  const section = REPORT_SECTIONS.find((s) => s.id === activeSection);
  const path = section?.path
    ? `/mandates/m-test/report/${section.path}`
    : '/mandates/m-test/report';
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Sidebar mandateId="m-test" activeSection={activeSection} />
    </MemoryRouter>,
  );
}

describe('Sidebar a11y (U-90)', () => {
  it('aside hat aria-label fuer Screen-Reader-Verbalisierung', () => {
    renderSidebar();
    const aside = screen.getByTestId('report-sidebar');
    expect(aside.getAttribute('aria-label')).toBe('Beratungsreport-Navigation');
  });

  it('nav-Element hat eigenen aria-label', () => {
    renderSidebar();
    const navs = screen.getAllByRole('navigation');
    // Mindestens eine nav muss Berichtssektionen-Label haben
    const reportNav = navs.find(
      (n) => n.getAttribute('aria-label') === 'Berichtssektionen',
    );
    expect(reportNav).toBeDefined();
  });

  it('Hamburger-Button hat aria-controls auf nav-id', () => {
    renderSidebar();
    const button = screen.getByRole('button', { name: /Navigation/ });
    expect(button.getAttribute('aria-controls')).toBe('report-sidebar-nav');
    expect(button.getAttribute('aria-expanded')).toBe('false');
  });

  it('Hamburger-Icons sind aria-hidden (dekorativ)', () => {
    const { container } = renderSidebar();
    const hiddenSpans = container.querySelectorAll('[aria-hidden="true"]');
    // Mindestens das Hamburger-Container-Span + die Sektion-Number-Spans
    expect(hiddenSpans.length).toBeGreaterThan(0);
  });

  it('aktiver Link hat aria-current="page"', () => {
    renderSidebar('erkenntnisse');
    const links = screen.getAllByRole('link');
    const active = links.find(
      (l) => l.getAttribute('aria-current') === 'page',
    );
    expect(active).toBeDefined();
    expect(active?.textContent).toContain('Erkenntnisse');
  });

  it('nicht-aktive Links haben KEIN aria-current', () => {
    renderSidebar('erkenntnisse');
    const links = screen.getAllByRole('link');
    const others = links.filter(
      (l) => l.getAttribute('aria-current') !== 'page',
    );
    expect(others.length).toBe(REPORT_SECTIONS.length - 1);
  });

  it('Sektion-Titel haben sr-only "Sektion N:" Prefix fuer Screen-Reader', () => {
    renderSidebar();
    const srOnlyElements = document.querySelectorAll('.sr-only');
    // 17 Sektionen erwartet jeweils ein sr-only Prefix
    expect(srOnlyElements.length).toBeGreaterThanOrEqual(17);
  });

  it('NavLinks haben focus-visible-Ring-Klassen', () => {
    renderSidebar();
    const links = screen.getAllByRole('link');
    for (const link of links) {
      expect(link.className).toMatch(/focus-visible:ring/);
    }
  });
});
