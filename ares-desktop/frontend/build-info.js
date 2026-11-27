/*
 * H-180 (EXE-03): Version und Build-Kennung sichtbar machen.
 *
 * Liest das oeffentliche /health des lokalen Backends (in der gepackten EXE mit
 * Version aus package.json und Git-SHA des Builds, siehe
 * ares-backend/config.py: build_info/build_sha) und zeigt "Ares <Version> · Build <SHA7>"
 * im Anmeldefenster (#ares-build-info, unter "Advisory OS" angelegt). Im Quellbetrieb fehlt der SHA; dann
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

  function ensureElement() {
    var el = document.getElementById('ares-build-info');
    if (el) return el;
    var overlay = document.getElementById('login-overlay');
    if (!overlay) return null;
    var anchor = Array.prototype.find.call(overlay.querySelectorAll('div'), function (d) {
      return d.children.length === 0 && String(d.textContent || '').trim() === 'Advisory OS';
    });
    if (!anchor || !anchor.parentNode) return null;
    el = document.createElement('div');
    el.id = 'ares-build-info';
    el.style.cssText = 'font-size:10px;color:var(--g3);margin-top:2px;';
    anchor.parentNode.appendChild(el);
    return el;
  }

  async function render() {
    var el = ensureElement();
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
