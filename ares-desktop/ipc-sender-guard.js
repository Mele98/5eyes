'use strict';
/**
 * A3 P2-5 / U-6: zentrale Absender-Pruefung fuer alle IPC-Kanaele.
 *
 * Bewusst ohne `electron`-Import, damit die Pruefung ohne Electron-Runtime
 * unit-getestet werden kann (tests/ipc-sender-guard.test.js).
 *
 * Erlaubt ist ausschliesslich der Top-Level-Frame, dessen URL auf die lokale
 * Entry-Datei zeigt (file://, kein Host). Query und Fragment sind erlaubt
 * (die App laedt die Entry mit `?intro=1`). Alles andere -- fehlender Frame,
 * Subframe, fremdes Schema, anderer Pfad, UNC-Host, kodierte Separatoren --
 * wird abgelehnt.
 */
const path = require('path');

function decodePathname(pathname) {
  // Segmentweise dekodieren, damit Kodierungsunterschiede (z.B. Umlaute,
  // Leerzeichen) zwischen Chromium und Node keinen legitimen Absender
  // ablehnen. Ein kodierter Separator oder NUL in einem Segment ist nie
  // legitim und fuehrt zur Ablehnung.
  const segments = String(pathname).split('/');
  const decoded = [];
  for (const segment of segments) {
    let value;
    try {
      value = decodeURIComponent(segment);
    } catch {
      return null;
    }
    if (/[\\/\0]/.test(value)) return null;
    decoded.push(value);
  }
  return decoded.join('/');
}

function expectedUrlPath(entryPath, isWindows) {
  // Erwarteter Pfad in URL-Pfadform (unkodiert):
  // Windows `C:<sep>a<sep>b.html` -> `/C:/a/b.html`, POSIX unveraendert.
  if (isWindows) {
    return `/${path.win32.resolve(entryPath).split(path.win32.sep).join('/')}`;
  }
  return path.posix.resolve(entryPath);
}

/**
 * Prueft, ob `url` exakt die lokale Entry-Datei `entryPath` adressiert.
 * Liefert `{ ok: true }` oder `{ ok: false, reason }`.
 */
function checkTrustedRendererUrl(url, entryPath, platform = process.platform) {
  if (typeof url !== 'string' || url.length === 0) return { ok: false, reason: 'missing-url' };
  if (typeof entryPath !== 'string' || entryPath.length === 0) return { ok: false, reason: 'missing-entry' };
  let actual;
  try {
    actual = new URL(url);
  } catch {
    return { ok: false, reason: 'invalid-url' };
  }
  if (actual.protocol !== 'file:') return { ok: false, reason: 'protocol' };
  if (actual.host !== '') return { ok: false, reason: 'host' };
  if (actual.username || actual.password) return { ok: false, reason: 'credentials' };

  const isWindows = platform === 'win32';
  const expectedPath = expectedUrlPath(entryPath, isWindows);

  // actual.pathname ist bereits vom URL-Parser normalisiert (`..`, `%2e%2e`).
  const actualPath = decodePathname(actual.pathname);
  if (actualPath === null) return { ok: false, reason: 'path-encoding' };

  // Windows-Dateisysteme sind case-insensitiv: dieselbe Datei in anderer
  // Schreibweise ist derselbe Absender. POSIX bleibt exakt.
  const same = isWindows
    ? actualPath.toLowerCase() === expectedPath.toLowerCase()
    : actualPath === expectedPath;
  return same ? { ok: true } : { ok: false, reason: 'path' };
}

/**
 * Prueft ein IpcMainInvokeEvent: senderFrame vorhanden, Top-Level-Frame und
 * URL = lokale Entry-Datei.
 */
function checkTrustedIpcSender(event, entryPath, platform = process.platform) {
  const frame = event && event.senderFrame;
  if (!frame) return { ok: false, reason: 'no-sender-frame' };
  if (frame.parent) return { ok: false, reason: 'subframe' };
  return checkTrustedRendererUrl(frame.url, entryPath, platform);
}

/**
 * Log-taugliche Kurzform einer Absender-URL: nur Schema und Host, nie Pfad,
 * Query oder Fragment (dort koennen Tokens oder Kundendaten stehen).
 */
function describeSenderForLog(event) {
  const frame = event && event.senderFrame;
  if (!frame) return 'sender=none';
  let origin = 'invalid';
  try {
    const parsed = new URL(String(frame.url || ''));
    origin = `${parsed.protocol}//${parsed.host}`;
  } catch {
    origin = 'invalid';
  }
  return `sender=${origin} top_level=${frame.parent ? 'no' : 'yes'}`;
}

module.exports = {
  checkTrustedRendererUrl,
  checkTrustedIpcSender,
  describeSenderForLog,
};
