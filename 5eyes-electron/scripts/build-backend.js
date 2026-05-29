const { spawnSync } = require('child_process');
const fs = require('fs');
const path = require('path');

const projectRoot = path.resolve(__dirname, '..', '..');
const backendRoot = path.join(projectRoot, '5eyes-backend');
const bundleBackendDir = path.join(projectRoot, '5eyes-electron', 'bundle', 'backend');
const distExe = path.join(backendRoot, 'dist', '5eyes-api.exe');
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
fs.rmSync(path.join(backendRoot, '5eyes-api.spec'), { force: true });
fs.rmSync(bundleBackendDir, { recursive: true, force: true });
fs.mkdirSync(bundleBackendDir, { recursive: true });
ensureMainEntrypoint();

const addDataArg = isWindows
  ? '5eyes_schema_v4.0_FINAL.sql;.'
  : '5eyes_schema_v4.0_FINAL.sql:.';
const fontDataArg = isWindows
  ? 'assets/fonts;assets/fonts'
  : 'assets/fonts:assets/fonts';

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
  'jose',
  'jose.jwt',
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
  'jose',
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
];

const pyInstallerArgs = [
  '--noconfirm',
  '--clean',
  '--onefile',
  '--name',
  '5eyes-api',
  '--add-data',
  addDataArg,
  '--add-data',
  fontDataArg,
];

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
  'python-jose',
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

copyIfExists(distExe, path.join(bundleBackendDir, '5eyes-api.exe'));
copyIfExists(path.join(backendRoot, '.env'), path.join(bundleBackendDir, '.env'));
copyIfExists(path.join(backendRoot, '.env.example'), path.join(bundleBackendDir, '.env.example'));
copyIfExists(path.join(backendRoot, 'README_price_updater.md'), path.join(bundleBackendDir, 'README_price_updater.md'));
console.log(`Backend bundle ready at ${path.join(bundleBackendDir, '5eyes-api.exe')}`);
