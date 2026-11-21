/*
 * H-180 (EXE-03): Version und Build-Kennung sichtbar machen.
 *
 * Liest das oeffentliche /health des lokalen Backends (in der gepackten EXE mit
 * Version aus package.json und Git-SHA des Builds, siehe
 * ares-backend/core/build_info.py) und zeigt "Ares <Version> · Build <SHA7>"
 * im Anmeldefenster (#ares-build-info). Im Quellbetrieb fehlt der SHA; dann
 * steht dort "Entwicklungsstand". Fehler bleiben still (rein informativ).
 */
(function () {
  function label(payload) {
    if (!payload || typeof payload !== 'object') return '';
    var version = String(payload.version || '').trim();
    var sha = String(payload.build_sha || '').trim();
    var text = 'Ares' + (version ? ' ' + version : '');
    if (/^[0-9a-f]{7,40}$/.test(sha)) text += ' · Build ' + sha.slice(0, 7);
    else text += ' · Entwicklungsstand';
    return text;
  }

  async function render() {
    var el = document.getElementById('ares-build-info');
    if (!el || !window.AresAPI || typeof window.AresAPI.getBackendRuntime !== 'function') return;
    try {
      var runtime = await window.AresAPI.getBackendRuntime();
      var base = runtime && runtime.baseUrl ? runtime.baseUrl : '';
      var response = await fetch(base + '/health', { cache: 'no-store' });
      if (!response.ok) return;
      el.textContent = label(await response.json());
    } catch (_err) {
      /* rein informativ */
    }
  }

  window.AresBuildInfo = { label: label, render: render };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', render);
  else render();
})();
