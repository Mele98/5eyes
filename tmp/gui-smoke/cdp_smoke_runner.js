const http = require('http');

async function getJson(url) {
  return new Promise((resolve, reject) => {
    http
      .get(url, (res) => {
        let body = '';
        res.setEncoding('utf8');
        res.on('data', (chunk) => {
          body += chunk;
        });
        res.on('end', () => {
          try {
            resolve(JSON.parse(body));
          } catch (error) {
            reject(new Error(`Invalid JSON from ${url}: ${body.slice(0, 300)}`));
          }
        });
      })
      .on('error', reject);
  });
}

async function connectToFirstPage(debugPort) {
  const targets = await getJson(`http://127.0.0.1:${debugPort}/json/list`);
  const page = targets.find((target) => target.type === 'page');
  if (!page || !page.webSocketDebuggerUrl) {
    throw new Error('No page target with webSocketDebuggerUrl found.');
  }

  const ws = new WebSocket(page.webSocketDebuggerUrl);
  await new Promise((resolve, reject) => {
    ws.addEventListener('open', resolve, { once: true });
    ws.addEventListener('error', reject, { once: true });
  });

  let nextId = 1;
  const pending = new Map();

  ws.addEventListener('message', (event) => {
    const payload = JSON.parse(String(event.data));
    if (!payload.id) return;
    const pair = pending.get(payload.id);
    if (!pair) return;
    pending.delete(payload.id);
    if (payload.error) pair.reject(new Error(payload.error.message || JSON.stringify(payload.error)));
    else pair.resolve(payload.result);
  });

  const send = (method, params = {}) =>
    new Promise((resolve, reject) => {
      const id = nextId++;
      pending.set(id, { resolve, reject });
      ws.send(JSON.stringify({ id, method, params }));
    });

  return { ws, send };
}

function renderException(result) {
  if (!result || !result.exceptionDetails) return null;
  const details = result.exceptionDetails;
  const text = details.text || 'Runtime.evaluate failed';
  const desc =
    details.exception && (details.exception.description || details.exception.value || details.exception.type);
  return desc ? `${text}: ${desc}` : text;
}

async function main() {
  const debugPort = Number(process.argv[2] || 9333);
  const { ws, send } = await connectToFirstPage(debugPort);
  await send('Runtime.enable');
  await send('Page.enable');

  const evaluate = async (expression) => {
    const result = await send('Runtime.evaluate', {
      expression,
      awaitPromise: true,
      returnByValue: true,
      userGesture: true,
    });
    const error = renderException(result);
    if (error) throw new Error(error);
    if (Object.prototype.hasOwnProperty.call(result.result, 'value')) return result.result.value;
    if (Object.prototype.hasOwnProperty.call(result.result, 'unserializableValue')) return result.result.unserializableValue;
    return null;
  };

  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

  const poll = async (label, expression, predicate, timeoutMs = 15000) => {
    const started = Date.now();
    let lastValue = null;
    while (Date.now() - started < timeoutMs) {
      lastValue = await evaluate(expression);
      if (predicate(lastValue)) return lastValue;
      await sleep(250);
    }
    throw new Error(`Timeout while waiting for ${label}. Last value: ${JSON.stringify(lastValue)}`);
  };

  const results = {};

  await poll(
    'frontend bootstrap',
    `(async () => ({readyState: document.readyState, hasApi: !!window.API, hasBootstrap: typeof doBootstrapAdmin === 'function'}))()`,
    (value) => value && value.readyState === 'complete' && value.hasBootstrap
  );

  await evaluate(`window.confirm = () => true; true;`);

  results.bootstrapStatus = await evaluate(`(async () => await API.get('/auth/bootstrap-status'))()`);

  if (results.bootstrapStatus && results.bootstrapStatus.setup_required) {
    await evaluate(`(() => {
      document.getElementById('bootstrap-full-name').value = 'Smoke Admin';
      document.getElementById('bootstrap-username').value = 'smoke_admin';
      document.getElementById('bootstrap-email').value = 'smoke@example.test';
      document.getElementById('bootstrap-password').value = 'SmokePass123!';
      document.getElementById('bootstrap-password-confirm').value = 'SmokePass123!';
      return true;
    })()`);
    await evaluate(`(async () => { await doBootstrapAdmin(); return true; })()`);
  }

  results.currentUser = await poll(
    'authenticated user',
    `(async () => ({user: currentUser ? {id: currentUser.id, username: currentUser.username, role: currentUser.role} : null, loginDisplay: document.getElementById('login-overlay').style.display}))()`,
    (value) => value && value.user && value.loginDisplay === 'none'
  );

  await evaluate(`(() => {
    document.getElementById('nc-firstname').value = 'Smoke';
    document.getElementById('nc-lastname').value = 'Client';
    document.getElementById('nc-canton').value = 'ZH';
    document.getElementById('nc-household').value = 'Einzelperson';
    document.getElementById('nc-type').value = 'Anlageberatung';
    return true;
  })()`);
  await evaluate(`(async () => { await createNewMandate(); return true; })()`);

  results.createdClient = await poll(
    'created client + mandate',
    `(async () => ({
      clientId: currentClientId,
      mandateId: currentMandateId,
      sidebarName: document.querySelector('.client.active .client-n')?.textContent || null
    }))()`,
    (value) => value && value.clientId && value.mandateId
  );

  await evaluate(`(() => {
    document.getElementById('acf-label').value = 'Smoke Einkommen';
    document.getElementById('acf-cftype').value = 'Income';
    document.getElementById('acf-amount').value = '120000';
    document.getElementById('acf-cat').value = 'Erwerbseinkommen';
    document.getElementById('acf-freq').value = 'jährlich';
    return true;
  })()`);
  await evaluate(`(async () => { await saveCashflow(); return true; })()`);

  results.cashflowsAfterCreate = await poll(
    'cashflow creation',
    `(async () => await API.get('/clients/' + currentClientId + '/cashflows'))()`,
    (value) => Array.isArray(value) && value.length === 1
  );

  await evaluate(`(async () => {
    await refreshCashflowsUI(currentClientId);
    const btn = document.querySelector('#zufluss-rows .cf-row .btn-ico, #abfluss-rows .cf-row .btn-ico');
    if (!btn) throw new Error('Cashflow delete button not found');
    dcf(btn);
    return true;
  })()`);

  results.cashflowsAfterDelete = await poll(
    'cashflow deletion',
    `(async () => await API.get('/clients/' + currentClientId + '/cashflows'))()`,
    (value) => Array.isArray(value) && value.length === 0
  );

  await evaluate(`(() => {
    document.getElementById('nz-label').value = 'Smoke Ziel';
    document.getElementById('nz-type').value = 'Einmalige_Ausgabe';
    document.getElementById('nz-prio').value = '1';
    document.getElementById('nz-amount').value = '250000';
    document.getElementById('nz-horizon').value = '8';
    return true;
  })()`);
  await evaluate(`(async () => { await saveGoal(); return true; })()`);

  results.goalsAfterCreate = await poll(
    'goal creation',
    `(async () => await API.get('/mandates/' + currentMandateId + '/goals'))()`,
    (value) => Array.isArray(value) && value.length === 1
  );

  await evaluate(`(async () => {
    await refreshGoalsUI(currentMandateId);
    const btn = document.querySelector('#zl .goal .btn-ico');
    if (!btn) throw new Error('Goal delete button not found');
    dg(btn);
    return true;
  })()`);

  results.goalsAfterDelete = await poll(
    'goal deletion',
    `(async () => await API.get('/mandates/' + currentMandateId + '/goals'))()`,
    (value) => Array.isArray(value) && value.length === 0
  );

  await evaluate(`(() => {
    _riskScoreResult = {
      capScore: 100,
      capProfile: 'Aktien',
      willScore: 100,
      willProfile: 'Aktien',
      finalScore: 100,
      finalProfile: 'Aktien',
      raw: { horizonIdx: 3, sparIdx: 3, liqIdx: 3, goalIdx: 3, prefIdx: 3, behavIdx: 3 }
    };
    return true;
  })()`);
  await evaluate(`(async () => { await saveRiskProfile(); return true; })()`);

  results.riskAssessments = await poll(
    'risk assessment save',
    `(async () => await API.get('/mandates/' + currentMandateId + '/risk-assessments'))()`,
    (value) => Array.isArray(value) && value.length >= 1
  );

  await evaluate(`(() => {
    document.getElementById('maw-cat').value = 'Liquiditaet';
    showAwFields('Liquiditaet');
    const section = document.getElementById('aw-Liquiditaet');
    section.querySelector('input.fi').value = 'Smoke Reserve';
    section.querySelector('input[type="number"]').value = '25000';
    document.getElementById('maw-note').value = 'Smoke Test';
    return true;
  })()`);
  await evaluate(`(async () => { await saveWealthPosition(); return true; })()`);

  results.wealthPositions = await poll(
    'wealth position save',
    `(async () => await API.get('/clients/' + currentClientId + '/wealth-positions'))()`,
    (value) => Array.isArray(value) && value.length >= 1
  );

  results.summary = {
    clientId: results.createdClient.clientId,
    mandateId: results.createdClient.mandateId,
    riskAssessments: results.riskAssessments.length,
    wealthPositions: results.wealthPositions.length,
  };

  console.log(JSON.stringify(results, null, 2));
  ws.close();
}

main().catch((error) => {
  console.error(error && error.stack ? error.stack : String(error));
  process.exit(1);
});
