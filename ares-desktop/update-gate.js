'use strict';
/**
 * UPDATE-001: Build-/Packaging-Gate fuer Desktop-Auto-Updates (fail-closed).
 *
 * Auto-Update bleibt deaktiviert, bis eine eigentuemerkontrollierte
 * HTTPS-Update-Adresse UND eine Code-Signing-Konfiguration vorhanden und
 * abgenommen sind. Das Gate wirkt an zwei Stellen:
 *  - beim Build (scripts/release-check.js + electron-builder beforePack):
 *    UPDATES_ENABLED=true ohne vollstaendige Konfiguration bricht ab;
 *  - zur Laufzeit (main.js): der Updater wird nur geladen, wenn die gepackte
 *    package.json `desktopUpdates.enabled === true` mit gueltiger Feed-URL
 *    traegt. Eine Laufzeit-Flag allein oeffnet das Gate nie.
 *
 * Keine Abhaengigkeit von Electron -> direkt mit node:test pruefbar.
 */

// Fuer Dokumentation/Beispiele reservierte oder lokale Namen (RFC 2606/6761/6762).
const RESERVED_TLDS = new Set(['invalid', 'example', 'test', 'localhost', 'local']);
const RESERVED_DOMAINS = ['example.com', 'example.net', 'example.org'];

function normalizeHost(host) {
  return String(host || '').trim().toLowerCase().replace(/\.$/, '');
}

function isReservedHost(host) {
  const h = normalizeHost(host);
  if (!h) return true;
  const labels = h.split('.');
  if (RESERVED_TLDS.has(labels[labels.length - 1])) return true;
  return RESERVED_DOMAINS.some((d) => h === d || h.endsWith(`.${d}`));
}

function checkFeedUrl(raw) {
  if (typeof raw !== 'string' || !raw.trim()) return { ok: false, reason: 'feed_url_missing' };
  let url;
  try {
    url = new URL(raw.trim());
  } catch {
    return { ok: false, reason: 'feed_url_invalid' };
  }
  if (url.protocol !== 'https:') return { ok: false, reason: 'feed_url_not_https' };
  if (url.username || url.password) return { ok: false, reason: 'feed_url_has_credentials' };
  const host = normalizeHost(url.hostname);
  if (host.startsWith('[') || /^\d{1,3}(\.\d{1,3}){3}$/.test(host)) return { ok: false, reason: 'feed_url_ip_literal' };
  if (!host.includes('.')) return { ok: false, reason: 'feed_url_not_qualified_host' };
  if (isReservedHost(host)) return { ok: false, reason: 'feed_url_placeholder_host' };
  return { ok: true, reason: null, url: url.href };
}

function parseUpdatesEnabled(env) {
  const raw = env ? env.UPDATES_ENABLED : undefined;
  if (raw === undefined || raw === '' || raw === 'false') return { value: false, error: null };
  if (raw === 'true') return { value: true, error: null };
  return {
    value: false,
    error: `UPDATE-001: UPDATES_ENABLED=${JSON.stringify(raw)} ist ungueltig (erlaubt: true|false).`,
  };
}

// Erkennt eine Code-Signing-Konfiguration ueber die von electron-builder
// dokumentierten Wege. Ob sie organisationsgebunden und abgenommen ist, bleibt
// eine Release-/Security-Freigabe ausserhalb des Codes.
function hasSigningConfig(env, buildConfig) {
  const e = env || {};
  if (e.CSC_LINK && e.CSC_KEY_PASSWORD) return true;
  if (e.WIN_CSC_LINK && e.WIN_CSC_KEY_PASSWORD) return true;
  const win = (buildConfig && buildConfig.win) || {};
  if (win.azureSignOptions && typeof win.azureSignOptions === 'object' && Object.keys(win.azureSignOptions).length > 0) {
    return true;
  }
  const st = win.signtoolOptions;
  if (st && typeof st === 'object' && (st.sign || st.certificateSubjectName || st.certificateSha1 || st.certificateFile)) {
    return true;
  }
  return false;
}

function publishEntries(build) {
  const publish = build ? build.publish : undefined;
  if (publish === null || publish === undefined) return [];
  return Array.isArray(publish) ? publish : [publish];
}

function evaluateBuildGate({ env, packageJson }) {
  const errors = [];
  const pkg = packageJson || {};
  const build = pkg.build || {};
  const desk = pkg.desktopUpdates || {};
  const parsed = parseUpdatesEnabled(env);
  if (parsed.error) errors.push(parsed.error);
  const updatesEnabled = parsed.value;
  const publish = publishEntries(build);

  if (!updatesEnabled) {
    if (build.publish !== null) {
      errors.push('UPDATE-001: build.publish muss null sein, solange UPDATES_ENABLED nicht true ist (keine Update-URL im Artefakt).');
    }
    if (desk.enabled !== false || desk.feedUrl !== undefined) {
      errors.push('UPDATE-001: desktopUpdates muss { "enabled": false } sein, solange UPDATES_ENABLED nicht true ist.');
    }
    return { updatesEnabled, errors };
  }

  const feed = checkFeedUrl(env.UPDATE_FEED_URL);
  if (!feed.ok) {
    errors.push(`UPDATE-001: UPDATE_FEED_URL fehlt oder ist keine eigentuemerkontrollierte HTTPS-Adresse (${feed.reason}).`);
  }
  if (!hasSigningConfig(env, build)) {
    errors.push('UPDATE-001: Keine Code-Signing-Konfiguration (CSC_LINK+CSC_KEY_PASSWORD, WIN_CSC_LINK+WIN_CSC_KEY_PASSWORD, win.signtoolOptions oder win.azureSignOptions).');
  }
  if (desk.enabled !== true || desk.feedUrl !== env.UPDATE_FEED_URL) {
    errors.push('UPDATE-001: desktopUpdates muss { "enabled": true, "feedUrl": <UPDATE_FEED_URL> } sein.');
  }
  if (publish.length !== 1 || publish[0].provider !== 'generic' || publish[0].url !== env.UPDATE_FEED_URL) {
    errors.push('UPDATE-001: build.publish muss genau einen generic-Provider mit url = UPDATE_FEED_URL enthalten.');
  }
  return { updatesEnabled, errors };
}

// Laufzeit: liest nur die (gepackte, schreibgeschuetzte) package.json.
function evaluateRuntimeUpdateGate({ packageJson, isPackaged }) {
  if (!isPackaged) return { enabled: false, reason: 'not_packaged' };
  const desk = (packageJson && packageJson.desktopUpdates) || {};
  if (desk.enabled !== true) return { enabled: false, reason: 'build_gate_closed' };
  const feed = checkFeedUrl(desk.feedUrl);
  if (!feed.ok) return { enabled: false, reason: feed.reason };
  return { enabled: true, reason: null, feedUrl: feed.url };
}

module.exports = {
  checkFeedUrl,
  evaluateBuildGate,
  evaluateRuntimeUpdateGate,
  hasSigningConfig,
  isReservedHost,
  parseUpdatesEnabled,
};
