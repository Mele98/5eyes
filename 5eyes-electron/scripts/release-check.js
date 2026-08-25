const fs = require('fs');
const path = require('path');

const projectRoot = path.resolve(__dirname, '..');
const packageJson = JSON.parse(fs.readFileSync(path.join(projectRoot, 'package.json'), 'utf8'));
const strict = process.env.STRICT_RELEASE === '1';
const frontendHtmlPath = path.join(projectRoot, 'frontend', '5eyes_v2.html');
const frontendHtml = fs.readFileSync(frontendHtmlPath, 'utf8');
const backendRoot = path.resolve(projectRoot, '..', '5eyes-backend');

function exists(relPath) {
  return fs.existsSync(path.join(projectRoot, relPath));
}

const warnings = [];
const errors = [];

['assets/icons/app.ico', 'assets/icons/installer-icon.ico', 'assets/icons/uninstaller-icon.ico'].forEach((file) => {
  if (!exists(file)) {
    errors.push(`Fehlende Build-Ressource: ${file}`);
  }
});

[
  'CormorantGaramond-Regular.ttf',
  'CormorantGaramond-Italic.ttf',
  'CormorantGaramond-SemiBold.ttf',
  'Inter-Regular.ttf',
  'Inter-SemiBold.ttf',
  'Inter-Medium.ttf',
].forEach((file) => {
  const fontPath = path.join(backendRoot, 'assets', 'fonts', file);
  if (!fs.existsSync(fontPath)) {
    errors.push(`Fehlende PDF-Font-Ressource: 5eyes-backend/assets/fonts/${file}`);
  }
});

if (!frontendHtml.trim().endsWith('</html>')) {
  errors.push('frontend/5eyes_v2.html endet nicht sauber mit </html>.');
}

// U-6: Sub-App muss vor dem electron-builder-Lauf gebaut sein, sonst
// landet eine veraltete oder leere `dist/` im Installer.
const reportingDistIndex = path.join(projectRoot, 'frontend', 'reporting', 'dist', 'index.html');
const reportingSrcEntry = path.join(projectRoot, 'frontend', 'reporting', 'src', 'main.tsx');
if (!fs.existsSync(reportingDistIndex)) {
  errors.push(
    'frontend/reporting/dist/index.html fehlt. `npm run build:reporting` ausfuehren oder `npm run dist:win` (chained den Build automatisch).'
  );
} else if (fs.existsSync(reportingSrcEntry)) {
  const distMtime = fs.statSync(reportingDistIndex).mtimeMs;
  const srcMtime = fs.statSync(reportingSrcEntry).mtimeMs;
  if (srcMtime > distMtime) {
    warnings.push(
      'frontend/reporting/dist ist aelter als frontend/reporting/src — Sub-App vor Release neu bauen (`npm run build:reporting`).'
    );
    if (strict) {
      errors.push('STRICT_RELEASE=1: reporting/dist ist veraltet gegen reporting/src.');
    }
  }
}

// U-6: bundle/backend/5eyes-api.exe muss existieren, sonst hat der
// electron-builder-Lauf keinen Backend-Server zum Mitpacken.
const bundleBackendExe = path.join(projectRoot, 'bundle', 'backend', '5eyes-api.exe');
if (!fs.existsSync(bundleBackendExe)) {
  warnings.push(
    'bundle/backend/5eyes-api.exe fehlt. `npm run build:backend` ausfuehren (laeuft automatisch in `npm run dist:win`).'
  );
  if (strict) {
    errors.push('STRICT_RELEASE=1: bundle/backend/5eyes-api.exe fehlt.');
  }
}

if (frontendHtml.includes('vendor/chart.min.js') && !exists('frontend/vendor/chart.min.js')) {
  warnings.push('Lokale Chart.js-Referenz vorhanden, aber frontend/vendor/chart.min.js fehlt noch. vendor_assets.py ausführen.');
  if (strict) {
    errors.push('STRICT_RELEASE=1 gesetzt, aber vendor/chart.min.js fehlt.');
  }
}

const externalMarkers = ['fonts.googleapis.com', 'fonts.gstatic.com', 'cdnjs.cloudflare.com', 'cdn.jsdelivr.net'];
const remainingExternal = externalMarkers.filter((marker) => frontendHtml.includes(marker));
if (remainingExternal.length > 0) {
  warnings.push(`Frontend enthält noch externe CDN-/Font-Referenzen: ${remainingExternal.join(', ')}`);
  if (strict) {
    errors.push('STRICT_RELEASE=1 gesetzt, aber externe Frontend-Referenzen sind noch vorhanden.');
  }
}

const publish = packageJson.build && Array.isArray(packageJson.build.publish) ? packageJson.build.publish[0] : null;
if (!publish || !publish.url) {
  warnings.push('Kein Publish-Provider konfiguriert. Auto-Update bleibt deaktiviert.');
} else if (String(publish.url).includes('example.invalid')) {
  warnings.push('Publish-URL ist noch Platzhalter. Vor echtem Release ersetzen.');
  if (strict) {
    errors.push('STRICT_RELEASE=1 gesetzt, aber Publish-URL ist noch Platzhalter.');
  }
}

if (!process.env.CSC_LINK) {
  warnings.push('CSC_LINK nicht gesetzt. Der Windows-Build wird unsigniert erstellt.');
}
if (!process.env.CSC_KEY_PASSWORD && process.env.CSC_LINK) {
  warnings.push('CSC_LINK gesetzt, aber CSC_KEY_PASSWORD fehlt. Signierung wird scheitern.');
  if (strict) {
    errors.push('STRICT_RELEASE=1 gesetzt, aber CSC_KEY_PASSWORD fehlt.');
  }
}

console.log('Release-Preflight für 5Eyes WealthArchitekten');
for (const warning of warnings) console.warn(`WARNUNG: ${warning}`);
for (const error of errors) console.error(`FEHLER: ${error}`);

if (errors.length > 0) {
  process.exit(1);
}
