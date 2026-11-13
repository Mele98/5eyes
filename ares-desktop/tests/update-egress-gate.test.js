'use strict';
// N-899-09 (H10): Desktop-Update nur mit wirksamer Freigabe des Kanals
// updates.desktop. Reiner Node-Test, Electron wird nicht gestartet.
const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');
const { evaluateEgressApproval, UPDATE_CHANNEL_ID } = require('../update-gate');

test('ohne Status ist die Update-Pruefung gesperrt', () => {
  assert.deepStrictEqual(evaluateEgressApproval(null), { allowed: false, reason: 'EGRESS_MANIFEST_MISSING' });
});

test('Kanal nicht freigegeben -> gesperrt', () => {
  assert.strictEqual(evaluateEgressApproval({ approved_channels: ['market_data.stooq'], blocked_channels: [] }).allowed, false);
});

test('blockierter Kanal liefert seinen Grund', () => {
  const status = { approved_channels: [UPDATE_CHANNEL_ID],
    blocked_channels: [{ channel_id: UPDATE_CHANNEL_ID, reason_code: 'EGRESS_HASH_MISMATCH' }] };
  assert.deepStrictEqual(evaluateEgressApproval(status), { allowed: false, reason: 'EGRESS_HASH_MISMATCH' });
});

test('freigegebener Kanal -> erlaubt', () => {
  assert.deepStrictEqual(evaluateEgressApproval({ approved_channels: [UPDATE_CHANNEL_ID], blocked_channels: [] }),
    { allowed: true, reason: null });
});

test('main.js prueft die Freigabe vor autoUpdater.checkForUpdates', () => {
  const source = fs.readFileSync(path.join(__dirname, '..', 'main.js'), 'utf8');
  const body = source.slice(source.indexOf('async function checkForUpdates()'));
  assert.ok(body.indexOf('evaluateEgressApproval(await egressStatusFetcher())') > 0);
  assert.ok(body.indexOf('evaluateEgressApproval') < body.indexOf('autoUpdater.checkForUpdates()'));
});
