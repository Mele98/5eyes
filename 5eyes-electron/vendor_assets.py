#!/usr/bin/env python3
"""
5Eyes — Assets lokal vendoren
==============================
Lädt Chart.js herunter und ersetzt Google Fonts mit System-Font-Fallbacks.
Macht das Frontend vollständig offline-fähig für den Windows-Installer.

Verwendung:
    cd 5eyes-electron
    python vendor_assets.py

Was passiert:
    1. Chart.js 4.5.1 via jsDelivr → frontend/vendor/chart.min.js
    2. Google Fonts CSS → inline Font-Stack mit System-Fonts als Fallback
    3. HTML-Referenzen aktualisiert und externe CDN-Fallbacks entfernt
"""
import re
import shutil
import sys
import urllib.error
import urllib.request
from pathlib import Path


FRONTEND_DIR = Path(__file__).parent / 'frontend'
VENDOR_DIR = FRONTEND_DIR / 'vendor'
HTML_FILE = FRONTEND_DIR / '5eyes_v2.html'

CHART_JS_VERSION = '4.4.1'
CHART_JS_URL = f'https://cdn.jsdelivr.net/npm/chart.js@{CHART_JS_VERSION}/dist/chart.umd.min.js'
CHART_JS_LOCAL = 'vendor/chart.min.js'

INLINE_FONTS_CSS = """
<style>
/* Vendored: replaces Google Fonts (DM Sans + EB Garamond) */
:root {
  --f-s: system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
  --f-d: Georgia, "Times New Roman", "Palatino Linotype", serif;
}
body { font-family: var(--f-s); }
</style>
""".strip()

LOCAL_CHART_TAG = '<script>/* Vendored Chart.js for offline desktop builds */</script>\n<script src="vendor/chart.min.js"></script>'


def download_file(url: str, dest: Path) -> bool:
    print(f'  Downloading: {url}')
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=30) as response:
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(response.read())
        print(f'  ✓ Saved: {dest} ({dest.stat().st_size:,} bytes)')
        return True
    except urllib.error.URLError as exc:
        print(f'  ✗ Download failed: {exc}')
        return False


def vendor_assets() -> int:
    print('=' * 60)
    print('  5Eyes — Vendoring Assets für Offline-Build')
    print('=' * 60)

    if not HTML_FILE.exists():
        print(f'✗ HTML-Datei nicht gefunden: {HTML_FILE}')
        return 1

    html = HTML_FILE.read_text(encoding='utf-8')
    original_size = len(html)
    changed = False

    print('\n1. Chart.js vendoring...')
    chart_dest = VENDOR_DIR / 'chart.min.js'
    if not chart_dest.exists():
        success = download_file(CHART_JS_URL, chart_dest)
        if not success:
            print('  ✗ Chart.js konnte nicht heruntergeladen werden. Build bleibt mit Warnung offline-unvollständig.')
            return 1
    else:
        print(f'  ✓ Already vendored: {chart_dest}')

    chart_patterns = [
        r'<script>[^<]*Chart\.js[^<]*</script>\s*<script[^>]*src="vendor/chart\.min\.js"[^>]*></script>',
        r'<script[^>]*src="https://[^"\']*chart\.js[^"\']*"[^>]*></script>',
        r'<script[^>]*src="vendor/chart\.min\.js"[^>]*></script>',
    ]
    replaced_chart_tag = False
    for pattern in chart_patterns:
        if re.search(pattern, html):
            html = re.sub(pattern, LOCAL_CHART_TAG, html, count=1)
            changed = True
            replaced_chart_tag = True
            break
    if not replaced_chart_tag and LOCAL_CHART_TAG not in html:
        html = html.replace('<script src="./desktop-api.js"></script>', LOCAL_CHART_TAG + '\n<script src="./desktop-api.js"></script>', 1)
        changed = True
    print('  ✓ HTML reference points to local Chart.js')

    print('\n2. Google Fonts → System Fonts...')
    if 'fonts.googleapis.com' in html or 'fonts.gstatic.com' in html:
        html = re.sub(r'<link[^>]*fonts\.googleapis\.com[^>]*>', INLINE_FONTS_CSS, html)
        html = re.sub(r'@import\s+url\([^)]*fonts\.googleapis\.com[^)]*\);?', '', html)
        changed = True
        print('  ✓ Google Fonts replaced with system font stack')
    else:
        print('  ✓ No Google Fonts reference found (already removed or not present)')

    print('\n3. Verifikation...')
    remaining_external = [pattern for pattern in ('fonts.googleapis.com', 'fonts.gstatic.com', 'cdnjs.cloudflare.com', 'cdn.jsdelivr.net') if pattern in html]
    if remaining_external:
        print(f'  ⚠ Verbleibende externe Referenzen: {remaining_external}')
        return 1
    print('  ✓ Keine externen CDN-Referenzen mehr')

    if changed:
        backup = HTML_FILE.with_suffix('.html.pre-vendor')
        shutil.copy2(HTML_FILE, backup)
        HTML_FILE.write_text(html, encoding='utf-8')
        print(f'\n✓ HTML aktualisiert ({original_size:,} → {len(html):,} chars)')
        print(f'  Backup: {backup}')
    else:
        print('\n  Keine Änderungen nötig.')

    print('\n' + '=' * 60)
    print('  Vendoring abgeschlossen.')
    print('=' * 60)
    return 0


if __name__ == '__main__':
    raise SystemExit(vendor_assets())
