/**
 * REPORT-CODE-SPLIT-001: Report-Sektionen als Lazy-Chunks.
 */
import { render, screen } from '@testing-library/react';
import { readFileSync } from 'fs';
import { dirname, join } from 'path';
import { Suspense } from 'react';
import { fileURLToPath } from 'url';
import { describe, expect, it } from 'vitest';

import { REPORT_SECTIONS } from '@/components/Sidebar';
import { makeCover } from '@/test/fixtures';
import { LazyCover, SECTION_LOADERS, SectionSkeleton, preloadSection } from './lazySections';

const __dirname = dirname(fileURLToPath(import.meta.url));

describe('lazySections', () => {
  it('jede Report-Sektion der Sidebar hat einen Chunk-Loader', () => {
    for (const s of REPORT_SECTIONS) {
      expect(Object.keys(SECTION_LOADERS)).toContain(s.id);
    }
  });

  it('jeder Loader liefert eine React-Komponente als default', async () => {
    for (const [id, load] of Object.entries(SECTION_LOADERS)) {
      const mod = await load();
      expect(typeof mod.default, id).toBe('function');
    }
  });

  it('preloadSection ignoriert unbekannte IDs ohne Fehler', () => {
    expect(() => preloadSection('gibt-es-nicht')).not.toThrow();
  });

  it('Suspense zeigt den Skeleton und danach die Sektion', async () => {
    render(
      <Suspense fallback={<SectionSkeleton />}>
        <LazyCover data={makeCover()} />
      </Suspense>,
    );
    expect(await screen.findByTestId('report-page-cover')).toBeInTheDocument();
    expect(screen.queryByTestId('report-section-skeleton')).toBeNull();
  });

  it('Skeleton belegt die Geometrie von ReportPage (kein Layout-Sprung)', () => {
    render(<SectionSkeleton />);
    const sk = screen.getByTestId('report-section-skeleton');
    for (const cls of ['mx-auto', 'min-h-screen', 'max-w-editorial', 'px-page-x', 'py-page-y']) {
      expect(sk.className.split(/\s+/)).toContain(cls);
    }
    expect(sk.getAttribute('aria-busy')).toBe('true');
  });

  it('App.tsx importiert keine Report-Seite mehr statisch (sonst landet sie im Haupt-Bundle)', () => {
    const app = readFileSync(join(__dirname, '..', 'App.tsx'), 'utf8');
    expect(app).not.toMatch(/^import\s+\{[^}]*\}\s+from\s+'@\/pages\/(?!lazySections)/m);
    expect(app).not.toMatch(/^import\s+\{\s*ProfilingPage\s*\}/m);
  });
});
