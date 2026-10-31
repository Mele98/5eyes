/**
 * Einzige Quelle des Browser-Storage-Schluessels fuer den Access-Token.
 *
 * Vertrag mit der Hauptapp: `ares-desktop/frontend/ares.html` schreibt und
 * liest denselben Schluessel als Literal (`API.setToken`/`API.getToken`,
 * `resolveReportingAppUrl`). `tests/test_reporting_mainapp_handoff.py`
 * prueft, dass beide Seiten identisch sind.
 *
 * Der Token liegt nur in `sessionStorage` (fluechtig pro Tab). Es gibt
 * bewusst keine Rueckfallquelle in `localStorage`.
 */
export const AUTH_TOKEN_STORAGE_KEY = 'ares.token';
