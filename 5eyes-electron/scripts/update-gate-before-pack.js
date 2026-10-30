'use strict';
/**
 * UPDATE-001: electron-builder `beforePack`-Hook. Erzwingt das Update-Gate
 * auch dann, wenn electron-builder ohne `npm run preflight:release`
 * aufgerufen wird. Unvollstaendige Konfiguration -> Packaging bricht ab.
 */
const fs = require('fs');
const path = require('path');
const { evaluateBuildGate } = require('../update-gate.js');

const PACKAGE_JSON_PATH = path.resolve(__dirname, '..', 'package.json');

async function runUpdateGate({ env, packageJson }) {
  const { errors } = evaluateBuildGate({ env, packageJson });
  if (errors.length > 0) {
    throw new Error(errors.join('\n'));
  }
}

async function beforePack() {
  const packageJson = JSON.parse(fs.readFileSync(PACKAGE_JSON_PATH, 'utf8'));
  await runUpdateGate({ env: process.env, packageJson });
}

module.exports = beforePack;
module.exports.default = beforePack;
module.exports.runUpdateGate = runUpdateGate;
