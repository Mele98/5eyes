const { spawnSync } = require('child_process');
const fs = require('fs');
const path = require('path');

// W2-804-03: Ares wird nur fuer Windows ausgeliefert. Der Bundle-Vertrag kennt
// genau ein natives Backend-Artefakt (die Windows-EXE); ausserhalb von Windows
// sofort abbrechen, bevor Build-/Dist-/Bundle-Ordner geloescht oder
// PyInstaller gestartet wird.
if (process.platform !== 'win32') {
  console.error(
    `Ares wird nur fuer Windows ausgeliefert; build:backend erzeugt ares-api.exe und ist auf Plattform '${process.platform}' nicht unterstuetzt.`
  );
  process.exit(1);
}

const projectRoot = path.resolve(__dirname, '..', '..');
const backendRoot = path.join(projectRoot, 'ares-backend');
const bundleBackendDir = path.join(projectRoot, 'ares-desktop', 'bundle', 'backend');
const distExe = path.join(backendRoot, 'dist', 'ares-api.exe');
const isWindows = process.platform === 'win32';
const buildWithSqlcipher = process.env.BUILD_WITH_SQLCIPHER === '1';

function run(command, args, cwd) {
  const result = spawnSync(command, args, {
    cwd,
    stdio: 'inherit',
    shell: isWindows,
  });

  if (result.status !== 0) {
    process.exit(result.status || 1);
  }
}

function copyIfExists(sourcePath, destPath) {
  if (!fs.existsSync(sourcePath)) {
    return;
  }
  fs.mkdirSync(path.dirname(destPath), { recursive: true });
  fs.copyFileSync(sourcePath, destPath);
}

function ensureMainEntrypoint() {
  const mainPy = fs.readFileSync(path.join(backendRoot, 'main.py'), 'utf8');
  if (!mainPy.includes("if __name__ == '__main__':") && !mainPy.includes('if __name__ == "__main__":')) {
    console.error('main.py has no executable __main__ entry point. The PyInstaller EXE would exit immediately.');
    process.exit(1);
  }
}

fs.rmSync(path.join(backendRoot, 'build'), { recursive: true, force: true });
fs.rmSync(path.join(backendRoot, 'dist'), { recursive: true, force: true });
fs.rmSync(path.join(backendRoot, 'ares-api.spec'), { force: true });
fs.rmSync(bundleBackendDir, { recursive: true, force: true });
fs.mkdirSync(bundleBackendDir, { recursive: true });
ensureMainEntrypoint();

const addDataArg = isWindows
  ? 'ares_schema.sql;.'
  : 'ares_schema.sql:.';
const fontDataArg = isWindows
  ? 'assets/fonts;assets/fonts'
  : 'assets/fonts:assets/fonts';
// X1/X3 (Laenderpakete): Pack-Manifeste und Pack-Texte (DocumentSet) sind
// Daten und muessen neben jurisdictions/*.py im Bundle liegen. Jede neue
// YAML-Datei unter jurisdictions/ gehoert in diese Liste
// (tests/test_jurisdiction_document_set.py prueft das).
const jurisdictionPackManifests = [
  'jurisdictions/ch/pack.yaml',
  'jurisdictions/ch/documents/de-CH/cost_disclosure.yaml',
  'jurisdictions/ch/documents/de-CH/legal.yaml',
  'jurisdictions/ch/documents/de-CH/strategy_report.yaml',
];

// W1-803-03: Die Reporting-Sub-App wird in die EXE eingebettet (Ziel
// `reporting_dist`, aufgeloest in ares-backend/main.py). Vorher lag sie nur im
// app.asar, das der Python-Prozess nicht lesen kann -> /reporting gab in jeder
// gepackten App 404. Fail-closed: ohne gebaute Sub-App kein Backend-Build.
const reportingDistDir = path.join(projectRoot, 'ares-desktop', 'frontend', 'reporting', 'dist');
if (!fs.existsSync(path.join(reportingDistDir, 'index.html'))) {
  console.error(
    `Reporting-Sub-App nicht gebaut (${path.join(reportingDistDir, 'index.html')} fehlt). ` +
      'Zuerst `npm run build:reporting` ausfuehren.'
  );
  process.exit(1);
}
// Relativ zu ares-backend (cwd von PyInstaller): run() nutzt unter Windows
// shell:true, ein absoluter Pfad mit Leerzeichen wuerde zerfallen.
const reportingDataArg = `../ares-desktop/frontend/reporting/dist${isWindows ? ';' : ':'}reporting_dist`;

const hiddenImports = [
  'uvicorn.logging',
  'uvicorn.loops',
  'uvicorn.loops.auto',
  'uvicorn.protocols',
  'uvicorn.protocols.http',
  'uvicorn.protocols.http.auto',
  'uvicorn.protocols.websockets',
  'uvicorn.protocols.websockets.auto',
  'uvicorn.lifespan',
  'uvicorn.lifespan.on',
  'sqlalchemy.dialects.sqlite',
  'sqlalchemy.orm',
  'pydantic_settings',
  'jwt',
  'passlib.handlers.bcrypt',
  'multipart',
  'apscheduler.schedulers.background',
  'apscheduler.triggers.cron',
  'aiofiles',
  'yfinance',
  'pandas',
  'numpy',
  'requests',
  'requests.adapters',
  'urllib3',
  'certifi',
  'dateutil',
  'dateutil.tz',
  'tzdata',
  'packaging',
  'anyio',
  'sniffio',
  'starlette',
  'fastapi',
  'bcrypt',
  'services.pdf.documents.anlagestrategie',
  // U-6: advisory_report + depotcheck + backtest fehlten — sie waren
  // seit Sprint U-P26 hinzugekommen und ohne expliziten Hidden-Import
  // wurde der PyInstaller-EXE-Build mit ModuleNotFoundError bei
  // Advisory-Report-Requests laufzeitlich crashen.
  'services.pdf.documents.advisory_report',
  'services.pdf.documents.asset_allocation',
  'services.pdf.documents.backtest',
  'services.pdf.documents.depotcheck',
  'services.pdf.documents.portfolio',
  'services.pdf.documents.protokoll',
  'services.pdf.documents.risikoprofil',
  'services.pdf.documents.vertrag',
  'services.market_data.annual_returns_backfill',
  'services.market_data.asset_class_price_backfill',
  // U-6: advisory_report-Aggregator + advisory_log_service werden
  // lazy aus routers.pdf_reports / routers.allocation importiert —
  // PyInstaller statisch-Analyse uebersieht das.
  'services.advisory_report',
  'services.advisory_log_service',
];

const collectSubmodules = [
  'uvicorn',
  'fastapi',
  'starlette',
  'sqlalchemy',
  'apscheduler',
  'yfinance',
  'pydantic',
  'pydantic_core',
  'pydantic_settings',
  'passlib',
  'bcrypt',
  'pandas',
  'numpy',
  'dateutil',
  'requests',
  'urllib3',
  'anyio',
  'services.pdf',
  // U-6: defensive Erweiterung — neue Module unter routers/, services/,
  // models/ koennen so dazukommen ohne build-backend.js anfassen zu
  // muessen. PyInstaller scannt rekursiv und nimmt alle Sub-Module
  // automatisch mit.
  'services',
  'routers',
  'models',
  'jurisdictions',
];

const pyInstallerArgs = [
  '--noconfirm',
  '--clean',
  '--onefile',
  '--name',
  'ares-api',
  '--add-data',
  addDataArg,
  '--add-data',
  fontDataArg,
  '--add-data',
  reportingDataArg,
];
for (const manifest of jurisdictionPackManifests) {
  const targetDir = path.posix.dirname(manifest);
  pyInstallerArgs.push('--add-data', isWindows ? `${manifest};${targetDir}` : `${manifest}:${targetDir}`);
}

for (const mod of hiddenImports) {
  pyInstallerArgs.push('--hidden-import', mod);
}
for (const mod of collectSubmodules) {
  pyInstallerArgs.push('--collect-submodules', mod);
}
for (const pkg of [
  'fastapi',
  'starlette',
  'uvicorn',
  'sqlalchemy',
  'pydantic',
  'pydantic-settings',
  'passlib',
  'apscheduler',
  'yfinance',
  'pandas',
  'numpy',
  'requests',
  'urllib3',
  'certifi',
  'python-dateutil',
  'tzdata',
]) {
  pyInstallerArgs.push('--copy-metadata', pkg);
}

if (buildWithSqlcipher) {
  pyInstallerArgs.push('--hidden-import', 'sqlcipher3');
  pyInstallerArgs.push('--collect-submodules', 'sqlcipher3');
}

pyInstallerArgs.push('main.py');

run('pyinstaller', pyInstallerArgs, backendRoot);

if (!fs.existsSync(distExe)) {
  console.error(`Expected executable was not created: ${distExe}`);
  process.exit(1);
}

copyIfExists(distExe, path.join(bundleBackendDir, 'ares-api.exe'));
// DESK-002 (Codex-Audit 2026-08-26): frueher wurde ein evtl. vorhandenes
// ares-backend/.env (mit echten SECRET_KEY/DB_KEY/API-Key-Werten des
// Build-Rechners) 1:1 in den Bundle-Ordner kopiert. package.json packt
// bundle/backend komplett per extraResources in JEDEN Installer, der auf
// diesem Rechner gebaut wird -- damit haetten echte Produktionsgeheimnisse
// in jeder ausgelieferten .exe gesteckt. Ein .env mit echten Werten darf
// NIE gebaut, kopiert oder ausgeliefert werden. Nur die secret-freie
// .env.example (Platzhalter-Werte) bleibt Teil des Bundles;
// scripts/bundle-secret-scan.js prueft das nach diesem Build-Schritt
// zusaetzlich als harte Absicherung.
copyIfExists(path.join(backendRoot, '.env.example'), path.join(bundleBackendDir, '.env.example'));
copyIfExists(path.join(backendRoot, 'README_price_updater.md'), path.join(bundleBackendDir, 'README_price_updater.md'));
console.log(`Backend bundle ready at ${path.join(bundleBackendDir, 'ares-api.exe')}`);
