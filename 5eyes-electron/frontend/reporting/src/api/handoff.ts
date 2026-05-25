/**
 * Sprint U-P22.6 — Token-Handoff von der 5eyes-Hauptapp.
 *
 * Use-Case: Berater klickt in der Hauptapp einen "Advisory-Report öffnen"-
 * Button. Hauptapp liest ihren Bearer-Token (sessionStorage['5eyes_token']
 * oder window.desktop.getAuthToken in Electron) und öffnet die Reporting-
 * Sub-App per `window.open` mit der URL:
 *
 *     http://localhost:5173/mandates/<id>/report#token=<jwt>
 *
 * Diese Datei wird in `main.tsx` SOFORT beim Boot ausgeführt — VOR React
 * rendert — damit der Token bereits in sessionStorage liegt, wenn der
 * erste `fetchAdvisoryReport`-Aufruf passiert.
 *
 * URL-Fragment statt Query-String, weil:
 *  1. Fragments werden NIEMALS an den Server gesendet (nicht im Backend-Log)
 *  2. Fragment wird nach dem Verbrauch via history.replaceState gelöscht,
 *     damit der Token weder im Browser-History noch im React-Router-Pfad
 *     auftaucht
 *
 * Sicherheits-Hinweis: für Dev-Workflow ausreichend. In Produktion
 * (U-P27, Electron-Integration) wird der Token via
 * `window.desktop.getAuthToken` direkt aus dem Electron-Storage gelesen
 * — kein URL-Pass mehr nötig.
 *
 * Konvention für den Key `5eyes_token` ist die gleiche wie in
 * 5eyes-electron/frontend/5eyes_v2.html (suche dort nach `5eyes_token`).
 */

const TOKEN_STORAGE_KEY = '5eyes_token';
const HANDOFF_PARAM = 'token';

export interface HandoffResult {
  /** true wenn ein Token im Fragment war und übernommen wurde */
  consumed: boolean;
  /** für Telemetrie/Tests: wo der Token landete, oder null bei Skip */
  destination: 'sessionStorage' | null;
}

/**
 * Liest `#token=<jwt>` aus `window.location.hash`, schreibt den Token
 * in `sessionStorage['5eyes_token']` und bereinigt die URL.
 *
 * Idempotent: mehrfacher Aufruf ohne Fragment ist No-Op.
 * Side-Effect-frei in Test-Umgebungen ohne `window`.
 */
export function consumeHandoffFromUrlFragment(): HandoffResult {
  if (typeof window === 'undefined') {
    return { consumed: false, destination: null };
  }

  const hash = window.location.hash || '';
  if (!hash.includes(`${HANDOFF_PARAM}=`)) {
    return { consumed: false, destination: null };
  }

  // Hash kann "#token=abc" oder "#/route?token=abc" oder "#foo=1&token=abc"
  // sein. URLSearchParams wirft bei "/route?..." nicht, sondern parsed das
  // wie eine querystring. Wir extrahieren rein den `token=...`-Teil.
  const fragment = hash.startsWith('#') ? hash.slice(1) : hash;
  const params = new URLSearchParams(fragment.replace(/^[^?]*\?/, ''));
  // Fallback: wenn der Fragment KEIN "?" enthielt, ist das ganze Fragment
  // selbst die Query — direkt parsen.
  const token = params.get(HANDOFF_PARAM) ?? new URLSearchParams(fragment).get(HANDOFF_PARAM);
  if (!token) {
    return { consumed: false, destination: null };
  }

  try {
    window.sessionStorage.setItem(TOKEN_STORAGE_KEY, token);
  } catch {
    // sessionStorage kann in extrem restriktiven Browsern fehlen.
    // Fail-soft: kein Crash, Reporting-App wird dann 401 zeigen und
    // der Berater muss den Token manuell setzen.
    return { consumed: false, destination: null };
  }

  // URL-Cleanup: alle Hash-Parameter löschen, History-Eintrag erneuern
  // (replaceState statt pushState, damit Back-Button funktioniert).
  try {
    const clean = window.location.pathname + window.location.search;
    window.history.replaceState(null, '', clean);
  } catch {
    // Failed replaceState ist nicht tragisch — Token ist trotzdem gesetzt.
  }

  return { consumed: true, destination: 'sessionStorage' };
}
