/**
 * Sprint U-46 (Roadmap-Punkt 46, 2026-06-04): Design-System-Doc-Drift-Schutz.
 *
 * Verifiziert dass die in DESIGN_SYSTEM.md dokumentierten Token-Werte
 * mit tailwind.config.ts uebereinstimmen. Wenn jemand einen Farbwert
 * in der Config aendert ohne die Doku zu updaten -> Test schlaegt fehl.
 */
import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(__dirname, '..');

const DESIGN_DOC = readFileSync(resolve(ROOT, 'DESIGN_SYSTEM.md'), 'utf-8');
const TAILWIND_CONFIG = readFileSync(resolve(ROOT, 'tailwind.config.ts'), 'utf-8');
const GLOBALS_CSS = readFileSync(resolve(ROOT, 'src/styles/globals.css'), 'utf-8');


describe('U-46 Design-System Drift-Schutz', () => {
  it('Canvas-Farbwerte stimmen in Doc + Config ueberein', () => {
    expect(DESIGN_DOC).toMatch(/#FAFAF6/);
    expect(TAILWIND_CONFIG).toMatch(/#FAFAF6/);
    expect(DESIGN_DOC).toMatch(/#F4F3EE/);
    expect(TAILWIND_CONFIG).toMatch(/#F4F3EE/);
  });

  it('Ink-Farbwerte stimmen in Doc + Config ueberein', () => {
    expect(DESIGN_DOC).toMatch(/#0F1C2E/);
    expect(TAILWIND_CONFIG).toMatch(/#0F1C2E/);
    expect(DESIGN_DOC).toMatch(/#3B475A/);
    expect(TAILWIND_CONFIG).toMatch(/#3B475A/);
  });

  it('Accent-Farbwert stimmt ueberein', () => {
    expect(DESIGN_DOC).toMatch(/#2C5F5F/);
    expect(TAILWIND_CONFIG).toMatch(/#2C5F5F/);
  });

  it('Status-Farben stimmen ueberein', () => {
    expect(DESIGN_DOC).toMatch(/#4E6F58/);  // gruen
    expect(TAILWIND_CONFIG).toMatch(/#4E6F58/);
    expect(DESIGN_DOC).toMatch(/#B59243/);  // gelb
    expect(TAILWIND_CONFIG).toMatch(/#B59243/);
    expect(DESIGN_DOC).toMatch(/#9E4747/);  // rot
    expect(TAILWIND_CONFIG).toMatch(/#9E4747/);
  });

  it('Font-Stack in Doc + Config konsistent', () => {
    // Cormorant Garamond als Serif
    expect(DESIGN_DOC).toMatch(/Cormorant Garamond/);
    expect(TAILWIND_CONFIG).toMatch(/Cormorant Garamond/);
    // Inter als Sans
    expect(DESIGN_DOC).toMatch(/Inter/);
    expect(TAILWIND_CONFIG).toMatch(/Inter/);
  });

  it('Schriftgroessen-Hierarchie in Doc enthaelt alle Tailwind-Tokens', () => {
    for (const token of ['display', 'h1', 'h2', 'h3', 'body', 'caption', 'micro']) {
      expect(DESIGN_DOC).toMatch(new RegExp(`text-${token}`));
      expect(TAILWIND_CONFIG).toMatch(new RegExp(`'${token}'`));
    }
  });

  it('Spacing-Tokens (page-x, page-y, section, block) in beiden vorhanden', () => {
    for (const token of ['page-x', 'page-y', 'section', 'block']) {
      expect(DESIGN_DOC).toMatch(new RegExp(token));
      expect(TAILWIND_CONFIG).toMatch(new RegExp(`'${token}'`));
    }
  });

  it('max-w-editorial-Token in beiden vorhanden', () => {
    expect(DESIGN_DOC).toMatch(/max-w-editorial/);
    expect(TAILWIND_CONFIG).toMatch(/editorial/);
  });

  it('Status-Pill-Komponente in Doc + globals.css verlinkt', () => {
    expect(DESIGN_DOC).toMatch(/status-pill/);
    expect(GLOBALS_CSS).toMatch(/status-pill/);
  });

  it('section-title-Komponente in Doc + globals.css verlinkt', () => {
    expect(DESIGN_DOC).toMatch(/section-title/);
    expect(GLOBALS_CSS).toMatch(/\.section-title/);
  });

  it('Print-Disziplin Sprint-Audit erwaehnt U-47 + U-52', () => {
    expect(DESIGN_DOC).toMatch(/U-47/);
    expect(DESIGN_DOC).toMatch(/U-52/);
  });

  it('Branding-Verbote-Sektion erwaehnt Signal-Farben + Drittmarken', () => {
    expect(DESIGN_DOC.toLowerCase()).toMatch(/signal/);
    expect(DESIGN_DOC.toLowerCase()).toMatch(/drittmarken|dritt-marken|3rd-party|drittmarke/);
  });

  it('Sprint-Audit-Trail enthaelt aktuelle Sprints', () => {
    // Alle FE-relevante Sprints muessen im Trail stehen
    for (const sprint of ['U-47', 'U-52', 'U-14', 'U-15', 'U-48', 'U-49', 'U-51', 'U-46']) {
      expect(DESIGN_DOC).toMatch(new RegExp(sprint));
    }
  });
});
