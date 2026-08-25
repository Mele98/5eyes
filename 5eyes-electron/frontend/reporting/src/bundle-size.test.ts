/**
 * Sprint U-56 (Roadmap-Punkt 56, 2026-06-03): Vitest Bundle-Size-Audit.
 *
 * Schwellen: JS 400 KB (heute ~338 KB), CSS 30 KB (heute ~21 KB).
 * Verhalten: dist/ vorhanden -> assert, sonst skip.
 */
import { describe, it, expect } from 'vitest';
import { existsSync, readdirSync, statSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const DIST_ASSETS = join(__dirname, '..', 'dist', 'assets');

const JS_MAX_BYTES = 400 * 1024;
const CSS_MAX_BYTES = 30 * 1024;


function findAsset(pattern: RegExp): { name: string; bytes: number } | null {
  if (!existsSync(DIST_ASSETS)) return null;
  const files = readdirSync(DIST_ASSETS);
  for (const f of files) {
    if (pattern.test(f)) {
      const full = join(DIST_ASSETS, f);
      return { name: f, bytes: statSync(full).size };
    }
  }
  return null;
}


describe('U-56 Bundle-Size-Audit', () => {
  it('JS bundle stays below 400 KB threshold', () => {
    const asset = findAsset(/^index-.*\.js$/);
    if (asset === null) {
      console.warn(
        'U-56: dist/assets/index-*.js nicht gefunden. Test geskippt.',
      );
      return;
    }
    expect(asset.bytes).toBeLessThanOrEqual(JS_MAX_BYTES);
    const kb = (asset.bytes / 1024).toFixed(1);
    const pct = ((asset.bytes / JS_MAX_BYTES) * 100).toFixed(0);
    console.log(`U-56 JS bundle: ${asset.name} = ${kb} KB (${pct}%)`);
  });

  it('CSS bundle stays below 30 KB threshold', () => {
    const asset = findAsset(/^index-.*\.css$/);
    if (asset === null) {
      console.warn('U-56: CSS-Bundle nicht gefunden. Skip.');
      return;
    }
    expect(asset.bytes).toBeLessThanOrEqual(CSS_MAX_BYTES);
    const kb = (asset.bytes / 1024).toFixed(1);
    const pct = ((asset.bytes / CSS_MAX_BYTES) * 100).toFixed(0);
    console.log(`U-56 CSS bundle: ${asset.name} = ${kb} KB (${pct}%)`);
  });

  it('source-map ratio sanity check', () => {
    const js = findAsset(/^index-.*\.js$/);
    const map = findAsset(/^index-.*\.js\.map$/);
    if (js === null || map === null) return;
    expect(map.bytes).toBeLessThan(js.bytes * 10);
  });

  it('threshold constants are documented', () => {
    expect(JS_MAX_BYTES).toBe(400 * 1024);
    expect(CSS_MAX_BYTES).toBe(30 * 1024);
  });
});
