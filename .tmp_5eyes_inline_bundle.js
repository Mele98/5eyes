/* Vendored Chart.js for offline desktop builds */

// ─── 5EYES API LAYER ─────────────────────────────────────────────────
const API = {
  _token: null,
  _baseUrl: null,
  async baseUrl() {
    if (!this._baseUrl) {
      if (window.FiveEyesAPI && typeof window.FiveEyesAPI.resolveBaseUrl === 'function') {
        this._baseUrl = await window.FiveEyesAPI.resolveBaseUrl();
      } else if (window.desktop && typeof window.desktop.getBackendBaseUrl === 'function') {
        this._baseUrl = await window.desktop.getBackendBaseUrl();
      } else {
        this._baseUrl = 'http://127.0.0.1:8000';
      }
    }
    return this._baseUrl;
  },
  async setToken(t) {
    this._token = t || null;
    if (window.desktop && typeof window.desktop.setAuthToken === 'function' && t) {
      try { await window.desktop.setAuthToken(t); } catch(e){}
    } else if (window.desktop && typeof window.desktop.clearAuthToken === 'function' && !t) {
      try { await window.desktop.clearAuthToken(); } catch(e){}
    } else {
      try { t ? localStorage.setItem('5eyes_token', t) : localStorage.removeItem('5eyes_token'); } catch(e){}
    }
  },
  async getToken() {
    if (this._token) return this._token;
    if (window.desktop && typeof window.desktop.getAuthToken === 'function') {
      try { this._token = await window.desktop.getAuthToken(); } catch(e){}
    }
    if (!this._token) { try { this._token = localStorage.getItem('5eyes_token'); } catch(e){} }
    return this._token;
  },
  async fetch(path, options={}) {
    const base = await this.baseUrl();
    const token = await this.getToken();
    const headers = {'Content-Type':'application/json', ...(token?{'Authorization':'Bearer '+token}:{}), ...(options.headers||{})};
    const res = await fetch(base+path, {...options, headers});
    const retryAfter = Number.parseInt(res.headers.get('Retry-After') || '0', 10) || null;
    if (res.status === 401 && token && !path.startsWith('/auth/login') && !path.startsWith('/auth/bootstrap')) {
      await API.setToken(null);
      showLogin('Sitzung abgelaufen. Bitte erneut anmelden.');
    }
    if (!res.ok) {
      const txt = await res.text();
      let detail = txt;
      try {
        const parsed = JSON.parse(txt);
        if (parsed && typeof parsed === 'object' && parsed.detail) {
          if (typeof parsed.detail === 'string') detail = parsed.detail;
          else if (Array.isArray(parsed.detail)) {
            detail = parsed.detail.map(function(item){
              if (item && typeof item === 'object') return item.msg || item.message || JSON.stringify(item);
              return String(item);
            }).join(' | ');
          } else {
            detail = JSON.stringify(parsed.detail);
          }
        }
      } catch(e) {}
      const err = new Error('API '+res.status+': '+detail);
      err.status = res.status;
      err.detail = detail;
      err.retryAfter = retryAfter;
      err.body = txt;
      throw err;
    }
    if (res.status === 204) return null;
    const ct = res.headers.get('content-type')||'';
    return ct.includes('application/json') ? res.json() : res.text();
  },
  get(p){ return this.fetch(p); },
  post(p,b){ return this.fetch(p,{method:'POST',body:JSON.stringify(b)}); },
  put(p,b){ return this.fetch(p,{method:'PUT',body:JSON.stringify(b)}); },
  del(p){ return this.fetch(p,{method:'DELETE'}); },
};

let currentUser = null;
let liveClients = [];
let bootstrapStatusCache = null;

function setOverlayMode(mode) {
  const loginPanel = document.getElementById('login-panel');
  const bootstrapPanel = document.getElementById('bootstrap-panel');
  if (loginPanel) loginPanel.style.display = mode === 'bootstrap' ? 'none' : 'block';
  if (bootstrapPanel) bootstrapPanel.style.display = mode === 'bootstrap' ? 'block' : 'none';
}

function updateBootstrapHint() {
  const hint = document.getElementById('login-bootstrap-hint');
  if (hint) hint.style.display = bootstrapStatusCache && bootstrapStatusCache.setup_required ? 'block' : 'none';
}

function showLogin(message='') {
  const el = document.getElementById('login-overlay');
  if (el) el.style.display = 'flex';
  setOverlayMode('login');
  updateBootstrapHint();
  const errEl = document.getElementById('login-error');
  if (errEl) errEl.textContent = message || '';
}

function showBootstrap(message='') {
  const el = document.getElementById('login-overlay');
  if (el) el.style.display = 'flex';
  setOverlayMode('bootstrap');
  const errEl = document.getElementById('bootstrap-error');
  if (errEl) errEl.textContent = message || '';
}

function hideLogin() {
  const el = document.getElementById('login-overlay');
  if (el) el.style.display = 'none';
  const label = document.getElementById('current-user-label');
  if (label && currentUser) label.textContent = currentUser.full_name || currentUser.username || '';
  const logoutBtn = document.getElementById('btn-logout');
  if (logoutBtn) logoutBtn.style.display = 'inline-block';
  const adminBtn = document.getElementById('btn-admin-open');
  if (adminBtn) adminBtn.style.display = (currentUser && currentUser.role === 'admin') ? 'inline-block' : 'none';
  ensureFoundationExampleButton();
}

function foundationExampleStatus(message,isError){
  var el=document.getElementById('foundation-case-status');
  if(!el)return;
  el.textContent=message||'';
  el.style.color=isError?'rgba(255,193,193,0.92)':'rgba(255,255,255,0.72)';
}

function ensureFoundationExampleButton(){
  var existing=document.getElementById('btn-foundation-example');
  var status=document.getElementById('foundation-case-status');
  var sidebar=document.querySelector('.sidebar');
  var anchor=document.querySelector('.sidebar .sb-add')||document.querySelector('.sidebar .sb-scroll')||sidebar;
  if(!currentUser||currentUser.role!=='admin'||!anchor){
    if(existing)existing.remove();
    if(status)status.remove();
    return;
  }
  if(!existing){
    existing=document.createElement('button');
    existing.id='btn-foundation-example';
    existing.className='sb-add';
    existing.style.marginTop='8px';
    existing.style.background='rgba(255,255,255,0.08)';
    existing.style.border='1px solid rgba(255,255,255,0.14)';
    existing.style.color='rgba(255,255,255,0.86)';
    existing.textContent='Foundation Case laden';
    existing.onclick=createFoundationExampleCase;
    if(anchor===sidebar)sidebar.appendChild(existing);
    else anchor.insertAdjacentElement('afterend',existing);
  }
  if(!status){
    status=document.createElement('div');
    status.id='foundation-case-status';
    status.style.cssText='font-size:9px;line-height:1.5;color:rgba(255,255,255,0.62);padding:6px 12px 0;';
    existing.insertAdjacentElement('afterend',status);
  }
}

async function createFoundationExampleCase(){
  if(!currentUser||currentUser.role!=='admin')return false;
  var btn=document.getElementById('btn-foundation-example');
  if(btn){
    btn.disabled=true;
    btn.textContent='Foundation Case wird aufgebaut...';
  }
  foundationExampleStatus('Systemfall wird erstellt und live vorbereitet...',false);
  try{
    var result=await API.post('/admin/system/foundation-example',{});
    if(result&&result.mandate_id){
      delete allocationPreferencesCache[String(result.mandate_id)];
      try{localStorage.removeItem(allocationPreferenceStoragePrefix+String(result.mandate_id));}catch(e){}
    }
    foundationExampleStatus(
      (result.client_name||'Foundation Case')+' - Risiko '+String(result.risk_score||'?')+'/10 - Advisory '+formatRappen(result.advisory_wealth_rappen||0)
        +' - Goal Score '+String(result.goal_score_weighted_pct||0)+'%'
        +' - Downside '+String(result.target_downside_probability_pct||0)+'%'
        +' - P50 '+String(result.projection_end_year||'')+' '+formatRappen(result.target_terminal_p50_rappen||0)
        +' - Fresh '+String(result.market_data_fresh_coverage_pct||0)+'%'
        +' - MissingPx '+String(result.market_data_missing_price_count||0),
      false
    );
    await loadClients();
    if(result&&result.client_id)await loadClientById(result.client_id);
    persistAllocationPreferences(buildDefaultAllocationPreferences());
    syncAllocationPreferences();
    await refreshStrategyData(false,true);
    go('sd');
    return true;
  }catch(e){
    foundationExampleStatus('Foundation Case konnte nicht erstellt werden: '+String(e.detail||e.message||'?'),true);
    return false;
  }finally{
    if(btn){
      btn.disabled=false;
      btn.textContent='Foundation Case laden';
    }
  }
}

async function checkBootstrapStatus() {
  try {
    bootstrapStatusCache = await API.get('/auth/bootstrap-status');
  } catch(e) {
    bootstrapStatusCache = { setup_required: false, can_create_admin: false, backend_unreachable: true };
  }
  updateBootstrapHint();
  return bootstrapStatusCache;
}

async function doLogout() {
  try { await API.post('/auth/logout', {}); } catch(e) {}
  await API.setToken(null);
  currentUser = null;
  const label = document.getElementById('current-user-label');
  if (label) label.textContent = '';
  const logoutBtn = document.getElementById('btn-logout');
  if (logoutBtn) logoutBtn.style.display = 'none';
  const adminBtn = document.getElementById('btn-admin-open');
  if (adminBtn) adminBtn.style.display = 'none';
  ensureFoundationExampleButton();
  const status = await checkBootstrapStatus();
  if (status && status.setup_required) showBootstrap();
  else showLogin();
}

async function doLogin() {
  const username = document.getElementById('login-username').value.trim();
  const password = document.getElementById('login-password').value;
  const errEl = document.getElementById('login-error');
  const btn = document.getElementById('btn-login-submit');
  if (errEl) errEl.textContent = '';
  if (!username || !password) { if (errEl) errEl.textContent = 'Bitte Benutzername und Passwort eingeben.'; return; }
  if (btn) { btn.disabled = true; btn.textContent = 'Anmelden…'; }
  try {
    const data = await API.post('/auth/login', {username, password});
    await API.setToken(data.access_token);
    currentUser = data.user;
    hideLogin();
    await initApp();
  } catch(e) {
    if (e.status === 429) {
      const wait = e.retryAfter || 60;
      if (errEl) errEl.textContent = `Zu viele Fehlversuche. Bitte ${wait} Sekunden warten.`;
      if (btn) {
        let remaining = wait;
        const iv = setInterval(() => {
          remaining -= 1;
          if (remaining <= 0) {
            clearInterval(iv);
            btn.disabled = false;
            btn.textContent = 'Anmelden';
          } else {
            btn.textContent = `Warten… (${remaining}s)`;
          }
        }, 1000);
        return;
      }
    } else if (e.status === 401) {
      if (errEl) errEl.textContent = 'Benutzername oder Passwort falsch.';
    } else if (e.status === 403) {
      if (errEl) errEl.textContent = 'Konto deaktiviert.';
    } else if ((e.message || '').includes('Failed to fetch')) {
      if (errEl) errEl.textContent = 'Backend nicht erreichbar. Bitte App neu starten.';
    } else {
      if (errEl) errEl.textContent = 'Anmeldung fehlgeschlagen: ' + String(e.detail || e.message || e).slice(0, 120);
    }
  } finally {
    if (btn && !btn.textContent.includes('Warten')) { btn.disabled = false; btn.textContent = 'Anmelden'; }
  }
}

async function doBootstrapAdmin() {
  const fullName = document.getElementById('bootstrap-full-name').value.trim();
  const username = document.getElementById('bootstrap-username').value.trim();
  const email = document.getElementById('bootstrap-email').value.trim();
  const password = document.getElementById('bootstrap-password').value;
  const passwordConfirm = document.getElementById('bootstrap-password-confirm').value;
  const errEl = document.getElementById('bootstrap-error');
  const btn = document.getElementById('btn-bootstrap-submit');
  if (errEl) errEl.textContent = '';
  if (!fullName || !username || !password) {
    if (errEl) errEl.textContent = 'Bitte Name, Benutzername und Passwort ausfüllen.';
    return;
  }
  if (password !== passwordConfirm) {
    if (errEl) errEl.textContent = 'Die Passwörter stimmen nicht überein.';
    return;
  }
  if (btn) { btn.disabled = true; btn.textContent = 'Wird erstellt…'; }
  try {
    const data = await API.post('/auth/bootstrap-admin', { full_name: fullName, username, email: email || null, password });
    bootstrapStatusCache = { setup_required: false, can_create_admin: false };
    await API.setToken(data.access_token);
    currentUser = data.user;
    hideLogin();
    await initApp();
  } catch(e) {
    if (e.status === 409) {
      bootstrapStatusCache = { setup_required: false, can_create_admin: false };
      showLogin('Ersteinrichtung bereits abgeschlossen. Bitte normal anmelden.');
      return;
    }
    if (errEl) errEl.textContent = 'Ersteinrichtung fehlgeschlagen: ' + String(e.detail || e.message || e).slice(0, 140);
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = 'Admin anlegen'; }
  }
}

async function loadClients() {
  try {
    liveClients = await API.get('/clients');
    rebuildSidebar(liveClients);
    ensureFoundationExampleButton();
    if (liveClients.length > 0) loadClientById(liveClients[0].id);
  } catch(e) {
    // isNet: only true for real network failures (no TCP connection).
    // 4xx/5xx API errors have e.status set — those are not network failures.
    var isNet = !e.status && (
      (e.message||'').includes('Failed to fetch') ||
      (e.message||'').includes('NetworkError') ||
      (e.message||'').includes('Load failed') ||
      !navigator.onLine
    );
    if (isNet) {
      console.warn('Demo-Modus:', e.message);
      liveClients = PERSONAS.map(function(p){ return {id:p.id,client_number:p.id,first_name:p.name.split(' ')[0],last_name:p.name.split(' ').slice(1).join(' '),household_type:p.household,_persona:p}; });
      rebuildSidebar(liveClients);
      ensureFoundationExampleButton();
      if (liveClients.length > 0) loadPersona(liveClients[0].id);
      // App-weiter Demo-Banner: sichtbar auf allen Screens
      if (!document.getElementById('demo-mode-banner')) {
        var b = document.createElement('div');
        b.id = 'demo-mode-banner';
        b.style.cssText = 'position:fixed;top:0;left:0;right:0;z-index:9998;background:var(--warn);color:#1a1a1a;text-align:center;font-size:10px;font-weight:600;padding:3px 8px;letter-spacing:0.05em;pointer-events:none;';
        b.textContent = '⚠️ DEMO-MODUS — Backend nicht erreichbar — angezeigte Daten werden nicht gespeichert';
        document.body.appendChild(b);
      }
    } else {
      console.error('Clients-API Fehler (kein Mock-Fallback):', e.status, e.message);
      var sbl=document.getElementById('sbl');
      if(sbl)sbl.innerHTML='<div style="padding:8px 10px;font-size:10px;color:var(--neg)">Clients konnten nicht geladen werden.</div>';
      ensureFoundationExampleButton();
    }
  }
}
function rebuildSidebar(clients) {
  const sbl = document.getElementById('sbl');
  if (!sbl) return;
  sbl.innerHTML = '';
  clients.forEach(c => {
    const name = (c.first_name||'') + ' ' + (c.last_name||'');
    const number = c.client_number || c.id;
    const div = document.createElement('div');
    div.className = 'client';
    div.dataset.pid = c.id;
    div.dataset.cid = c.id;
    div.onclick = () => loadClientById(c.id);
    div.innerHTML = '<div class="client-n">'+name+'</div><div class="client-m">'+number+'</div>';
    sbl.appendChild(div);
  });
}
async function loadClientById(clientId) {
  const clientRef = liveClients.find(c => c.id === clientId);
  if (clientRef && clientRef._persona) {
    loadPersona(clientId); return;
  }
  try {
    const [clientRes, wealthRes, cashflowRes, mandatesRes, positionsRes] = await Promise.allSettled([
      API.get('/clients/'+clientId),
      API.get('/clients/'+clientId+'/wealth-summary'),
      API.get('/clients/'+clientId+'/cashflow-summary'),
      API.get('/clients/'+clientId+'/mandates'),
      API.get('/clients/'+clientId+'/wealth-positions'),
    ]);
    if (clientRes.status === 'fulfilled') {
      const c = clientRes.value;
      currentPersona = c;
      currentClientId = c.id;
      currentMandateId = null;
      if (mandatesRes.status === 'fulfilled' && Array.isArray(mandatesRes.value) && mandatesRes.value.length > 0) {
        var activeMandate = mandatesRes.value.find(function(m){ return m && m.status === 'Aktiv'; }) || mandatesRes.value[0];
        currentMandateId = activeMandate ? activeMandate.id : null;
      }
      strategyState={allocation:null,recommendation:null,activeMandateId:currentMandateId,lastGeneratedAt:0,loading:false,dirty:true,risk:null,buildingBlocks:[],marketRuntime:null};
      renderEngineRuntimePanels(null);
      document.querySelectorAll('.client').forEach(el =>
        el.classList.toggle('active', el.dataset.cid === c.id));
      const phS = document.querySelector('#page-sd .ph-s');
      if (phS) phS.textContent = (c.first_name||'') + ' ' + (c.last_name||'') + ' · ' + (c.household_type||'') + ' · ' + (c.canton || c.country_of_residence || '');
      if (wealthRes.status === 'fulfilled' && wealthRes.value) {
        const w = wealthRes.value;
        const fmtK = v => 'CHF ' + Math.round(v).toLocaleString('de-CH');
        const kRV = document.getElementById('kpi-reinvermoegen');
        if (kRV) kRV.textContent = fmtK(w.net_worth_chf);
        const kBV = document.getElementById('kpi-beratungsvermoegen');
        if (kBV) kBV.textContent = fmtK(w.advisory_wealth_chf);
      }
      if (positionsRes.status === 'fulfilled') {
        renderWealthPositions(positionsRes.value);
      }
      if (cashflowRes.status === 'fulfilled' && cashflowRes.value) {
        const cf = cashflowRes.value;
        const kCF = document.getElementById('kpi-cashflow');
        if (kCF) kCF.textContent = 'CHF ' + Math.round(cf.surplus_chf).toLocaleString('de-CH');
      }
      syncAllocationPreferences();
      refreshCashflowsUI(c.id);
      if(currentMandateId){
        refreshGoalsUI(currentMandateId);
        refreshReviewUI(currentMandateId);
      } else {
        renderDemoReviewUI();
      }
    }
  } catch(e) {
    var isNet2 = !e.status && (
      (e.message||'').includes('Failed to fetch') ||
      (e.message||'').includes('NetworkError') ||
      !navigator.onLine
    );
    if(isNet2&&clientRef&&clientRef._persona)loadPersona(clientId);
    else console.error('loadClientById error:',e.status,e.message);
  }
}
async function refreshPricesFromBackend() {
  try {
    await API.get('/admin/prices/status');
  } catch(e) { /* silent – might not be admin */ }
}

// ─── UPDATE MANAGEMENT ────────────────────────────────────────────────────────
function applyUpdateState(state) {
  const section = document.getElementById('update-section');
  const label = document.getElementById('update-status-label');
  const checkBtn = document.getElementById('btn-check-updates');
  const installBtn = document.getElementById('btn-install-update');
  if (!state || !section) return;
  if (!state.enabled) { section.style.display = 'none'; return; }
  section.style.display = 'block';
  if (state.checking) {
    if (label) label.textContent = 'Prüfe auf Updates…';
  } else if (state.downloaded) {
    if (label) label.textContent = 'Update ' + (state.latestVersion||'') + ' bereit zur Installation.';
    if (installBtn) installBtn.style.display = 'inline-block';
  } else if (state.available) {
    if (label) label.textContent = 'Update ' + (state.latestVersion||'') + ' wird heruntergeladen…';
  } else if (state.error) {
    if (label) label.textContent = 'Update-Fehler: ' + state.error.slice(0,60);
  } else {
    if (label) label.textContent = 'Aktuell (v' + (state.currentVersion||'?') + ')';
    if (installBtn) installBtn.style.display = 'none';
  }
  if (checkBtn) checkBtn.disabled = !!state.checking;
}

async function adminCheckUpdates() {
  const btn = document.getElementById('btn-check-updates');
  if (btn) { btn.disabled = true; btn.textContent = 'Prüfe…'; }
  try {
    if (window.FiveEyesAPI && window.FiveEyesAPI.updates) {
      const state = await window.FiveEyesAPI.updates.check();
      applyUpdateState(state);
    }
  } catch(e) {
    console.warn('Update check failed:', e);
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = 'Auf Updates prüfen'; }
  }
}

async function adminInstallUpdate() {
  try {
    if (window.FiveEyesAPI && window.FiveEyesAPI.updates) {
      await window.FiveEyesAPI.updates.install();
    }
  } catch(e) {
    console.warn('Update install failed:', e);
  }
}

// Subscribe to update state changes from Electron main process
if (window.desktop && typeof window.desktop.onUpdateStateChanged === 'function') {
  window.desktop.onUpdateStateChanged((state) => applyUpdateState(state));
}
// Also init update state on admin modal open
(async () => {
  if (window.FiveEyesAPI && window.FiveEyesAPI.updates) {
    try {
      const state = await window.FiveEyesAPI.updates.getState();
      applyUpdateState(state);
    } catch(e) {}
  }
})();
// ─────────────────────────────────────────────────────────────────────────────
async function initApp() {
  go('sd');
  initCharts();
  bindAllocationPreferenceControls();
  ensureFoundationExampleButton();
  await loadClients();
  setTimeout(refreshPricesFromBackend, 3000);
}
// ─────────────────────────────────────────────────────────────────────



// ─── LIVE PRICES (Yahoo Finance via allorigins proxy) ───
// ─── PRINT / PDF REPORT ───
// NAV
const pages={sd:0,rp:1,ub:2,al:3,po:4,rv:5,sr:6};
function go(p,b){
  Object.keys(pages).forEach(k=>{const el=document.getElementById('page-'+k);if(el)el.classList.remove('active');});
  const pg=document.getElementById('page-'+p);if(pg)pg.classList.add('active');
  const idx=pages[p];
  document.querySelectorAll('.tstep').forEach((s,i)=>{
    s.classList.remove('active','done');
    const sn=s.querySelector('.sn');
    if(i<idx){s.classList.add('done');if(sn)sn.textContent='✓';}
    else if(i===idx){s.classList.add('active');if(sn)sn.textContent=i+1;}
    else if(sn){sn.textContent=i+1;}
  });
  setTimeout(initCharts,80);
  if(p==='al')setTimeout(function(){refreshStrategyData(false,false);},120);
  if(p==='po'||p==='sr')setTimeout(function(){refreshStrategyData(false,true);},140);
}
function selC(el){document.querySelectorAll('.client').forEach(c=>c.classList.remove('active'));el.classList.add('active');}
let priv=false;
function toggleP(){priv=!priv;document.getElementById('sbl').classList.toggle('blurred',priv);document.getElementById('pb').textContent=priv?'Einblenden':'Ausblenden';}

// MODALS
function om(id){
  if(id&&prepareModalBeforeOpen(id)===false)return;
  const el=document.getElementById(id);
  if(el)el.classList.add('open');
}
function cm(id){
  const el=document.getElementById(id);
  if(el)el.classList.remove('open');
  if(id&&typeof cleanupModalAfterClose==='function')cleanupModalAfterClose(id);
}
document.querySelectorAll('.overlay').forEach(o=>o.addEventListener('click',function(e){if(e.target===this)this.classList.remove('open');}));

// Q / FP
function sq(el,g){
  el.closest('.qopts').querySelectorAll('.qopt').forEach(o=>o.classList.remove('sel'));
  el.classList.add('sel');
  // Live-Berechnung Risikoprofil nach jeder Antwort
  if(typeof calcRiskScore==='function') calcRiskScore();
}
function selFP(el){document.querySelectorAll('.fpv').forEach(v=>v.classList.remove('active'));el.classList.add('active');}

function isDemoClientId(id){
  var v=String(id||'');
  return !id||v.indexOf('local-')===0||v.indexOf('demo-')===0||v.indexOf('HH-')===0;
}
function isDemoMandateId(id){
  var v=String(id||'');
  return !id||v.indexOf('local-')===0||v.indexOf('demo-')===0;
}

// DELETE
function dcf(btn){
  var row=btn.closest('.cf-row'),cfId=row?row.dataset.cfid:null;
  var cid=getActiveClientId();
  var isDemo=isDemoClientId(cfId)||isDemoClientId(cid);
  if(!confirm(isDemo?'Eintrag entfernen (Demo)?':'Cashflow wirklich löschen?'))return;
  if(!isDemo){
    if(!cid){console.error('dcf DELETE skipped: no active client id');return;}
    API.del('/clients/'+cid+'/cashflows/'+cfId)
      .then(function(){refreshCashflowsUI(cid);markStrategyDirty('Cashflow gelöscht: Strategie neu berechnen.');})
      .catch(function(e){console.error('dcf DELETE failed:',e.status,e.message);});
  } else if(row) row.remove();
}
function dg(btn){
  var g=btn.closest('.goal'),gId=g?g.dataset.goalid:null;
  var mid=getActiveMandateId();
  var isDemo=isDemoClientId(gId)||isDemoMandateId(mid);
  if(!confirm(isDemo?'Ziel entfernen (Demo)?':'Ziel wirklich löschen?'))return;
  if(!isDemo){
    if(!mid){console.error('dg DELETE skipped: no active mandate id');return;}
    API.del('/mandates/'+mid+'/goals/'+gId)
      .then(function(){refreshGoalsUI(mid);markStrategyDirty('Ziel gelöscht: Strategie neu berechnen.');})
      .catch(function(e){console.error('dg DELETE failed:',e.status,e.message);});
  } else if(g){g.remove();renum();}
}

// DRAG GOALS
function setupDrag(){
  const list=document.getElementById('zl');if(!list)return;
  let drag=null;
  list.querySelectorAll('.goal').forEach(row=>{
    row.addEventListener('dragstart',function(){drag=this;this.style.opacity='0.4';});
    row.addEventListener('dragend',function(){this.style.opacity='1';});
    row.addEventListener('dragover',e=>e.preventDefault());
    row.addEventListener('drop',function(e){e.preventDefault();if(drag&&drag!==this){list.insertBefore(drag,this);renum();}});
  });
}
function renum(){
  document.querySelectorAll('#zl .goal').forEach((r,i)=>{
    const pd=r.querySelector('.pd');if(pd){pd.textContent=i+1;pd.className='pd '+(i<2?'p1':i<4?'p2':'p3');}
  });
}

// DATA
let alloc=[
  {n:'Liquiditätsreserve',c:'#166534',ist:5,soll:7,chf:142500},
  {n:'Aktien (global+CH)',c:'#1e4b8f',ist:53,soll:45,chf:1510500},
  {n:'Anleihen / Defensiv',c:'#78601a',ist:10,soll:15,chf:285000},
  {n:'Immobilien (ind.)',c:'#2c5080',ist:8,soll:8,chf:228000},
  {n:'Alternative / Gold',c:'#4a6080',ist:6,soll:6,chf:171000},
  {n:'Private Equity',c:'#5a2d8b',ist:6,soll:7,chf:171000},
  {n:'Externe Mandate',c:'#5a6878',ist:2,soll:2,chf:57000},
];
let TOTAL=2848000;
let quoten=[
  {n:'Liquiditätsreserve',c:'#166534',ist:5,min:5,ziel:7,max:10},
  {n:'Aktien Schweiz',c:'#1a1f2e',ist:18,min:10,ziel:15,max:25},
  {n:'Aktien Global',c:'#1e4b8f',ist:35,min:25,ziel:30,max:40},
  {n:'Obligationen CHF',c:'#78601a',ist:6,min:8,ziel:10,max:15},
  {n:'Obligationen Global',c:'#a08030',ist:4,min:3,ziel:5,max:8},
  {n:'Immobilien (ind.)',c:'#2c5080',ist:8,min:5,ziel:8,max:12},
  {n:'Alternative / Gold',c:'#4a6080',ist:6,min:3,ziel:6,max:10},
  {n:'Private Equity',c:'#5a2d8b',ist:6,min:0,ziel:7,max:15},
  {n:'Externe Mandate',c:'#5a6878',ist:2,min:0,ziel:2,max:5},
];
const budget=[
  {cat:'Wohnen',items:[{n:'Miete / Nebenkosten',m:0}]},
  {cat:'Familie',items:[{n:'Kinderbetreuung',m:0},{n:'Alimente',m:0}]},
  {cat:'Haushalt & Konsum',items:[{n:'Lebensmittel, Getränke',m:3800},{n:'Haushaltführung',m:500},{n:'Telefon, Handy',m:150},{n:'Internet, TV, Radio',m:120},{n:'Streaming',m:50},{n:'Bekleidung, Schuhe',m:400},{n:'Genussmittel',m:200}]},
  {cat:'Gesundheit',items:[{n:'Krankenkasse inkl. Zusatz',m:900},{n:'Arzt',m:100},{n:'Zahnarzt, Optiker',m:150},{n:'Wellness, Fitness',m:200}]},
  {cat:'Versicherungen',items:[{n:'Hausrat, Gebäude',m:80},{n:'Privathaftpflicht',m:30},{n:'Rechtsschutz',m:40},{n:'Reiseversicherung',m:20}]},
  {cat:'Mobilität',items:[{n:'Leasing Auto',m:800},{n:'MFZ-Versicherung',m:150},{n:'Service, Reparaturen',m:100},{n:'Treibstoff',m:200},{n:'ÖV, Abos',m:100}]},
  {cat:'Erholung & Hobbys',items:[{n:'Ferien, Ausflüge',m:1500},{n:'Restaurant, Kino',m:600},{n:'Sport, Bildung',m:300}]},
  {cat:'Steuern',items:[{n:'Steuern Kanton ZH',m:7917}]},
  {cat:'3. Säule',items:[{n:'Säule 3a',m:605},{n:'Säule 3b',m:0}]},
  {cat:'Verschiedenes',items:[{n:'Spenden, Geschenke',m:200},{n:'Kredite, Darlehen',m:1500}]},
];
let strategyState={allocation:null,recommendation:null,activeMandateId:null,lastGeneratedAt:0,loading:false,dirty:true,risk:null,buildingBlocks:[],marketRuntime:null};
var allocationSuballocExpanded={};
var currentPortfolioHoldingPositionId=null;

function buildBudget(){/* Stub: Budget-Seite entfernt. buildAT() ruft diese Funktion — kein Seiteneffekt. */}

function buildQT(id){
  ensureAllocationRuntimePanels();
  const t=document.getElementById(id);if(!t)return;
  const prefs=loadAllocationPreferences();
  const activeBands=prefs&&prefs.bands?prefs.bands:{};
  allocationBandBaseline={};
  t.innerHTML=`<div style="font-size:10px;color:var(--n6);line-height:1.6;background:var(--bg);border:1px solid var(--b1);border-radius:var(--r);padding:8px 10px;margin-bottom:8px">Manuelle Soll-Quoten sind eine Simulation ueber der aktuellen House-Matrix. Nur Abweichungen von der Engine-Basis werden als Overrides ans Backend gesendet.</div><div style="display:grid;grid-template-columns:8px 1fr 42px 62px 62px 62px;gap:0;padding-bottom:4px;border-bottom:2px solid var(--b2);margin-bottom:2px;"><div></div><div style="font-size:9px;font-weight:500;letter-spacing:0.05em;text-transform:uppercase;color:var(--n4);padding-left:6px">Asset-Klasse</div><div style="font-size:9px;font-weight:500;text-transform:uppercase;letter-spacing:0.05em;color:var(--n4);text-align:right">Ist</div><div style="font-size:9px;font-weight:500;text-transform:uppercase;letter-spacing:0.05em;color:var(--n4);text-align:right">Min</div><div style="font-size:9px;font-weight:500;text-transform:uppercase;letter-spacing:0.05em;color:var(--n4);text-align:right">Ziel</div><div style="font-size:9px;font-weight:500;text-transform:uppercase;letter-spacing:0.05em;color:var(--n4);text-align:right">Max</div></div>`+quoten.map(function(r,idx){
    var bucket=normalizeBandKey(r.key||r.n||('bucket_'+idx));
    var baseline={min_bps:Math.round(Number(r.min||0)*100),target_bps:Math.round(Number(r.ziel||0)*100),max_bps:Math.round(Number(r.max||0)*100)};
    allocationBandBaseline[bucket]=baseline;
    var override=normalizeBandOverrideEntry(activeBands[bucket])||{};
    var minimum=override.min_bps!=null?override.min_bps:baseline.min_bps;
    var target=override.target_bps!=null?override.target_bps:baseline.target_bps;
    var maximum=override.max_bps!=null?override.max_bps:baseline.max_bps;
    return `<div class="qtr"><div class="qtd" style="background:${r.c}"></div><div class="qtn">${r.n}</div><div class="qti">${r.ist}%</div><input class="qtinp" data-bucket="${bucket}" data-field="min_bps" value="${formatBandPercent(minimum)}"><input class="qtinp" data-bucket="${bucket}" data-field="target_bps" value="${formatBandPercent(target)}" style="border-color:var(--n6)"><input class="qtinp" data-bucket="${bucket}" data-field="max_bps" value="${formatBandPercent(maximum)}"></div>`;
  }).join('');
  t.querySelectorAll('.qtinp').forEach(function(input){
    input.addEventListener('input',function(){
      updateBandOverrideStatus(collectBandOverridesFromModal()||{});
      markStrategyDirty('Bandbreiten aktualisiert: Strategie neu berechnen.');
    });
    input.addEventListener('change',function(){
      persistAllocationPreferences();
    });
  });
  updateBandOverrideStatus(activeBands);
}
function applyAllocationBandOverrides(){
  persistAllocationPreferences();
  return refreshStrategyData(true,false);
}
function resetAllocationBandOverrides(){
  var prefs=mergeAllocationPreferences(buildDefaultAllocationPreferences(),loadAllocationPreferences());
  prefs.bands={};
  persistAllocationPreferences(prefs);
  buildQT('qt-modal');
  updateBandOverrideStatus({});
  markStrategyDirty('Individuelle Bandbreiten zurueckgesetzt: Strategie neu berechnen.');
}
function formatIsoLocal(value){
  if(!value)return 'Nicht verfuegbar';
  try{
    return new Date(value).toLocaleString('de-CH',{year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'});
  }catch(e){
    return String(value);
  }
}
function renderEngineRuntimePanels(result){
  ensureAllocationRuntimePanels();
  var engine=document.getElementById('aa-engine-grid');
  var rationale=document.getElementById('aa-engine-rationale');
  var market=document.getElementById('aa-market-runtime');
  var liveSummary=document.getElementById('aa-live-summary');
  var liveAssets=document.getElementById('aa-live-assets');
  var livePositions=document.getElementById('aa-live-positions');
  var simEvents=document.getElementById('aa-sim-events');
  var mcSummary=document.getElementById('aa-mc-summary');
  var mcGoals=document.getElementById('aa-mc-goals');
  var assumptions=document.getElementById('aa-assumption-table');
  var suballoc=document.getElementById('aa-suballoc-table');
  var blocks=document.getElementById('aa-block-reference');
  if(!engine||!rationale||!market||!liveSummary||!liveAssets||!livePositions||!simEvents||!mcSummary||!mcGoals||!assumptions||!suballoc||!blocks)return;
  if(!result){
    engine.innerHTML='';
    rationale.innerHTML='<div style="font-size:10px;color:var(--n4)">Noch keine Engine-Berechnung vorhanden.</div>';
    market.innerHTML='<div style="font-size:10px;color:var(--n4)">Marktdaten- und CMA-Status werden nach der ersten Berechnung angezeigt.</div>';
    liveSummary.innerHTML='<div style="font-size:10px;color:var(--n4)">Preisgetriebene Drift- und Rebalancing-Hinweise erscheinen mit dem ersten Live-Rezept.</div>';
    liveAssets.innerHTML='';
    livePositions.innerHTML='';
    simEvents.innerHTML='<div style="font-size:10px;color:var(--n4)">Simulation und Rebalancing-Ereignisse erscheinen nach der ersten Berechnung.</div>';
    mcSummary.innerHTML='<div style="font-size:10px;color:var(--n4)">Monte-Carlo-Bandbreiten werden nach der ersten Berechnung angezeigt.</div>';
    mcGoals.innerHTML='<div style="font-size:10px;color:var(--n4)">Zielpfade und Erfolgswahrscheinlichkeiten erscheinen nach der ersten Berechnung.</div>';
    assumptions.innerHTML='<div style="font-size:10px;color:var(--n4)">Noch keine Asset-Class-Annahmen berechnet.</div>';
    suballoc.innerHTML='<div style="font-size:10px;color:var(--n4)">Noch keine Subanlageklassen berechnet.</div>';
    blocks.innerHTML='<div style="font-size:10px;color:var(--n4)">Noch keine Building-Block-Referenz geladen.</div>';
    return;
  }
  var advisoryChf=Math.round(Number(result.advisory_wealth_rappen||0)/100);
  var totalChf=Math.round(Number(result.total_wealth_rappen||0)/100);
  var sim=simulationPayload(result);
  var mc=monteCarloPayload(result);
  var live=liveRebalancingPayload(result)||(strategyState.recommendation?liveRebalancingPayload(strategyState.recommendation):null);
  var rebalanceCount=sim&&Array.isArray(sim.rebalancing_events)?sim.rebalancing_events.length:0;
  var mcTargetP10=mc&&Array.isArray(mc.target_p10_series_rappen)&&mc.target_p10_series_rappen.length?mc.target_p10_series_rappen[mc.target_p10_series_rappen.length-1]:0;
  var mcTargetP50=mc&&Array.isArray(mc.target_p50_series_rappen)&&mc.target_p50_series_rappen.length?mc.target_p50_series_rappen[mc.target_p50_series_rappen.length-1]:0;
  var mcTargetP90=mc&&Array.isArray(mc.target_p90_series_rappen)&&mc.target_p90_series_rappen.length?mc.target_p90_series_rappen[mc.target_p90_series_rappen.length-1]:0;
  var cards=[
    {label:'House Matrix',value:(result.house_matrix_profile||'n/a')+' / Score '+String(result.score_bucket||'-'),sub:'Risikoprofil setzt das Maximalbudget'},
    {label:'Risk Budget',value:formatBpsPercent(result.risk_budget_bps||0),sub:'Gewichtete Risky Fraction erlaubt'},
    {label:'Risky Fraction',value:formatBpsPercent(result.risky_fraction_total_bps||0),sub:'Headroom '+formatBpsPercent(result.risky_fraction_headroom_bps||0)},
    {label:'Liquiditaetsbedarf',value:formatRappen(result.reserve_needed_rappen||0),sub:'Netto-Cashflow '+formatRappen(result.annual_net_cashflow_rappen||0)},
    {label:'Beratungsvermoegen',value:formatCompactCHF(advisoryChf),sub:totalChf?Math.round(advisoryChf/Math.max(1,totalChf)*100)+'% des Gesamtvermoegens':'Kein Gesamtvermoegen'},
    {label:'Rendite / Vol',value:((Number(result.expected_return_bps||0)/100).toFixed(2))+'% / '+((Number(result.expected_volatility_bps||0)/100).toFixed(2))+'%',sub:'7J-Projektion auf Advisory-Basis'},
    {label:'Aktiengewicht',value:formatBpsPercent((result.asset_class_risky_weights_bps||{}).equities||0),sub:'Hinterlegte Risky Fraction Aktien'},
    {label:'Rebalancing',value:rebalanceCount?String(rebalanceCount)+' Event(s)':'Im Band',sub:sim?('Modus '+String(sim.rebalance_mode||'bands')):'Noch keine Simulation'},
    {label:'Monte Carlo',value:mc?(String(mc.simulations||0)+' Pfade'):'n/a',sub:mc?('P50 '+((Number(mc.target_annualized_return_p50_bps||0)/100).toFixed(2))+'% p.a.'):'Noch keine Pfadsimulation'},
    {label:'Downside',value:mc?(String(mc.target_downside_probability_pct||0)+'%'):'n/a',sub:'Anteil Zielpfade unter Startwert'}
  ];
  engine.innerHTML=cards.map(function(card){
    return '<div style="background:var(--surface);border:1px solid var(--b1);border-radius:var(--r2);padding:10px 12px"><div style="font-size:9px;font-weight:600;letter-spacing:0.08em;text-transform:uppercase;color:var(--n4);margin-bottom:4px">'+escapeHtml(card.label)+'</div><div style="font-family:var(--f-d);font-size:18px;color:var(--n8)">'+escapeHtml(card.value)+'</div><div style="font-size:10px;color:var(--n5);margin-top:3px">'+escapeHtml(card.sub)+'</div></div>';
  }).join('');
  rationale.innerHTML=(result.reasoning||[]).slice(0,7).map(function(item){
    return '<div style="font-size:10px;color:var(--n6);line-height:1.6;padding:7px 9px;background:var(--bg);border:1px solid var(--b1);border-radius:var(--r)">- '+escapeHtml(item)+'</div>';
  }).join('')||'<div style="font-size:10px;color:var(--n4)">Keine Reasoning-Punkte vorhanden.</div>';
  var runtime=strategyState.marketRuntime&&strategyState.marketRuntime.prices?strategyState.marketRuntime.prices:null;
  var refresh=runtime&&runtime.last_refresh_summary?runtime.last_refresh_summary:null;
  var quality=runtime&&runtime.quality?runtime.quality:null;
  var marketItems=[
    'Kapitalmarktannahmen: '+(result.capital_market_assumption_set||'n/a')+' ('+(result.capital_market_source||'unbekannt')+')',
    runtime?('Preis-Scheduler: '+((runtime.scheduler_enabled&&runtime.scheduler_running)?'aktiv':'inaktiv')+' / Provider: '+String(runtime.provider||'n/a')+' / Naechster Lauf: '+(runtime.next_run_at?formatIsoLocal(runtime.next_run_at):'nicht geplant')):'Preis-Scheduler-Status nicht verfuegbar',
    refresh?('Letzter Preis-Refresh: '+formatIsoLocal(refresh.finished_at||refresh.started_at)+' / verarbeitet '+String(refresh.processed||0)+' / aktualisiert '+String((refresh.inserted||0)+(refresh.updated||0))+' / wiederverwendet '+String(refresh.reused_fresh||0)+' / Fehler '+String(refresh.failed||0)):'Noch kein Preis-Refresh protokolliert',
    'Wichtig: Live-Marktdaten dienen aktuell Bewertung, Drift und Rebalancing-Checks. Kapitalmarktannahmen bleiben in V1 manuell versioniert.'
  ];
  if(quality){
    marketItems.splice(2,0,
      'Preisqualitaet: fresh '+String(quality.fresh_products_count||0)+' / '+String(quality.active_products_count||0)+' ('+String(quality.fresh_coverage_pct||0)+'%) / stale '+String(quality.stale_products_count||0)+' / ohne Preis '+String(quality.missing_price_count||0),
      'Lookup-Qualitaet: direkt '+String(quality.direct_lookup_products_count||0)+' / proxy '+String(quality.proxy_lookup_products_count||0)+' / synthetisch '+String(quality.synthetic_lookup_products_count||0)+' / Luecken '+String(quality.mapping_gap_count||0)+(quality.latest_price_date?(' / Letztes Preisdatum '+String(quality.latest_price_date)):'')
    );
  }
  market.innerHTML=marketItems.map(function(item){
    return '<div style="font-size:10px;color:var(--n6);line-height:1.6;padding:7px 9px;background:var(--bg);border:1px solid var(--b1);border-radius:var(--r)">'+escapeHtml(item)+'</div>';
  }).join('');
  liveSummary.innerHTML=live
    ? [
      'Stand: '+String(live.as_of_date||'n/a')+' / Referenzanker '+String(live.reference_anchor_date||'n/a'),
      'Live-Marktwert '+formatRappen(live.live_total_value_rappen||0)+' / Turnover fuer Rueckfuehrung '+formatRappen(live.turnover_required_rappen||0),
      'Bandbrueche: '+((live.breached_asset_classes||[]).length?(live.breached_asset_classes||[]).map(assetDisplayName).join(', '):'keine'),
      'Methodik: '+String(live.methodology||'')
    ].map(function(item){
      return '<div style="font-size:10px;color:var(--n6);line-height:1.6;padding:7px 9px;background:var(--bg);border:1px solid var(--b1);border-radius:var(--r)">'+escapeHtml(item)+'</div>';
    }).join('')
    : '<div style="font-size:10px;color:var(--n4)">Noch kein live bewertetes Rezept verfuegbar. Die Drift-Logik aktiviert sich mit einer Produkt-Empfehlung und Preisen.</div>';
  liveAssets.innerHTML=renderLiveRebalancingBuckets(live);
  livePositions.innerHTML=renderLiveRebalancingPositions(live);
  assumptions.innerHTML=(result.asset_class_assumptions||[]).map(function(item){
    return '<div style="display:grid;grid-template-columns:1fr 56px 56px 56px 72px 72px;gap:8px;align-items:center;padding:7px 9px;background:var(--bg);border:1px solid var(--b1);border-radius:var(--r)"><div><div style="font-size:11px;font-weight:500;color:var(--n8)">'+escapeHtml(item.asset_class||'Asset-Klasse')+'</div><div style="font-size:9px;color:var(--n5);margin-top:3px">'+escapeHtml(item.liquidity_profile||'')+'</div></div><div style="font-size:10px;color:var(--n7);text-align:right">'+formatBpsPercent(item.current_weight_bps||0)+'</div><div style="font-size:10px;color:var(--n7);text-align:right">'+formatBpsPercent(item.target_weight_bps||0)+'</div><div style="font-size:10px;color:var(--n7);text-align:right">'+formatBpsPercent(item.risky_fraction_bps||0)+'</div><div style="font-size:10px;color:var(--n7);text-align:right">'+((Number(item.expected_return_bps||0)/100).toFixed(2))+'%</div><div style="font-size:10px;color:var(--n7);text-align:right">'+((Number(item.expected_volatility_bps||0)/100).toFixed(2))+'%</div></div>';
  }).join('')||'<div style="font-size:10px;color:var(--n4)">Noch keine Asset-Class-Annahmen berechnet.</div>';
  simEvents.innerHTML=sim&&Array.isArray(sim.rebalancing_events)&&sim.rebalancing_events.length
    ? sim.rebalancing_events.slice(0,4).map(function(item){
      var buckets=(item.breached_buckets||[]).length?(item.breached_buckets||[]).join(', '):'Kalender-Reset';
      return '<div style="font-size:10px;color:var(--n6);line-height:1.6;padding:7px 9px;background:var(--bg);border:1px solid var(--b1);border-radius:var(--r)"><strong>'+escapeHtml(item.year||'')+'</strong> · '+escapeHtml(buckets)+' · Turnover '+formatRappen(item.turnover_rappen||0)+'<div style="font-size:9px;color:var(--n5);margin-top:3px">'+escapeHtml(item.notes||'')+'</div></div>';
    }).join('')
    : ('<div style="font-size:10px;color:var(--n6);line-height:1.6;padding:7px 9px;background:var(--bg);border:1px solid var(--b1);border-radius:var(--r)">'
      +(sim?'Simulation bleibt ueber den gewaehlten Horizont innerhalb der Bandbreiten.':'Simulation wird nach der ersten Berechnung angezeigt.')
      +'</div>');
  mcSummary.innerHTML=mc
    ? [
      'Pfade: '+String(mc.simulations||0)+' / Seed '+String(mc.seed||'n/a')+' / Horizont '+String(mc.horizon_years||0)+' Jahre',
      'Terminalband Soll: P10 '+formatRappen(mcTargetP10)+' / P50 '+formatRappen(mcTargetP50)+' / P90 '+formatRappen(mcTargetP90),
      'P50-Rendite: '+((Number(mc.target_annualized_return_p50_bps||0)/100).toFixed(2))+'% p.a. / Downside '+String(mc.target_downside_probability_pct||0)+'%',
      '1J Risiko: VaR 95 '+formatRiskLossBps(mc.target_var_95_1y_bps)+' / CVaR 95 '+formatRiskLossBps(mc.target_cvar_95_1y_bps)+' / Verlust-Wkeit '+formatProbabilityPct(mc.target_loss_probability_1y_pct),
      'Max Drawdown: P50 '+formatRiskLossBps(mc.target_max_drawdown_p50_bps)+' / Stress P95 '+formatRiskLossBps(mc.target_max_drawdown_p95_bps),
      'Methodik: normalverteilte Jahresrenditen auf Basis der hinterlegten Rendite- und Volatilitaetsannahmen.'
    ].map(function(item){
      return '<div style="font-size:10px;color:var(--n6);line-height:1.6;padding:7px 9px;background:var(--bg);border:1px solid var(--b1);border-radius:var(--r)">'+escapeHtml(item)+'</div>';
    }).join('')
    : '<div style="font-size:10px;color:var(--n4)">Monte-Carlo-Bandbreiten werden nach der ersten Berechnung angezeigt.</div>';
  mcGoals.innerHTML=mc&&Array.isArray(mc.goal_summaries)&&mc.goal_summaries.length
    ? mc.goal_summaries.slice(0,4).map(function(item){
      var score=Number(item.score||0);
      var tone=score>=70?'var(--pos)':(score>=45?'var(--warn)':'var(--neg)');
      return '<div style="display:flex;justify-content:space-between;align-items:flex-start;gap:12px;padding:7px 9px;background:var(--bg);border:1px solid var(--b1);border-radius:var(--r)"><div><div style="font-size:11px;font-weight:500;color:var(--n8)">'+escapeHtml(item.label||'Ziel')+'</div><div style="font-size:9px;color:var(--n5);margin-top:3px">Pfaderfolg '+escapeHtml(String(item.success_rate_pct||0))+'% / P50 '+escapeHtml(formatRappen(item.projected_value_p50_rappen||0))+'</div></div><div style="text-align:right"><div style="font-size:10px;color:'+tone+';font-weight:600">'+escapeHtml(String(score))+'%</div><div style="font-size:9px;color:var(--n5);margin-top:3px">Funded '+escapeHtml(String(Math.round(Number(item.funded_ratio_p50||0)*100)))+'%</div></div></div>';
    }).join('')
    : '<div style="font-size:10px;color:var(--n4)">Keine Zielpfade berechnet.</div>';
  suballoc.innerHTML=renderSubAllocationGroups(result.sub_allocations||[]);
  var blockRows=Array.isArray(strategyState.buildingBlocks)?strategyState.buildingBlocks:[];
  blocks.innerHTML=blockRows.length?blockRows.map(function(item){
    return '<div style="display:grid;grid-template-columns:1fr 66px;gap:8px;align-items:center;padding:6px 8px;background:var(--bg);border:1px solid var(--b1);border-radius:var(--r)"><div><div style="font-size:10px;font-weight:500;color:var(--n8)">'+escapeHtml(item.asset_class||'')+' / '+escapeHtml(item.sub_asset_class||'')+'</div><div style="font-size:9px;color:var(--n5);margin-top:2px">'+escapeHtml(item.universe||'Standard')+'</div></div><div style="font-size:10px;color:var(--n7);text-align:right">'+formatBpsPercent(item.risky_fraction_bps||0)+'</div></div>';
  }).join(''):'<div style="font-size:10px;color:var(--n4)">Building-Block-Referenz noch nicht geladen.</div>';
}

function buildAT(){
  const t=document.getElementById('at');if(!t)return;
  t.innerHTML=alloc.map(r=>{
    const d=r.soll-r.ist;const dc=Math.abs(d)<=1?'dok':d<0?'dn':'dp';const sign=d>0?'+':'';const sc=Math.round(TOTAL*r.soll/100);
    return`<div class="ar"><div class="ad" style="background:${r.c}"></div><div class="an">${r.n}</div><div class="av">${r.ist}%</div><div style="font-size:11px;text-align:right;color:var(--n4)">CHF ${(r.chf/1000).toFixed(0)}k</div><div class="as">${r.soll}%</div><div style="font-size:11px;text-align:right;color:var(--n4)">CHF ${(sc/1000).toFixed(0)}k</div><div class="adl ${dc}">${sign}${d}%</div></div>`;
  }).join('');
  Array.prototype.forEach.call(grid.querySelectorAll('div[style*="text-align:center"] > button:first-of-type'),function(btn,idx){
    var doc=docs[idx];
    if(!doc)return;
    btn.textContent='Kapitel drucken';
    btn.setAttribute('onclick',"printDocumentTypeReport('"+String(doc.document_type||'Dokument').replace(/'/g,"\\'")+"')");
  });
}

function buildDLegend(){
  const el=document.getElementById('dnleg');if(!el)return;
  el.innerHTML=alloc.map(r=>`<div style="display:flex;align-items:center;justify-content:space-between;padding:2px 0;"><div style="display:flex;align-items:center;gap:4px;"><div style="width:6px;height:6px;border-radius:50%;background:${r.c};flex-shrink:0;"></div><span style="font-size:9px;color:var(--n6)">${r.n}</span></div><span style="font-size:9px;font-weight:500">${r.ist}%</span></div>`).join('');
}

let charts={};
function initCharts(){
  if (typeof Chart === 'undefined') { console.warn('Chart.js not loaded; charts remain disabled until vendor_assets.py is executed.'); return; }
  var startYear=(new Date()).getFullYear();
  const yr=Array.from({length:11},function(_,idx){return startYear+idx;});
  const startK=Math.max(1200,Math.round((Number(TOTAL||2848000))/1000));
  const ist=Array.from({length:11},function(_,idx){return Math.round(startK*Math.pow(1.03,idx));});
  const opt=Array.from({length:11},function(_,idx){return Math.round(startK*Math.pow(1.045,idx));});

  const cfg=(data,color,fill,compare)=>{const ds=[{label:'Prognose',data:data,borderColor:color,backgroundColor:color.replace(')',',0.07)').replace('rgb','rgba'),borderWidth:2,pointRadius:0,fill:fill,tension:0.4}];if(compare)ds.push({label:'IST',data:ist,borderColor:'rgba(146,64,14,0.5)',backgroundColor:'transparent',borderWidth:1.5,borderDash:[3,3],pointRadius:0,tension:0.4});return{type:'line',data:{labels:yr,datasets:ds},options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{display:!!compare,position:'top',labels:{font:{size:9},boxWidth:9,padding:7}}},scales:{x:{grid:{display:false},ticks:{font:{size:9},color:'#7a8299'}},y:{grid:{color:'rgba(0,0,0,0.04)'},ticks:{font:{size:9},color:'#7a8299',callback:v=>`${(v/1000).toFixed(1)}M`}}}}};};
  if(!charts.ist){const el=document.getElementById('ch-ist');if(el)charts.ist=new Chart(el.getContext('2d'),cfg(ist,'rgb(146,64,14)',true,false));}
  if(!charts.opt){const el=document.getElementById('ch-opt');if(el)charts.opt=new Chart(el.getContext('2d'),cfg(opt,'rgb(22,101,52)',true,true));}
  // ch-fp removed (page-fp removed)
  if(!charts.dn){
    const el=document.getElementById('ch-dn');
    if(el){charts.dn=new Chart(el.getContext('2d'),{type:'doughnut',data:{labels:alloc.map(r=>r.n),datasets:[{data:alloc.map(r=>r.ist),backgroundColor:alloc.map(r=>r.c),borderWidth:2,borderColor:'#fff'}]},options:{responsive:true,maintainAspectRatio:true,cutout:'68%',plugins:{legend:{display:false}}}});buildDLegend();}
  }
  ensureAllocationRuntimePanels();
  buildAT();buildQT('qt-modal');renderEngineRuntimePanels(null);buildBudget();setupDrag();
}

const PERSONAS = [{"id": "HH-001", "name": "Lukas Meier", "household": "Single", "age": 32, "profession": "Ingenieur", "region": "ZH", "currency": "CHF", "personaType": "Young Accumulator", "income": 125000, "fixedCosts": 32000, "varCosts": 26000, "surplus": 67000, "liquidity": 35000, "securities": 90000, "pension": 28000, "realEstate": 0, "businessValue": 0, "debts": 0, "netWorth": 153000, "horizon": 30, "riskProfile": "Moderat", "knowledge": "Mittel", "mainGoal": "Kapitalaufbau / Eigenheim", "event": "Kein Ereignis", "advisoryStyle": "Wachstum", "notes": "Hohe Cashquote, diszipliniert", "assets": [{"label": "Cash / Liquidität", "amount": 35000, "currency": "CHF", "category": "Liquidität", "notes": "Kurzfristige Reserve"}, {"label": "Börsenportfolio", "amount": 90000, "currency": "CHF", "category": "Wertschriften", "notes": "Heute frei investierbar"}, {"label": "Vorsorge (PK/3a/FZ)", "amount": 28000, "currency": "CHF", "category": "Vorsorge", "notes": "Gebunden bzw. teilgebunden"}], "liabilities": [], "cashflows": [{"type": "Income", "label": "Berufseinkommen", "amount": 125000, "currency": "CHF", "frequency": "jährlich", "nature": "wiederkehrend"}, {"type": "Expense", "label": "Fixkosten", "amount": 32000, "currency": "CHF", "frequency": "jährlich", "nature": "wiederkehrend"}, {"type": "Expense", "label": "Variable Ausgaben", "amount": 26000, "currency": "CHF", "frequency": "jährlich", "nature": "wiederkehrend"}, {"type": "Surplus", "label": "Verfügbarer Überschuss", "amount": 67000, "currency": "CHF", "frequency": "jährlich", "nature": "abgeleitet"}], "goals": [{"label": "Eigenheim / Eigenkapital", "target": 250000, "currency": "CHF", "horizon": 8, "priority": "hoch", "type": "einmalig"}, {"label": "Optionale Lifestyle-/Freiheitsziele", "target": 100000, "currency": "CHF", "horizon": 12, "priority": "mittel", "type": "einmalig"}], "preferences": {"riskProfile": "Moderat", "knowledge": "Mittel", "homeBias": "CH-Home-Bias", "esg": "ESG neutral", "themes": "Nur begrenzt", "event": "Kein Ereignis"}}, {"id": "HH-002", "name": "Sarah Keller", "household": "Single", "age": 38, "profession": "Juristin", "region": "BS", "currency": "CHF", "personaType": "Single High Earner", "income": 165000, "fixedCosts": 42000, "varCosts": 36000, "surplus": 87000, "liquidity": 80000, "securities": 250000, "pension": 70000, "realEstate": 0, "businessValue": 0, "debts": 0, "netWorth": 400000, "horizon": 25, "riskProfile": "Moderat", "knowledge": "Tief-Mittel", "mainGoal": "Vermögensaufbau", "event": "Kein Ereignis", "advisoryStyle": "Wachstum", "notes": "Wenig Erfahrung, hohe Sparrate", "assets": [{"label": "Cash / Liquidität", "amount": 80000, "currency": "CHF", "category": "Liquidität", "notes": "Kurzfristige Reserve"}, {"label": "Börsenportfolio", "amount": 250000, "currency": "CHF", "category": "Wertschriften", "notes": "Heute frei investierbar"}, {"label": "Vorsorge (PK/3a/FZ)", "amount": 70000, "currency": "CHF", "category": "Vorsorge", "notes": "Gebunden bzw. teilgebunden"}], "liabilities": [], "cashflows": [{"type": "Income", "label": "Berufseinkommen", "amount": 165000, "currency": "CHF", "frequency": "jährlich", "nature": "wiederkehrend"}, {"type": "Expense", "label": "Fixkosten", "amount": 42000, "currency": "CHF", "frequency": "jährlich", "nature": "wiederkehrend"}, {"type": "Expense", "label": "Variable Ausgaben", "amount": 36000, "currency": "CHF", "frequency": "jährlich", "nature": "wiederkehrend"}, {"type": "Surplus", "label": "Verfügbarer Überschuss", "amount": 87000, "currency": "CHF", "frequency": "jährlich", "nature": "abgeleitet"}], "goals": [{"label": "Langfristiges Vermögensziel", "target": 1500000, "currency": "CHF", "horizon": 25, "priority": "hoch", "type": "Bestand"}, {"label": "Optionale Lifestyle-/Freiheitsziele", "target": 100000, "currency": "CHF", "horizon": 12, "priority": "mittel", "type": "einmalig"}], "preferences": {"riskProfile": "Moderat", "knowledge": "Tief-Mittel", "homeBias": "CH-Home-Bias", "esg": "ESG neutral", "themes": "Nur begrenzt", "event": "Kein Ereignis"}}, {"id": "HH-003", "name": "Daniel & Laura Baumann", "household": "Family", "age": 41, "profession": "Arzt / Lehrerin", "region": "AG", "currency": "CHF", "personaType": "Family with Mortgage", "income": 210000, "fixedCosts": 72000, "varCosts": 48000, "surplus": 90000, "liquidity": 80000, "securities": 320000, "pension": 450000, "realEstate": 1200000, "businessValue": 0, "debts": 780000, "netWorth": 1270000, "horizon": 20, "riskProfile": "Moderat", "knowledge": "Mittel", "mainGoal": "Ausbildung Kinder", "event": "Kinder mit 8 und 10", "advisoryStyle": "Sicherheit + Wachstum", "notes": "Immobilienlastig", "assets": [{"label": "Cash / Liquidität", "amount": 80000, "currency": "CHF", "category": "Liquidität", "notes": "Kurzfristige Reserve"}, {"label": "Börsenportfolio", "amount": 320000, "currency": "CHF", "category": "Wertschriften", "notes": "Heute frei investierbar"}, {"label": "Vorsorge (PK/3a/FZ)", "amount": 450000, "currency": "CHF", "category": "Vorsorge", "notes": "Gebunden bzw. teilgebunden"}, {"label": "Immobilien", "amount": 1200000, "currency": "CHF", "category": "Immobilien", "notes": "Selbstgenutzt und/oder Anlageobjekt"}], "liabilities": [{"label": "Hypothek/Kredite", "amount": 780000, "currency": "CHF", "category": "Finanzierung"}], "cashflows": [{"type": "Income", "label": "Berufseinkommen", "amount": 210000, "currency": "CHF", "frequency": "jährlich", "nature": "wiederkehrend"}, {"type": "Expense", "label": "Fixkosten", "amount": 72000, "currency": "CHF", "frequency": "jährlich", "nature": "wiederkehrend"}, {"type": "Expense", "label": "Variable Ausgaben", "amount": 48000, "currency": "CHF", "frequency": "jährlich", "nature": "wiederkehrend"}, {"type": "Surplus", "label": "Verfügbarer Überschuss", "amount": 90000, "currency": "CHF", "frequency": "jährlich", "nature": "abgeleitet"}], "goals": [{"label": "Langfristiges Vermögensziel", "target": 2290000, "currency": "CHF", "horizon": 20, "priority": "hoch", "type": "Bestand"}, {"label": "Bildung / Familie / Flexibilitätsreserve", "target": 150000, "currency": "CHF", "horizon": 15, "priority": "mittel", "type": "einmalig"}], "preferences": {"riskProfile": "Moderat", "knowledge": "Mittel", "homeBias": "CH-Home-Bias", "esg": "ESG neutral", "themes": "Nur begrenzt", "event": "Kinder mit 8 und 10"}}];
let currentPersona = null;
var currentCashflows = [];
var currentGoals = [];
var currentCashflowEditId = null;
var currentGoalEditId = null;

function fmtCHF(n){if(n===null||n===undefined)return '–';return 'CHF '+Math.round(n).toLocaleString('de-CH');}

  function loadPersona(pid){
    const p=PERSONAS.find(x=>x.id===pid);
    if(!p)return;
    currentPersona=p;
    currentClientId=null;
    currentMandateId=p.mandate_id||null;
    strategyState={allocation:null,recommendation:null,activeMandateId:currentMandateId,lastGeneratedAt:0,loading:false,dirty:true,risk:null,buildingBlocks:[],marketRuntime:null};
    renderEngineRuntimePanels(null);
    currentWealthPositions=[];
    updateMortgageLinkedPropertyOptions('');
    document.querySelectorAll('.client').forEach(el=>el.classList.toggle('active',el.dataset.pid===pid));
  const phS=document.querySelector('#page-sd .ph-s');
  if(phS)phS.textContent=p.name+' · '+p.personaType+' · '+p.region;
  const hg=document.getElementById('hh-grid');
  if(hg)hg.innerHTML=`<div><div class="psk">Hauptperson</div><div class="psv">${p.name}, ${p.age} J.</div></div><div><div class="psk">Haushalt</div><div class="psv">${p.household}</div></div><div><div class="psk">Beruf</div><div class="psv">${p.profession}</div></div><div><div class="psk">Wohnsitz</div><div class="psv">${p.region}</div></div><div><div class="psk">Anlagehorizont</div><div class="psv">${p.horizon} Jahre</div></div><div><div class="psk">Beratungsstil</div><div class="psv">${p.advisoryStyle||'–'}</div></div><div><div class="psk">Persona-Typ</div><div class="psv">${p.personaType}</div></div><div><div class="psk">Ereignis</div><div class="psv">${p.event||'–'}</div></div>`;
  const av=document.getElementById('asset-view');
  if(av){
    const ber=p.assets.filter(a=>['Wertschriften','Liquidität'].includes(a.category));
    const and=p.assets.filter(a=>!['Wertschriften','Liquidität'].includes(a.category));
    const tBer=ber.reduce((s,a)=>s+(a.amount||0),0);
    av.innerHTML=`<div style="font-size:9px;font-weight:600;letter-spacing:0.08em;text-transform:uppercase;color:var(--n6);margin-bottom:5px;padding-bottom:3px;border-bottom:1px solid var(--b1)">Beratungsvermögen</div>${ber.map(a=>`<div class="wr"><div class="wn"><div class="wna">${a.label}</div><div class="wnd">${a.notes||a.category}</div></div><div class="wa">${fmtCHF(a.amount)}</div><div class="wt"><span class="tag tb">Beratung</span></div></div>`).join('')}<div style="display:flex;justify-content:space-between;align-items:center;padding:7px 0 0;border-top:1px solid var(--b2);margin-top:3px"><span style="font-size:11px;font-weight:600">Total Beratungsvermögen</span><span style="font-family:var(--f-d);font-size:16px;color:var(--pos)">${fmtCHF(tBer)}</span></div><div style="font-size:9px;font-weight:600;letter-spacing:0.08em;text-transform:uppercase;color:var(--n4);margin:10px 0 5px;padding-bottom:3px;border-bottom:1px solid var(--b1)">Anderes Vermögen</div>${and.map(a=>`<div class="wr"><div class="wn"><div class="wna">${a.label}</div><div class="wnd">${a.category}</div></div><div class="wa">${fmtCHF(a.amount)}</div><div class="wt"><span class="tag tn">Andere</span></div></div>`).join('')}${p.liabilities.map(l=>`<div class="wr"><div class="wn"><div class="wna">${l.label}</div><div class="wnd">${l.category}</div></div><div class="wa" style="color:var(--neg)">− ${fmtCHF(l.amount)}</div><div class="wt"><span class="tag tr2">Verbindl.</span></div></div>`).join('')}<div style="display:flex;justify-content:space-between;align-items:center;padding:10px 0 0;border-top:2px solid var(--n8);margin-top:7px"><span style="font-size:12px;font-weight:600;text-transform:uppercase;letter-spacing:0.04em">Reinvermögen Total</span><span style="font-family:var(--f-d);font-size:22px;color:var(--n8)">${fmtCHF(p.netWorth)}</span></div>`;
  }
  prependWealthSplitSummary({
    netChf:p.netWorth||0,
    grossChf:tBer+and.reduce((s,a)=>s+(a.amount||0),0),
    advisoryChf:tBer,
    otherGrossChf:and.reduce((s,a)=>s+(a.amount||0),0),
    liabilitiesChf:p.liabilities.reduce((s,l)=>s+(l.amount||0),0),
    advisoryCount:ber.length,
    otherCount:and.length,
    liabilityCount:p.liabilities.length
  });
  const kpis=document.querySelectorAll('.kpir .kpi');
  if(kpis.length>=5){
    kpis[0].querySelector('.kv').innerHTML=`<span style="font-family:var(--f-d)">${fmtCHF(p.netWorth)}</span>`;
    kpis[0].querySelector('.ks').textContent='Reinvermögen gesamt';
    kpis[1].querySelector('.kv').innerHTML=`<span style="font-family:var(--f-d)">${fmtCHF((p.securities||0)+(p.liquidity||0))}</span>`;
    kpis[1].querySelector('.ks').textContent='Beratungsvermögen';
    kpis[2].querySelector('.ks').textContent=p.mainGoal||'–';
    kpis[3].querySelector('.kv').innerHTML=`<span style="font-family:var(--f-d)">+${fmtCHF(p.surplus)}</span>`;
    kpis[4].querySelector('.ks').textContent='Horizont '+p.horizon+' J.';
  }
  const zf=document.getElementById('zufluss-rows');
  if(zf){
    const inc=p.cashflows.filter(c=>c.type==='Income');
    const totalIn=inc.reduce((s,c)=>s+(c.amount||0),0);
    const icos={'Berufseinkommen':'💼','Vermietung':'🏠','Kapitalerträge':'📈','Dividenden':'📈','Rente':'👴','AHV':'👴','Unternehmerlohn':'🏢','Freelance':'💻','Bonus':'⭐'};
    const getIco=l=>Object.entries(icos).find(([k])=>l.includes(k))||['','💰'];
    zf.innerHTML='<div class="cf-sec">Laufende Zuflüsse</div>'+inc.map(c=>'<div class="cf-row"><div class="cfi" style="background:var(--pos-lt)">'+getIco(c.label)[1]+'</div><div class="cfn"><div class="cfna">'+c.label+'</div><div class="cfnd">'+c.frequency+'</div></div><div class="cfa ci">+'+fmtCHF(c.amount)+'</div><div><button class="btn-ico e" onclick="om(\'m-acf\')">✎</button><button class="btn-ico" onclick="dcf(this)">✕</button></div></div>').join('')+'<div class="cft"><span style="font-size:11px;font-weight:600">Total Zuflüsse p.a.</span><span style="font-family:var(--f-d);font-size:17px;color:var(--pos)">+'+fmtCHF(totalIn)+'</span></div>';
  }
  const af=document.getElementById('abfluss-rows');
  if(af){
    const exp=p.cashflows.filter(c=>c.type==='Expense');
    const totalOut=exp.reduce((s,c)=>s+(c.amount||0),0);
    af.innerHTML='<div class="cf-sec">Laufende Ausgaben</div>'+exp.map(c=>'<div class="cf-row"><div class="cfi" style="background:var(--neg-lt)">📋</div><div class="cfn"><div class="cfna">'+c.label+'</div><div class="cfnd">'+c.frequency+' · '+c.nature+'</div></div><div class="cfa co">−'+fmtCHF(c.amount)+'</div><div><button class="btn-ico e" onclick="om(\'m-acf\')">✎</button><button class="btn-ico" onclick="dcf(this)">✕</button></div></div>').join('')+'<div class="cft"><div><div style="font-size:11px;font-weight:600">Netto-Cashflow p.a.</div></div><span style="font-family:var(--f-d);font-size:18px;color:var(--pos)">+'+fmtCHF(p.surplus)+'</span></div>';
  }
  const zl=document.getElementById('zl');
  if(zl){
    const pc={'hoch':'p1','mittel':'p2','tief':'p3','niedrig':'p3'};
    zl.innerHTML=p.goals.map((g,i)=>{
      const pct=Math.min(90,Math.round((p.netWorth/(g.target||1))*35+15));
      const gcl=pct>=70?'fg':pct>=45?'fa':'fr';
      const tcl=pct>=70?'tg':pct>=45?'ta':'tr2';
      const lbl=pct>=70?'On Track':pct>=45?'Prüfen':'Gefährdet';
      return '<div class="goal" draggable="true"><div class="pd '+(pc[g.priority]||'p2')+'">'+(i+1)+'</div><div class="gi"><div class="gn">'+g.label+'</div><div class="gd">'+fmtCHF(g.target)+' · '+g.horizon+' J. · '+g.type+'</div></div><span class="tag '+tcl+'">'+lbl+'</span><div class="gbw"><div class="gp">'+pct+' %</div><div class="gb"><div class="gf '+gcl+'" style="width:'+pct+'%"></div></div></div><div><button class="btn-ico e" onclick="om(\'m-nz\')">✎</button><button class="btn-ico" onclick="dg(this)">✕</button></div></div>';
    }).join('');
    setupDrag();
  }
  if(charts.ist){
    const base=(p.securities||0)+(p.liquidity||0);
    const ann=p.surplus||0;
    const r=p.riskProfile==='Wachstum'?0.052:p.riskProfile==='Konservativ'?0.028:0.042;
    charts.ist.data.datasets[0].data=[0,1,2,3,4,5,6,7,8,9,10].map(i=>Math.round((base*Math.pow(1+r,i)+ann*((Math.pow(1+r,i)-1)/r))/1000));
    charts.ist.update('none');
  }
  const rpM={'Konservativ':['Income – Kapitalerhalt','Kapitalerhalt, min. Risiko. Max. Aktienquote 25 %.'],'Moderat':['Balanced – Ausgewogen','Ausgewogen. Max. Aktienquote 40 %.'],'Wachstum':['Growth – Wachstum','Wachstumsorientiert. Max. Aktienquote 60 %.']};
  const rpR=rpM[p.riskProfile]||rpM['Moderat'];
  const rp_p=document.querySelector('.resbox .res-p');
  const rp_d=document.querySelector('.resbox .res-d');
  if(rp_p)rp_p.textContent=rpR[0];
  if(rp_d)rp_d.textContent=rpR[1];
  syncAllocationPreferences();
  renderDemoReviewUI();
  document.title='5eyes \u00b7 '+p.name;
}

async function fetchPrice(ticker){
  // Stub: direkte Preisabfragen wurden durch den Backend-Preisdienst ersetzt.
  // Preise werden serverseitig über POST /admin/prices/refresh aktualisiert.
  // loadLivePrices() ruft diese Funktion — beide sind aktuell inaktiv.
  return null;
}

async function loadLivePrices(){
  // Stub: live Preisabfragen sind deaktiviert (fetchPrice() gibt null zurück).
  // Wird nicht aufgerufen — bleibt als Platzhalter für spätere Backend-Integration.
}

function currentActivePageKey(){
  var active=document.querySelector('.page.active');
  return active&&active.id?String(active.id).replace(/^page-/,''):'sd';
}
function reportClientLabel(){
  var p=currentPersona||{};
  return p.name||[p.first_name||'',p.last_name||''].join(' ').trim()||'Mandant';
}
function normalizeReportPages(rawPages){
  var seen={};
  return (rawPages||[]).map(function(item){return String(item||'').trim();}).filter(function(key){
    return pages.hasOwnProperty(key)&&!seen[key]&&(seen[key]=true);
  });
}
function reportPagesForDocumentType(documentType){
  var raw=String(documentType||'').toLowerCase();
  if(raw.indexOf('strategie')>=0)return ['rp','ub','al'];
  if(raw.indexOf('rezept')>=0)return ['al','po','sr'];
  if(raw.indexOf('protokoll')>=0)return ['rv','sr'];
  if(raw.indexOf('risikoprofil')>=0)return ['rp'];
  return ['rv'];
}
function printDocumentTypeReport(documentType){
  printReport({pages:reportPagesForDocumentType(documentType)});
}
function collectReportPagesFromModal(){
  var checks=document.querySelectorAll('#m-rep input[type=checkbox]');
  if(!checks.length)return [currentActivePageKey()];
  var mapping=[
    ['sd'],
    ['rp'],
    ['ub'],
    ['ub','al'],
    ['po']
  ];
  var selected=[];
  Array.prototype.forEach.call(checks,function(check,idx){
    if(check&&check.checked&&mapping[idx])selected=selected.concat(mapping[idx]);
  });
  return normalizeReportPages(selected.length?selected:[currentActivePageKey()]);
}
function serializePrintablePage(pageKey){
  var page=document.getElementById('page-'+pageKey);
  if(!page)return '';
  var clone=page.cloneNode(true);
  clone.classList.remove('active');
  Array.prototype.forEach.call(clone.querySelectorAll('button,.cnav,.overlay,.mx,.topbar,.sb,.tsteps'),function(node){ node.remove(); });
  Array.prototype.forEach.call(clone.querySelectorAll('[onclick]'),function(node){ node.removeAttribute('onclick'); });
  Array.prototype.forEach.call(clone.querySelectorAll('canvas'),function(canvas){
    try{
      var img=document.createElement('img');
      img.src=canvas.toDataURL('image/png');
      img.style.maxWidth='100%';
      img.style.height='auto';
      canvas.parentNode.replaceChild(img,canvas);
    }catch(e){
      var ph=document.createElement('div');
      ph.style.cssText='border:1px dashed var(--b2);padding:12px;border-radius:var(--r);font-size:10px;color:var(--n5)';
      ph.textContent='Diagramm wird in der Print-Ansicht nicht direkt gerendert.';
      canvas.parentNode.replaceChild(ph,canvas);
    }
  });
  return clone.innerHTML;
}
function openPrintableReportWindow(pageKeys,title){
  var sections=normalizeReportPages(pageKeys).map(function(pageKey){
    var html=serializePrintablePage(pageKey);
    if(!html)return '';
    return '<section class="print-section">'+html+'</section>';
  }).filter(Boolean);
  if(!sections.length){
    window.print();
    return;
  }
  var styles=Array.prototype.map.call(document.querySelectorAll('style'),function(node){ return node.outerHTML; }).join('\n');
  var win=window.open('','_blank','noopener,noreferrer,width=1180,height=900');
  if(!win){
    window.print();
    return;
  }
  win.document.open();
  win.document.write('<!doctype html><html><head><meta charset=\"utf-8\"><title>'+escapeHtml(title)+'</title>'+styles+'<style>body{background:#fff;margin:0;padding:28px;font-family:var(--f-s,Arial,sans-serif);color:#111} .page{display:block!important;margin:0 auto 24px!important;max-width:1100px!important;box-shadow:none!important;background:#fff!important;border:none!important} .print-section{page-break-after:always} .print-section:last-child{page-break-after:auto} button,.cnav,.overlay,.mx,.topbar,.sb,.tsteps{display:none!important} .ph-r{display:none!important} .page *{box-shadow:none!important} @page{size:A4;margin:12mm}</style></head><body>'+sections.join('')+'</body></html>');
  win.document.close();
  setTimeout(function(){ try{ win.focus(); win.print(); }catch(e){} },350);
}
function printReport(options){
  var cfg=options||{};
  var pageKeys=normalizeReportPages(cfg.pages||((cfg.source==='modal'||(document.getElementById('m-rep')&&document.getElementById('m-rep').classList.contains('open')))?collectReportPagesFromModal():[currentActivePageKey()]));
  var title='5eyes Report - '+reportClientLabel()+' - '+new Date().toLocaleDateString('de-CH');
  openPrintableReportWindow(pageKeys,title);
}

function openPortfolioPositionHelper(){
  var recommendation=strategyState&&strategyState.recommendation;
  var positions=recommendation&&Array.isArray(recommendation.positions)?recommendation.positions:[];
  var empty=document.getElementById('ap-empty-state');
  var form=document.getElementById('ap-form-wrap');
  var save=document.getElementById('btn-ap-save');
  var del=document.getElementById('btn-ap-delete');
  var title=document.querySelector('#m-ap .mtitle');
  if(title)title.textContent='Bestand zu Empfehlungstitel';
  if(!positions.length||!(recommendation&&recommendation.run&&recommendation.run.id)){
    if(empty)empty.style.display='block';
    if(form)form.style.display='none';
    if(save)save.style.display='none';
    if(del)del.style.display='none';
    om('m-ap');
    return;
  }
  if(empty)empty.style.display='none';
  if(form)form.style.display='block';
  if(save)save.style.display='';
  openPortfolioHoldingModal(currentPortfolioHoldingPositionId||positions[0].id);
}

function portfolioRecommendationPositions(){
  return strategyState&&strategyState.recommendation&&Array.isArray(strategyState.recommendation.positions)
    ? strategyState.recommendation.positions
    : [];
}

function currentRecommendationRunId(){
  return strategyState&&strategyState.recommendation&&strategyState.recommendation.run
    ? String(strategyState.recommendation.run.id||'')
    : '';
}

function findRecommendationPosition(positionId){
  var positions=portfolioRecommendationPositions();
  return positions.find(function(item){return item&&String(item.id||'')===String(positionId||'');})||null;
}

function setPortfolioHoldingError(message){
  var box=document.getElementById('ap-error');
  if(!box)return;
  if(message){
    box.textContent=message;
    box.style.display='block';
  }else{
    box.textContent='';
    box.style.display='none';
  }
}

function syncPortfolioHoldingSelection(){
  var positionId=getInputValue('ap-position-id');
  var position=findRecommendationPosition(positionId);
  currentPortfolioHoldingPositionId=positionId||null;
  var basis=document.getElementById('ap-basis-note');
  var meta=document.getElementById('ap-product-meta');
  var del=document.getElementById('btn-ap-delete');
  if(!position){
    if(meta)meta.textContent='Keine Position gewählt.';
    if(basis)basis.textContent='Noch kein Bestand hinterlegt.';
    if(del)del.style.display='none';
    setInputValue('ap-depot-bank','');
    setInputValue('ap-custody-account','');
    setInputValue('ap-units','');
    setInputValue('ap-market-value','');
    setInputValue('ap-cost-price','');
    setInputValue('ap-as-of',new Date().toISOString().slice(0,10));
    setSelectValue('ap-source','manual');
    setInputValue('ap-notes','');
    return;
  }
  if(meta){
    meta.textContent=[
      position.product_name||'Produkt',
      position.sub_asset_class||position.asset_class||'',
      position.lookup_symbol?('Lookup '+position.lookup_symbol):''
    ].filter(Boolean).join(' · ');
  }
  if(basis){
    basis.textContent=position.holding_present
      ? ('Aktiv: '+String(position.valuation_basis||'actual_holding_units')
          +(position.holding_as_of_date?(' · Stand '+position.holding_as_of_date):'')
          +(position.holding_source?(' · '+position.holding_source):''))
      : 'Noch kein Bestand hinterlegt. Ohne Holding wird Drift weiter aus dem Rezept rekonstruiert.';
  }
  if(del)del.style.display=position.holding_present?'':'none';
  setInputValue('ap-depot-bank',position.holding_depot_bank||getInputValue('recipe-depot-bank')||'');
  setInputValue('ap-custody-account',position.holding_custody_account_number||'');
  setInputValue('ap-units',formatUnitsInput(position.holding_units_milli));
  setInputValue('ap-market-value',formatInputCHF(position.holding_market_value_rappen));
  setInputValue('ap-cost-price',formatInputCHF(position.holding_avg_cost_price_rappen));
  setInputValue('ap-as-of',position.holding_as_of_date||new Date().toISOString().slice(0,10));
  setSelectValue('ap-source',position.holding_source||'manual');
  setInputValue('ap-notes',position.holding_notes||'');
  setPortfolioHoldingError('');
}

function openPortfolioHoldingModal(positionId){
  var positions=portfolioRecommendationPositions();
  var empty=document.getElementById('ap-empty-state');
  var form=document.getElementById('ap-form-wrap');
  var save=document.getElementById('btn-ap-save');
  if(!positions.length){
    if(empty)empty.style.display='block';
    if(form)form.style.display='none';
    if(save)save.style.display='none';
    om('m-ap');
    return;
  }
  if(empty)empty.style.display='none';
  if(form)form.style.display='block';
  if(save)save.style.display='';
  var select=document.getElementById('ap-position-id');
  if(select){
    select.innerHTML=positions.map(function(item){
      var label=[item.product_name||'Produkt',item.sub_asset_class||item.asset_class||''].filter(Boolean).join(' · ');
      return '<option value="'+String(item.id||'')+'">'+escapeHtml(label)+'</option>';
    }).join('');
    select.value=String(positionId||positions[0].id||'');
  }
  syncPortfolioHoldingSelection();
  om('m-ap');
}

async function savePortfolioHolding(){
  var mid=currentMandateId;
  var runId=currentRecommendationRunId();
  var positionId=getInputValue('ap-position-id');
  if(!mid||!runId||!positionId){
    setPortfolioHoldingError('Bitte zuerst ein aktuelles Rezept laden.');
    return;
  }
  var unitsMilli=parseUnitsMilli(getInputValue('ap-units'));
  var marketValueRappen=parseCHF(getInputValue('ap-market-value'));
  if(!(unitsMilli>0)&&!(marketValueRappen>0)){
    setPortfolioHoldingError('Bitte Bestand in Stück oder einen Bestandsmarktwert erfassen.');
    return;
  }
  var btn=document.getElementById('btn-ap-save');
  if(btn){btn.disabled=true;btn._origText=btn.textContent;btn.textContent='Speichert…';}
  setPortfolioHoldingError('');
  try{
    await API.put('/mandates/'+mid+'/recommendations/'+runId+'/positions/'+positionId+'/holding',{
      depot_bank:getInputValue('ap-depot-bank').trim()||null,
      custody_account_number:getInputValue('ap-custody-account').trim()||null,
      as_of_date:getInputValue('ap-as-of')||null,
      units_milli:unitsMilli>0?unitsMilli:null,
      market_value_rappen:marketValueRappen>0?marketValueRappen:null,
      avg_cost_price_rappen:parseCHF(getInputValue('ap-cost-price'))>0?parseCHF(getInputValue('ap-cost-price')):null,
      source:getInputValue('ap-source')||'manual',
      notes:getInputValue('ap-notes').trim()||null
    });
    cm('m-ap');
    await refreshStrategyData(true,true);
    updateStrategyStatus('Bestand gespeichert und Live-Drift neu bewertet.',false);
  }catch(e){
    setPortfolioHoldingError(parseApiError(e,'Bestand konnte nicht gespeichert werden.'));
  }finally{
    if(btn){btn.disabled=false;btn.textContent=btn._origText||'Speichern';}
  }
}

async function deletePortfolioHolding(){
  var mid=currentMandateId;
  var runId=currentRecommendationRunId();
  var positionId=getInputValue('ap-position-id');
  if(!mid||!runId||!positionId){
    setPortfolioHoldingError('Kein Bestand zum Löschen ausgewählt.');
    return;
  }
  var btn=document.getElementById('btn-ap-delete');
  if(btn){btn.disabled=true;btn._origText=btn.textContent;btn.textContent='Löscht…';}
  setPortfolioHoldingError('');
  try{
    await API.del('/mandates/'+mid+'/recommendations/'+runId+'/positions/'+positionId+'/holding');
    cm('m-ap');
    await refreshStrategyData(true,true);
    updateStrategyStatus('Bestand entfernt. Live-Drift nutzt wieder die Rezept-Rekonstruktion.',false);
  }catch(e){
    setPortfolioHoldingError(parseApiError(e,'Bestand konnte nicht gelöscht werden.'));
  }finally{
    if(btn){btn.disabled=false;btn.textContent=btn._origText||'Bestand löschen';}
  }
}

function bindHonestUiActions(){
  var portfolioBtn=document.querySelector('#page-po .ph-r .btn');
  if(portfolioBtn)portfolioBtn.setAttribute('onclick','openPortfolioPositionHelper()');
  var reportBtn=document.querySelector('#m-rep .mfooter .btn-p');
  if(reportBtn){
    reportBtn.textContent='Drucken / PDF öffnen';
    reportBtn.setAttribute('onclick',"cm('m-rep');printReport({source:'modal'})");
  }
  var reportBody=document.querySelector('#m-rep .mbody');
  if(reportBody && !document.getElementById('report-honesty-note')){
    reportBody.insertAdjacentHTML('afterbegin','<div id="report-honesty-note" style="background:var(--warn-lt);border:1px solid rgba(150,98,0,0.16);border-radius:var(--r);padding:8px 10px;margin-bottom:10px;font-size:10px;line-height:1.6;color:var(--n7)">Aktuell wird die laufende App-Ansicht gedruckt bzw. als PDF über den System-Dialog gespeichert. Inhalts- und Formatwahl sind noch keine separate Report-Engine.</div>');
  }
  var riskPdfBtn=document.querySelector('#m-rp-print .mfooter .btn-p');
  if(riskPdfBtn){
    riskPdfBtn.textContent='Drucken / PDF öffnen';
    riskPdfBtn.setAttribute('onclick',"cm('m-rp-print');printReport({pages:['rp']})");
  }
  var riskPdfBody=document.querySelector('#m-rp-print .mbody');
  if(riskPdfBody){
    riskPdfBody.innerHTML='<div style="font-size:11px;color:var(--n6);line-height:1.7">Die aktuelle Risikoprofil-Seite wird über den System-Druckdialog ausgegeben. Ein separates FINMA-PDF-Layout ist in dieser Version noch nicht hinterlegt.</div>';
  }
  var rvHeaderPrint=document.querySelector('#page-rv .ph-r .btn-g');
  if(rvHeaderPrint)rvHeaderPrint.setAttribute('onclick',"printReport({pages:['rv']})");
  var rvFooterPrint=document.querySelector('#page-rv .cnav .btn-g');
  if(rvFooterPrint)rvFooterPrint.setAttribute('onclick',"printReport({pages:['rv']})");
  var srHeaderPrint=document.querySelector('#page-sr .ph-r .btn');
  if(srHeaderPrint)srHeaderPrint.setAttribute('onclick',"printReport({pages:['sr']})");
  var srFooterPrint=document.querySelector('#page-sr .cnav .btn-g');
  if(srFooterPrint)srFooterPrint.setAttribute('onclick',"printReport({pages:['sr']})");
  var summaryRecipePrint=document.querySelector('#page-sr .btn-g');
  if(summaryRecipePrint)summaryRecipePrint.setAttribute('onclick',"printReport({pages:['al','po','rv','sr']})");
  var docCards=document.querySelectorAll('#rv-doc-grid > div');
  if(docCards[0]){
    var contractBtn=docCards[0].querySelector('button');
    if(contractBtn)contractBtn.setAttribute('onclick',"printReport({pages:['rv']})");
  }
  if(docCards[1]){
    var strategyBtn=docCards[1].querySelector('button');
    if(strategyBtn)strategyBtn.setAttribute('onclick',"printReport({pages:['rp','ub','al']})");
  }
  if(docCards[2]){
    var recipeDocBtn=docCards[2].querySelector('button');
    if(recipeDocBtn)recipeDocBtn.setAttribute('onclick',"printReport({pages:['al','po','sr']})");
  }
  if(docCards[3]){
    var logBtn=docCards[3].querySelector('button');
    if(logBtn)logBtn.setAttribute('onclick',"printReport({pages:['rv','sr']})");
  }
  var recipeBtn=document.querySelector('#m-ums .mfooter .btn-p');
  if(recipeBtn)recipeBtn.textContent='Finalisieren & drucken';
  ensureWealthEditorDeleteButton();
}

document.addEventListener('DOMContentLoaded', async () => {
  bindHonestUiActions();
  bindLegacyReviewModalActions();
  const existingToken = await API.getToken();
  if (existingToken) {
    try {
      const me = await API.get('/auth/me');
      currentUser = me;
      bootstrapStatusCache = { setup_required: false, can_create_admin: false };
      hideLogin();
      await initApp();
      return;
    } catch(e) {
      await API.setToken(null);
    }
  }

  const status = await checkBootstrapStatus();
  if (status && status.setup_required) showBootstrap();
  else showLogin(status && status.backend_unreachable ? 'Backend nicht erreichbar. Bitte App neu starten.' : '');
});

// RISK TABS
function switchRTab(btn, panelId) {
  setTimeout(function(){if(typeof calcRiskScore==='function')calcRiskScore();},50);
  document.querySelectorAll('.rtab').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('.rpanel').forEach(p => p.classList.remove('active'));
  btn.classList.add('active');
  const p = document.getElementById(panelId);
  if (p) p.classList.add('active');
}

// INDEXIERUNG ABFLÜSSE
const baseAmounts = {
  'a-lhk': 180000, 'a-st': 95000, 'a-bvg': 35000,
  'a-hyp': 18000,  'a-3a': 7000
};
function fmt(n) {
  return '−CHF ' + Math.round(n).toLocaleString('de-CH');
}
function toggleIndexierung(on) {
  document.querySelectorAll('.idx-col').forEach(el => {
    el.style.display = on ? 'flex' : 'none';
  });
  if (!on) {
    // Reset to base amounts
    Object.keys(baseAmounts).forEach(id => {
      const el = document.getElementById(id);
      if (el) el.textContent = fmt(baseAmounts[id]);
    });
  } else {
    recalcIdx();
  }
}
function recalcIdx() {
  const horizon = 10; // Jahre
  const ids  = Object.keys(baseAmounts);
  const inps = document.querySelectorAll('.idx-inp');
  ids.forEach((id, i) => {
    const pct  = parseFloat(inps[i]?.value || 0) / 100;
    const proj = baseAmounts[id] * Math.pow(1 + pct, horizon);
    const el = document.getElementById(id);
    if (el) {
      const diff = proj - baseAmounts[id];
      el.innerHTML = fmt(proj) +
        (diff > 0 ? '<span style="font-size:9px;color:var(--warn);margin-left:4px">(+' +
          Math.round(diff).toLocaleString('de-CH') + ' in ' + horizon + ' J.)</span>' : '');
    }
  });
}
function downloadEventCalendarFile(eventType,eventDate,details){
  var iso=String(eventDate||new Date().toISOString().slice(0,10));
  var stamp=iso.replace(/-/g,'');
  var text=String(details||'').trim()||'Ereignis-Trigger ausgeloest. Bitte Review-Gespraech planen.';
  var ics='BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//5Eyes WealthArchitekten//DE\r\nBEGIN:VEVENT\r\nUID:'+stamp+'-5eyes@wealtharchitekten.ch\r\nDTSTAMP:'+stamp+'T080000Z\r\nDTSTART:'+stamp+'T090000Z\r\nDTEND:'+stamp+'T100000Z\r\nSUMMARY:5Eyes Review: '+eventType+'\r\nDESCRIPTION:'+text.replace(/\n/g,' ')+'\r\nCATEGORIES:5Eyes,Review,Compliance\r\nPRIORITY:1\r\nEND:VEVENT\r\nEND:VCALENDAR';
  var blob=new Blob([ics],{type:'text/calendar;charset=utf-8'});
  var a=document.createElement('a');
  a.href=URL.createObjectURL(blob);
  a.download='5eyes_trigger_'+stamp+'.ics';
  a.click();
  setTimeout(function(){URL.revokeObjectURL(a.href);},250);
}
async function runtimeProtokolliereEreignis(){
  var btn=document.getElementById('btn-ev-save');
  var mid=getActiveMandateId();
  var typVal=getInputValue('ev-type')||'Anderes Ereignis';
  var eventDate=getInputValue('ev-date')||new Date().toISOString().slice(0,10);
  var details=getInputValue('ev-details').trim();
  var action=getInputValue('ev-action')||'review';
  var wantsCalendar=!!(document.getElementById('ev-calendar')&&document.getElementById('ev-calendar').checked);
  var createTrigger=action!=='document';
  var triggerId=null;
  var actionLabel=action==='risk'?'Risikoprofil neu pruefen':(action==='goals'?'Ziele anpassen':(action==='document'?'Nur dokumentieren - kein Handlungsbedarf':'Review-Termin ausloesen'));
  var notes=joinNotes([details,'Massnahme: '+actionLabel]);
  var logPayload={
    entry_type:/ziel/i.test(typVal)?'Zielaenderung':'Ereignis-Reaktion',
    title:'Ereignis: '+typVal,
    description:notes||null,
    decision:action==='document'?'Kein Handlungsbedarf':null,
    entry_date:eventDate
  };
  var triggerPayload={
    trigger_type:'Ereignis',
    trigger_name:typVal,
    frequency:'bei Ereignis',
    next_due_at:eventDate
  };
  if(!typVal){showModalFeedback('ev-error',btn,'Bitte Ereignis auswaehlen.',true);return;}
  if(btn){btn.disabled=true;btn.textContent='Protokolliert...';}
  if(mid&&!isDemoMandateId(mid)){
    try{
      if(createTrigger){
        var triggerResult=await API.post('/mandates/'+mid+'/triggers',triggerPayload);
        triggerId=triggerResult&&triggerResult.id?triggerResult.id:null;
      }
      if(triggerId)logPayload.trigger_id=triggerId;
      await API.post('/mandates/'+mid+'/advisory-log',logPayload);
      if(wantsCalendar&&action==='review')downloadEventCalendarFile(typVal,eventDate,details);
      showModalFeedback('ev-error',btn,'✓ Ereignis im Review-Funnel erfasst',false);
      await refreshReviewUI(mid);
      setTimeout(function(){
        cm('m-ev');
        if(action==='risk')go('rp');
        if(action==='goals')go('uz');
      },500);
    }catch(e){
      showModalFeedback('ev-error',btn,'Fehler: '+(e.detail||e.message||'?'),true);
    }
  } else {
    if(createTrigger){
      triggerId='demo-event-trigger-'+Date.now();
      currentReviewState.triggers=[{
        id:triggerId,
        trigger_type:'Ereignis',
        trigger_name:typVal,
        frequency:'bei Ereignis',
        status:'Aktiv',
        next_due_at:eventDate,
        triggered_notes:notes||null
      }].concat(currentReviewState.triggers||[]);
    }
    currentReviewState.logs=[Object.assign({id:'demo-log-'+Date.now(),trigger_id:triggerId},logPayload)].concat(currentReviewState.logs||[]);
    renderReviewState(currentReviewState);
    if(wantsCalendar&&action==='review')downloadEventCalendarFile(typVal,eventDate,details);
    showModalFeedback('ev-error',btn,'✓ Demo-Modus: Ereignis erfasst',false);
    setTimeout(function(){
      cm('m-ev');
      if(action==='risk')go('rp');
      if(action==='goals')go('uz');
    },700);
  }
}
protokolliereEreignis=runtimeProtokolliereEreignis;


// Subclass total calculator
function calcSCTotal(){
  var t=0;
  ['sc-akt','sc-obl','sc-imm','sc-liq','sc-alt'].forEach(function(id){
    var el=document.getElementById(id); if(el)t+=parseFloat(el.value||0);
  });
  var d=document.getElementById('sc-tot');
  if(d){d.textContent='Total: '+Math.round(t)+'%';d.style.color=Math.abs(t-100)<0.5?'var(--pos)':t>100?'var(--neg)':'var(--n6)';}
}
// Override modal
var _pnames=['','Kapitalschutz','Kapitalschutz','Defensiv','Defensiv','Ausgewogen','Ausgewogen','Wachstumsorientiert','Wachstumsorientiert','Dynamisch','Aktien'];
function updOv(v){
  var d=document.getElementById('ov-disp');var n=document.getElementById('ov-name');
  if(d)d.textContent=v+'/10'; if(n)n.textContent=_pnames[parseInt(v)]||'';
}
function applyOv(){
  var v=(document.getElementById('ov-sl')||{value:7}).value;
  var n=_pnames[parseInt(v)];
  var b=document.getElementById('overr-badge');
  var ov=document.getElementById('overr-val');
  var rp=document.getElementById('res-pname');
  if(b)b.style.display='block';
  if(ov)ov.textContent=v+'/10 – '+n;
  if(rp)rp.textContent=n+' – Override '+v+'/10';
  cm('m-overr');
}
// Init: hide subclass section
/* sc-wrap: DOM-Element entfernt, Handler gelöscht */


function addCustomRestr(){
  // Hinweis: #custom-restr-input existiert aktuell nicht im DOM. Null-Guard schützt vor Fehler.
  var inp=document.getElementById('custom-restr-input');
  if(!inp||!inp.value.trim())return;
  var container=inp.parentElement.previousElementSibling;
  var span=document.createElement('span');
  span.className='rtag rtag-on';
  span.textContent='✓ '+inp.value.trim();
  span.onclick=function(){this.classList.toggle('rtag-on');};
  container.appendChild(span);
  inp.value='';
}
function calcEDTotal(){
  var ids=['ed-akt','ed-obl','ed-imm','ed-liq','ed-alt'];
  var t=0; ids.forEach(function(id){var el=document.getElementById(id);if(el)t+=parseFloat(el.value||0);});
  var d=document.getElementById('ed-tot');
  if(d){d.textContent='Total: '+Math.round(t)+'%';d.style.color=Math.abs(t-100)<0.5?'var(--pos)':t>100?'var(--neg)':'var(--n6)';}
}


function switchSbTab(t){
  var tabs=['m','r'];
  tabs.forEach(function(x){
    var tab=document.getElementById('tab-'+x);
    var panel=document.getElementById('sb-tab-'+x);
    if(tab&&panel){
      var active=x===t;
      tab.style.background=active?'rgba(201,168,76,0.15)':'none';
      tab.style.borderBottomColor=active?'var(--g4)':'transparent';
      tab.style.color=active?'var(--g3)':'rgba(255,255,255,0.35)';
      panel.style.display=active?'block':'none';
    }
  });
}
function protokolliereEreignis(){
  var typ=document.querySelector('#m-ev select');
  var datum=document.querySelector('#m-ev input[type=date]');
  var typVal=typ?typ.value:'Ereignis';
  var datVal=datum?datum.value.replace(/-/g,''):new Date().toISOString().slice(0,10).replace(/-/g,'');
  // Generate .ics file
  var ics='BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//5Eyes WealthArchitekten//DE\r\nBEGIN:VEVENT\r\nUID:'+datVal+'-5eyes@wealtharchitekten.ch\r\nDTSTAMP:'+datVal+'T080000Z\r\nDTSTART:'+datVal+'T090000Z\r\nDTEND:'+datVal+'T100000Z\r\nSUMMARY:5Eyes Review: '+typVal+'\r\nDESCRIPTION:Ereignis-Trigger ausgeloest. Bitte Review-Gespraesch planen.\r\nCATEGORIES:5Eyes,Review,Compliance\r\nPRIORITY:1\r\nEND:VEVENT\r\nEND:VCALENDAR';
  var blob=new Blob([ics],{type:'text/calendar;charset=utf-8'});
  var a=document.createElement('a');
  a.href=URL.createObjectURL(blob);
  a.download='5eyes_trigger_'+datVal+'.ics';
  a.click();
  cm('m-ev');
  console.log('Ereignis protokolliert. Kalender-Export (.ics) heruntergeladen – in Outlook öffnen zum Importieren.');
}


  function showAwFields(val) {
    var sections = ['Depot','Liquiditaet','Immobilien','Vorsorge','Alternative','Hypothek'];
    sections.forEach(function(s) {
      var el = document.getElementById('aw-' + s);
      if (el) el.style.display = (s === val) ? 'block' : 'none';
  });
  // Auto-set Zuordnung type
    var typ = document.getElementById('maw-typ');
    if (!typ) return;
    if (val === 'Hypothek') {
      typ.value = 'Verbindlichkeit';
      updateMortgageLinkedPropertyOptions();
    } else if (val === 'Depot' || val === 'Liquiditaet') {
      typ.value = 'Beratungsvermögen';
    } else {
      typ.value = 'Anderes Vermögen';
    }
}

// ─── ADMIN TOOLS ──────────────────────────────────────────────────────
function showAdminResult(msg, isError) {
  const el = document.getElementById('admin-result');
  if (!el) return;
  el.style.display = 'block';
  el.style.color = isError ? 'var(--neg)' : 'var(--g4)';
  el.textContent = msg;
}

async function adminBackup() {
  const btn = document.getElementById('btn-admin-backup');
  if (btn) { btn.disabled = true; btn.textContent = 'Läuft…'; }
  try {
    const r = await API.post('/admin/system/db/backup', {});
    showAdminResult('✓ Backup erstellt:\n' + (r.backup_file||'') + '\nSHA256: ' + (r.sha256||'').slice(0,16) + '…', false);
  } catch(e) {
    showAdminResult('✗ ' + (e.message||e), true);
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = 'Backup erstellen'; }
  }
}

async function adminIntegrity() {
  const btn = document.getElementById('btn-admin-integrity');
  if (btn) { btn.disabled = true; btn.textContent = 'Prüft…'; }
  try {
    const r = await API.get('/admin/system/db/integrity');
    const ok = r.status === 'ok';
    showAdminResult((ok ? '✓ ' : '⚠ ') + 'Quick: ' + r.quick_check + '\nIntegrity: ' + (r.integrity_check||[]).join(', '), !ok);
  } catch(e) {
    showAdminResult('✗ ' + (e.message||e), true);
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = 'Integrity Check'; }
  }
}

async function adminOptimize() {
  const btn = document.getElementById('btn-admin-optimize');
  if (btn) { btn.disabled = true; btn.textContent = 'Optimiert…'; }
  try {
    const r = await API.post('/admin/system/db/optimize', {});
    showAdminResult('✓ Optimiert um ' + (r.optimized_at||''), false);
  } catch(e) {
    showAdminResult('✗ ' + (e.message||e), true);
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = 'DB Optimieren'; }
  }
}

async function adminLogs() {
  try {
    const r = await API.get('/admin/system/logs/recent?lines=50');
    const lines = (r.lines||[]).slice(-20).join('\n');
    showAdminResult(lines || '(keine Logs)', false);
  } catch(e) {
    showAdminResult('✗ ' + (e.message||e), true);
  }
}

async function adminSupportBundle() {
  const btn = document.getElementById('btn-admin-support');
  if (btn) { btn.disabled = true; btn.textContent = 'Erstellt…'; }
  try {
    const r = await API.post('/admin/system/support-bundle', {});
    showAdminResult('✓ Support-Bundle erstellt\n' + (r.bundle_file||'') + '\nSHA256: ' + (r.sha256||'').slice(0,16) + '…', false);
  } catch(e) {
    showAdminResult('✗ ' + (e.message||e), true);
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = 'Support-Bundle'; }
  }
}

async function adminUpdateStatus() {
  try {
    const state = window.FiveEyesAPI && window.FiveEyesAPI.updates ? await window.FiveEyesAPI.updates.getState() : { enabled:false };
    const lines = [
      'Auto-Update aktiv: ' + (state.enabled ? 'Ja' : 'Nein'),
      'Prüfung läuft: ' + (state.checking ? 'Ja' : 'Nein'),
      'Aktuelle Version: ' + (state.currentVersion || 'n/a'),
      'Neueste Version: ' + (state.latestVersion || 'n/a'),
      'Update verfügbar: ' + (state.available ? 'Ja' : 'Nein'),
      'Update heruntergeladen: ' + (state.downloaded ? 'Ja' : 'Nein'),
    ];
    if (state.error) lines.push('Fehler: ' + state.error);
    showAdminResult(lines.join('\n'), false);
  } catch(e) {
    showAdminResult('✗ ' + (e.message||e), true);
  }
}

async function adminCheckForUpdates() {
  const btn = document.getElementById('btn-admin-update-check');
  if (btn) { btn.disabled = true; btn.textContent = 'Prüft…'; }
  try {
    if (window.FiveEyesAPI && window.FiveEyesAPI.updates) {
      await window.FiveEyesAPI.updates.check();
      await adminUpdateStatus();
    } else {
      showAdminResult('Auto-Update ist in diesem Modus nicht verfügbar.', true);
    }
  } catch(e) {
    showAdminResult('✗ ' + (e.message||e), true);
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = 'Nach Updates suchen'; }
  }
}

async function adminInstallDownloadedUpdate() {
  const btn = document.getElementById('btn-admin-update-install');
  if (btn) { btn.disabled = true; btn.textContent = 'Installiert…'; }
  try {
    if (window.FiveEyesAPI && window.FiveEyesAPI.updates) {
      const result = await window.FiveEyesAPI.updates.install();
      if (result && result.ok) showAdminResult('Update-Installation wird gestartet. Die App beendet sich gleich.', false);
      else showAdminResult(result && result.message ? result.message : 'Kein heruntergeladenes Update verfügbar.', true);
    } else {
      showAdminResult('Auto-Update ist in diesem Modus nicht verfügbar.', true);
    }
  } catch(e) {
    showAdminResult('✗ ' + (e.message||e), true);
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = 'Heruntergeladenes Update installieren'; }
  }
}
// ─────────────────────────────────────────────────────────────────────



// ════════════════════════════════════════════════════════════
// SECTION: RISK SCORING
// ════════════════════════════════════════════════════════════
// Implementiert die 5eyes Scoring-Logik aus risk_scoring.py
// ============================================================
var _riskScoreResult = null;
var currentMandateId = null;
var currentClientId = null;

function calcRiskScore() {
  // Fragen aus Tab 2 (Risikofähigkeit): Q5=Horizont, Q6=Sparquote, Q7=Liquidität
  var rfSections = document.querySelectorAll('#r-rf .qsec');
  var horizonIdx = -1, sparIdx = -1, liqIdx = -1;
  rfSections.forEach(function(sec, si) {
    var sel = sec.querySelector('.qopt.sel');
    if (!sel) return;
    var opts = Array.from(sec.querySelectorAll('.qopt'));
    var idx = opts.indexOf(sel);
    if (si === 0) horizonIdx = idx;
    else if (si === 1) sparIdx = idx;
    else if (si === 2) liqIdx = idx;
  });

  // Fragen aus Tab 3 (Risikobereitschaft): Q9=Anlageziel, Q10=Präferenz, Q11=Verhalten
  var rbSections = document.querySelectorAll('#r-rb .qsec');
  var goalIdx = -1, prefIdx = -1, behavIdx = -1;
  rbSections.forEach(function(sec, si) {
    var sel = sec.querySelector('.qopt.sel');
    if (!sel) return;
    var opts = Array.from(sec.querySelectorAll('.qopt'));
    var idx = opts.indexOf(sel);
    if (si === 0) goalIdx = idx;
    else if (si === 1) prefIdx = idx;
    else if (si === 2) behavIdx = idx;
  });

  // Risikofähigkeit Score (0–100)
  var horizonYears = [1, 3, 5, 12][Math.max(0, horizonIdx)];
  var sparPts = Math.max(0, sparIdx);
  var liqPts  = Math.max(0, liqIdx);
  var capTotal = sparPts * 4 + liqPts * 4;
  var capBand = capTotal >= 20 ? 5 : capTotal >= 15 ? 4 : capTotal >= 10 ? 3 : capTotal >= 5 ? 2 : 1;
  var matrix = {
    '1,1':5,'1,2':5,'1,3':5,'1,4':5,'1,5':5,
    '3,1':10,'3,2':15,'3,3':15,'3,4':15,'3,5':15,
    '5,1':10,'5,2':20,'5,3':25,'5,4':25,'5,5':25,
    '12,1':10,'12,2':20,'12,3':40,'12,4':60,'12,5':100
  };
  var capScore = matrix[horizonYears + ',' + capBand] || 15;

  // Risikobereitschaft Score (0–100)
  var willTotal = Math.max(0, goalIdx) + Math.max(0, prefIdx) + Math.max(0, behavIdx);
  var willScore = Math.round((willTotal / 9) * 100);

  // Finaler Score = Minimum
  var finalScore = Math.min(capScore, willScore);

  function s2p(s) {
    if (s >= 90) return 'Aktien';
    if (s >= 70) return 'Dynamisch';
    if (s >= 50) return 'Wachstumsorientiert';
    if (s >= 30) return 'Ausgewogen';
    if (s >= 10) return 'Defensiv';
    return 'Kapitalschutz';
  }

  var capProfile = s2p(capScore);
  var willProfile = s2p(willScore);
  var finalProfile = s2p(finalScore);

  // Profil-Beschreibungen
  var profileDescs = {
    'Kapitalschutz': 'Kapitalerhalt, minimales Risiko. Aktienquote max. 10 %.',
    'Defensiv': 'Sicherheitsorientiert, geringe Schwankungen. Aktienquote max. 25 %.',
    'Ausgewogen': 'Ausgewogenes Rendite-Risiko-Verhältnis. Aktienquote max. 40 %.',
    'Wachstumsorientiert': 'Erhöhtes Kapitalwachstum, erhöhtes Risiko. Aktienquote max. 60 %.',
    'Dynamisch': 'Wachstumsorientiert mit hoher Aktienquote. Aktienquote max. 80 %.',
    'Aktien': 'Maximales Wachstum, hohe Schwankungen. Aktienquote bis 100 %.'
  };

  // Ergebnis speichern
  _riskScoreResult = {
    capScore: capScore, capProfile: capProfile,
    willScore: willScore, willProfile: willProfile,
    finalScore: finalScore, finalProfile: finalProfile,
    raw: {horizonIdx: horizonIdx, sparIdx: sparIdx, liqIdx: liqIdx,
          goalIdx: goalIdx, prefIdx: prefIdx, behavIdx: behavIdx}
  };

  // UI aktualisieren — Score-Punkte (5 Dots)
  function makeDots(n) {
    var out = '';
    for (var i=1; i<=5; i++) out += '<div class="rs' + (i <= n ? ' on' : '') + '"></div>';
    return out;
  }

  var rdims = document.querySelectorAll('.rdim');
  if (rdims.length >= 2) {
    var capDots = Math.round(capScore / 20);
    rdims[0].querySelector('.rdl').textContent = 'Risikofähigkeit';
    rdims[0].querySelector('.rsc').innerHTML = makeDots(capDots);
    rdims[0].querySelector('.rval').textContent = capProfile + ' (' + capDots + '/5)';
    var capSubtext = sparIdx >= 2 && liqIdx >= 2 ? 'Zeithorizont, Sparquote & Reserven stark' :
                     sparIdx >= 1 || liqIdx >= 1 ? 'Mittlere Tragfähigkeit' : 'Geringe Tragfähigkeit';
    rdims[0].querySelector('.rsub').textContent = capSubtext;

    var willDots = Math.round(willScore / 20);
    rdims[1].querySelector('.rdl').textContent = 'Risikobereitschaft';
    rdims[1].querySelector('.rsc').innerHTML = makeDots(willDots);
    rdims[1].querySelector('.rval').textContent = willProfile + ' (' + willDots + '/5)';
    var willSubtext = goalIdx >= 2 && prefIdx >= 2 ? 'Wachstum, erhöhtes Risiko akzeptiert' :
                      goalIdx >= 1 || prefIdx >= 1 ? 'Moderate Risikobereitschaft' : 'Konservativ';
    rdims[1].querySelector('.rsub').textContent = willSubtext;
  }

  // Ergebnis-Box aktualisieren
  var rp = document.getElementById('res-pname');
  if (rp) rp.textContent = finalProfile;
  var rd = document.querySelector('.resbox .res-d');
  if (rd) rd.innerHTML = (profileDescs[finalProfile] || '') +
    '<div style="margin-top:6px;font-size:10px;color:var(--n5)">' +
    'Risikofähigkeit: <strong>' + capScore + '/100</strong> &nbsp;·&nbsp; ' +
    'Risikobereitschaft: <strong>' + willScore + '/100</strong> &nbsp;·&nbsp; ' +
    'Finaler Score: <strong>' + finalScore + '/100</strong></div>';

  // Score-Badge in Ergebnis-Box
  var scoreSpan = document.querySelector('.resbox span');
  if (scoreSpan) scoreSpan.innerHTML = 'Berechneter Score: <strong style="color:var(--n8)">' +
    Math.round(finalScore/10) + '/10</strong> <em style="font-size:9px;color:var(--n5)">(' + finalProfile + ')</em>';
}

async function saveRiskProfile() {
  if (!_riskScoreResult) {
    var _sb=document.getElementById('btn-save-riskprofile');
    if(_sb){var _ot=_sb.textContent;_sb.textContent='Bitte alle Fragen ausfüllen';_sb.style.color='var(--neg)';
      setTimeout(function(){_sb.textContent=_ot;_sb.style.color='';},3000);}
    return;
  }
  var btn = document.getElementById('btn-save-riskprofile');
  if (btn) { btn.disabled = true; btn.textContent = 'Speichern...'; }

  var r = _riskScoreResult;
  var raw = r.raw;
  var horizonMap = ['Bis 2 Jahre','2 bis 3 Jahre','4 bis 5 Jahre','Mehr als 12 Jahre'];
  var horizonYrMap = [1, 2, 5, 15];
  var hIdx = Math.max(0, raw.horizonIdx);

  var payload = {
    q_income_points: 2,
    q_obligations_points: 2,
    q_savings_points: Math.max(0, raw.sparIdx) * 4,
    q_wealth_points: Math.max(0, raw.liqIdx) * 4,
    investment_horizon_label: horizonMap[hIdx],
    investment_horizon_years: horizonYrMap[hIdx],
    q_investment_goal_points: Math.max(1, raw.goalIdx + 1),
    q_risk_preference_points: Math.max(1, raw.prefIdx + 1),
    q_risk_behavior_points: Math.max(1, raw.behavIdx + 1),
    answers: []
  };

  var mandateId = getActiveMandateId();

  if (mandateId) {
    try {
      await API.post('/mandates/' + mandateId + '/risk-assessments', payload);
      if (btn) {
        btn.disabled = false;
        btn.textContent = 'Gespeichert ✓';
        btn.style.background = 'var(--pos)';
        setTimeout(function() { if(btn){btn.textContent='Risikoprofil speichern';btn.style.background='';} }, 3000);
      }
      markStrategyDirty('Risikoprofil gespeichert: Strategie neu berechnen.');
      return;
    } catch(e) {
      // API call failed (network or server error) — show error, do not fall through to local display
      if (btn) { btn.disabled = false; btn.textContent = 'Fehler beim Speichern'; btn.style.color = 'var(--neg)';
        setTimeout(function(){if(btn){btn.textContent='Risikoprofil speichern';btn.style.color='';}},4000); }
      console.error('saveRiskProfile API error:', e.status, e.message);
      return;
    }
  }

  // No mandate active — show local score in UI only (not saved) — zeige Score lokal im Button und im Ergebnis-Badge
  if (btn) {
    btn.disabled = false;
    btn.textContent = r.finalProfile + ' ' + r.finalScore + '/100';
    btn.style.background = 'var(--g4)';
    btn.title = 'Risikofähigkeit: ' + r.capScore + '/100 · Risikobereitschaft: ' + r.willScore + '/100';
    setTimeout(function() {
      if (btn) { btn.textContent = 'Risikoprofil speichern'; btn.style.background = ''; btn.title = ''; }
    }, 5000);
  }
  // Show result in score badge (already updated by calcRiskScore, just re-confirm)
  var scoreSpan = document.querySelector('.resbox span');
  if (scoreSpan) {
    scoreSpan.innerHTML = 'Score: <strong style="color:var(--g4)">' + r.finalScore + '/100</strong>'
      + ' <em style="font-size:9px;color:var(--n5)">(' + r.finalProfile + ') — kein Mandat, nicht gespeichert</em>';
  }
}

// Neues Mandat anlegen
// ════════════════════════════════════════════════════════════
// SECTION: MANDATE & USER CREATION (createNewMandate, createNewUser)
// ════════════════════════════════════════════════════════════

async function createNewMandate() {
  var firstName = (document.getElementById('nc-firstname')||{value:''}).value.trim();
  var lastName  = (document.getElementById('nc-lastname')||{value:''}).value.trim();
  var dob       = (document.getElementById('nc-dob')||{value:''}).value || null;
  var canton    = (document.getElementById('nc-canton')||{value:''}).value.trim() || null;
  var mType     = (document.getElementById('nc-type')||{value:'Anlageberatung'}).value;
  var household = (document.getElementById('nc-household')||{value:'Einzelperson'}).value;
  var errEl     = document.getElementById('nc-error');
  var btn       = document.getElementById('btn-nc-submit');

  if (!firstName || !lastName) {
    if (errEl) { errEl.textContent = 'Bitte Vor- und Nachname eingeben.'; errEl.style.color = 'var(--neg)'; errEl.style.display = 'block'; }
    return;
  }
  if (errEl) errEl.style.display = 'none';
  if (btn) { btn.disabled = true; btn.textContent = 'Wird angelegt…'; }

  var ts = Date.now().toString().slice(-6);
  var clientNum  = 'C-' + ts;
  var mandateNum = 'M-' + ts;

  // Echter Netzwerkausfall vs. API-Fehler (4xx/5xx)
  function isNetworkDown(e) {
    return !e.status && (
      (e.message||'').includes('Failed to fetch') ||
      (e.message||'').includes('NetworkError') ||
      (e.message||'').includes('Load failed') ||
      !navigator.onLine
    );
  }

  function showErr(msg) {
    if (errEl) { errEl.textContent = msg; errEl.style.color = 'var(--neg)'; errEl.style.display = 'block'; }
    if (btn) { btn.disabled = false; btn.textContent = 'Mandat anlegen'; }
  }

  function addToSidebar(cid, warnLabel) {
    var sbl = document.getElementById('sbl');
    if (!sbl) return;
    document.querySelectorAll('.client').forEach(function(c){ c.classList.remove('active'); });
    var div = document.createElement('div');
    div.className = 'client active';
    div.dataset.pid = cid;
    div.dataset.cid = cid;
    div.innerHTML = '<div class="client-n">' + firstName + ' ' + lastName + '</div>' +
      '<div class="client-m">' + clientNum + ' &middot; ' + mType +
      (warnLabel ? ' <span style="color:var(--warn);font-size:9px;margin-left:4px">' + warnLabel + '</span>' : '') +
      '</div><div class="client-tags"><span class="ctag ct-b">Neu</span></div>';
    div.onclick = function() { selC(div); showNewClientScreen(firstName, lastName, mType); };
    sbl.insertBefore(div, sbl.firstChild);
  }

  // Schritt 1: Client anlegen
  var clientData;
  try {
    clientData = await API.post('/clients', {
      client_number: clientNum,
      first_name: firstName,
      last_name: lastName,
      date_of_birth: dob || null,
      canton: canton,
      household_type: household,
      language: 'DE',
      advisor_id: currentUser ? currentUser.id : null,
      country_of_residence: 'CH',
      client_classification: 'Privatkunde',
      is_professional_opt_out: false,
      is_qualified_investor: false
    });
    currentClientId = clientData.id;
  } catch(ce) {
    if (isNetworkDown(ce)) {
      // Backend nicht erreichbar — Demo-Eintrag mit sichtbarem Label
      currentClientId = 'demo-' + ts;
      addToSidebar(currentClientId, '⚠️ Demo');
      showNewClientScreen(firstName, lastName, mType, {dob:dob, canton:canton, household:household});
      cm('m-nc');
      // Formular leeren
      ['nc-firstname','nc-lastname','nc-canton'].forEach(function(id){ var el=document.getElementById(id);if(el)el.value=''; });
      var dobEl2=document.getElementById('nc-dob');if(dobEl2)dobEl2.value='';
      if (btn) { btn.disabled = false; btn.textContent = 'Mandat anlegen'; }
      // Fehlermeldung bleibt sichtbar (ausserhalb Modal)
      if (errEl) { errEl.textContent = '⚠️ Demo-Modus: Backend nicht erreichbar — Daten werden nicht gespeichert.'; errEl.style.color = 'var(--warn)'; errEl.style.display = 'block'; }
      return;
    }
    // API-Fehler (4xx/5xx): kein lokaler Fallback
    showErr('Client konnte nicht angelegt werden: ' + (ce.detail || ce.message || 'HTTP ' + (ce.status || '?')));
    return;
  }

  // Schritt 2: Mandat anlegen
  var mandateData;
  try {
    mandateData = await API.post('/clients/' + currentClientId + '/mandates', {
      mandate_number: mandateNum,
      mandate_type: mType,
      base_currency: 'CHF',
      advisory_language: 'DE'
    });
    currentMandateId = mandateData.id;
  } catch(me) {
    if (isNetworkDown(me)) {
      // Client wurde angelegt, Mandat nicht — ehrlich kommunizieren
      addToSidebar(currentClientId, '⚠️ kein Mandat');
      showNewClientScreen(firstName, lastName, mType, {dob:dob, canton:canton, household:household});
      cm('m-nc');
      if (btn) { btn.disabled = false; btn.textContent = 'Mandat anlegen'; }
      return;
    }
    showErr('Mandat konnte nicht angelegt werden: ' + (me.detail || me.message || 'HTTP ' + (me.status || '?')));
    return;
  }

  // Schritt 3: Erfolg
  addToSidebar(currentClientId, '');
  showNewClientScreen(firstName, lastName, mType, {dob:dob, canton:canton, household:household});
  cm('m-nc');
  ['nc-firstname','nc-lastname','nc-canton'].forEach(function(id){
    var el=document.getElementById(id); if(el)el.value='';
  });
  var dobEl=document.getElementById('nc-dob'); if(dobEl)dobEl.value='';
  if (btn) { btn.disabled = false; btn.textContent = 'Mandat anlegen'; }
}

function showNewClientScreen(firstName, lastName, mType, meta) {
  meta = meta || {};
  currentPersona = {
    name: firstName+' '+lastName,
    first_name: firstName,
    last_name: lastName,
    mandate_type: mType,
    date_of_birth: meta.dob || null,
    canton: meta.canton || null,
    household_type: meta.household || null,
    household: meta.household || null,
    language: 'DE'
  };

  var phS = document.querySelector('#page-sd .ph-s');
  if (phS) phS.textContent = firstName + ' ' + lastName + ' \u00b7 ' + mType + ' \u00b7 Neu angelegt';

  var hg = document.getElementById('hh-grid');
  if (hg) hg.innerHTML =
    '<div><div class="psk">Hauptperson</div><div class="psv">' + firstName + ' ' + lastName + '</div></div>' +
    '<div><div class="psk">Mandat-Typ</div><div class="psv">' + mType + '</div></div>' +
    '<div><div class="psk">Status</div><div class="psv" style="color:var(--pos)">Aktiv &mdash; neu angelegt</div></div>' +
    '<div><div class="psk">N&auml;chster Schritt</div><div class="psv">Risikoprofilierung ausf&uuml;llen</div></div>';

  document.querySelectorAll('.kpir .kv').forEach(function(el){el.textContent='CHF \u2014';});
  document.querySelectorAll('.kpir .ks').forEach(function(el){el.textContent='\u2014';});

  var av = document.getElementById('asset-view');
  if (av) av.innerHTML = '<div style="color:var(--n4);font-size:11px;padding:20px;text-align:center">Noch keine Verm&ouml;gensangaben erfasst.<br>Bitte Risikoprofil ausf&uuml;llen und Verm&ouml;gen erfassen.</div>';

  var zf = document.getElementById('zufluss-rows');
  if (zf) zf.innerHTML = '<div style="color:var(--n4);font-size:11px;padding:12px 0">Noch keine Zuflusse erfasst.</div>';
  var af = document.getElementById('abfluss-rows');
  if (af) af.innerHTML = '<div style="color:var(--n4);font-size:11px;padding:12px 0">Noch keine Abflusse erfasst.</div>';
  var zl = document.getElementById('zl');
  if (zl) zl.innerHTML = '<div style="color:var(--n4);font-size:11px;padding:12px 0">Noch keine Ziele erfasst.</div>';

  document.title = '5eyes \u00b7 ' + firstName + ' ' + lastName;
  go('sd');
}

// Neuer Benutzer anlegen (Admin)
async function createNewUser() {
  var fullName = (document.getElementById('nu-fullname')||{value:''}).value.trim();
  var username = (document.getElementById('nu-username')||{value:''}).value.trim();
  var password = (document.getElementById('nu-password')||{value:''}).value;
  var role     = (document.getElementById('nu-role')||{value:'advisor'}).value;
  var email    = (document.getElementById('nu-email')||{value:''}).value.trim() || null;
  var errEl    = document.getElementById('nu-error');
  var btn      = document.getElementById('btn-nu-submit');

  if (!fullName || !username || !password) {
    if (errEl) { errEl.textContent = 'Bitte Name, Benutzername und Passwort eingeben.'; errEl.style.display='block'; }
    return;
  }
  if (password.length < 10) {
    if (errEl) { errEl.textContent = 'Passwort muss mindestens 10 Zeichen lang sein.'; errEl.style.display='block'; }
    return;
  }
  if (errEl) errEl.style.display = 'none';
  if (btn) { btn.disabled = true; btn.textContent = 'Wird angelegt...'; }

  try {
    var data = await API.post('/users', {
      username: username,
      password: password,
      full_name: fullName,
      email: email,
      role: role
    });
    showAdminResult('\u2713 Benutzer angelegt:\n  Name: ' + data.full_name + '\n  Login: ' + data.username + '\n  Rolle: ' + data.role, false);
    ['nu-fullname','nu-username','nu-password','nu-email'].forEach(function(id){
      var el=document.getElementById(id); if(el)el.value='';
    });
    if (btn) { btn.disabled=false; btn.textContent='Benutzer anlegen'; }
  } catch(e) {
    var msg = e.detail || e.message || String(e);
    if (errEl) { errEl.textContent = 'Fehler: ' + msg; errEl.style.display='block'; }
    if (btn) { btn.disabled=false; btn.textContent='Benutzer anlegen'; }
  }
}


// ════════════════════════════════════════════════════════════
// SECTION: HELPERS (parseCHF, showModalFeedback, getActive*)
// ════════════════════════════════════════════════════════════
function showModalFeedback(eid,btn,msg,isErr){
  var e=document.getElementById(eid);
  if(e){e.textContent=msg;e.style.color=isErr?'var(--neg)':'var(--pos)';e.style.display='block';
    if(!isErr)setTimeout(function(){e.style.display='none';},3000);}
  if(btn){btn.disabled=false;btn.textContent=isErr?'Fehler – nochmals':(btn._origText||'Speichern');
    if(!isErr){btn.style.background='var(--pos)';setTimeout(function(){if(btn)btn.style.background='';},2500);}}
}
function parseApiError(e,fallback){
  return String((e&&e.detail)||(e&&e.message)||fallback||'?');
}
function parseCHF(s){
  var c=String(s||0).replace(/['\s]/g,'').replace(',','.');
  return Math.round((parseFloat(c)||0)*100);
}
function parseUnitsMilli(value){
  var raw=String(value||'').replace(/['\s]/g,'').replace(',','.').trim();
  if(!raw)return null;
  var units=parseFloat(raw);
  if(!isFinite(units)||units<0)return null;
  return Math.round(units*1000);
}
function formatUnitsInput(value){
  if(value==null||value==='')return '';
  var units=Number(value)/1000;
  if(!isFinite(units))return '';
  return units.toLocaleString('de-CH',{minimumFractionDigits:0,maximumFractionDigits:3});
}
function parsePercentToBps(value){
  var raw=String(value||'').replace('%','').replace(',','.').trim();
  if(!raw)return null;
  var n=parseFloat(raw);
  return isFinite(n)?Math.round(n*100):null;
}
function escapeHtml(value){
  return String(value==null?'':value)
    .replace(/&/g,'&amp;')
    .replace(/</g,'&lt;')
    .replace(/>/g,'&gt;')
    .replace(/"/g,'&quot;')
    .replace(/'/g,'&#39;');
}
function getInputValue(id){
  var el=document.getElementById(id);
  return el?String(el.value||''):'';
}
function getCheckboxValue(id){
  var el=document.getElementById(id);
  return !!(el&&el.checked);
}
function getRadioValue(name,fallback){
  var el=document.querySelector('input[name="'+name+'"]:checked');
  return el?String(el.value||''):(fallback||'');
}
function joinNotes(parts){
  var items=(parts||[]).map(function(part){return String(part||'').trim();}).filter(Boolean);
  return items.length?items.join(' | '):null;
}
  function bpsToPercentText(bps){
    if(bps==null||isNaN(Number(bps)))return '';
    var pct=(Number(bps)/100).toFixed(2).replace(/\.00$/,'').replace(/(\.\d)0$/,'$1');
    return pct+'%';
  }
  function chfFromRappen(rappen){
    return Math.round((Number(rappen)||0)/100);
  }
  var currentWealthPositions=[];
  function getPropertyPositionLabelById(positionId){
    var match=currentWealthPositions.find(function(pos){return pos&&pos.id===positionId;});
    return match?(match.label||'Immobilienposition'):'';
  }
  function updateMortgageLinkedPropertyOptions(selectedId){
    var select=document.getElementById('maw-mortgage-linked-property');
    var hint=document.getElementById('maw-mortgage-linked-property-hint');
    if(!select)return;
    var selected=selectedId==null?String(select.value||''):String(selectedId||'');
    var properties=currentWealthPositions.filter(function(pos){
      return pos&&pos.position_type==='Immobilien'&&(!Object.prototype.hasOwnProperty.call(pos,'is_active')||pos.is_active!==0);
    });
    var options=['<option value="">Keine direkte Verknüpfung</option>'];
    properties.forEach(function(pos){
      options.push('<option value="'+escapeHtml(pos.id||'')+'">'+escapeHtml(pos.label||'Immobilienposition')+'</option>');
    });
    select.innerHTML=options.join('');
    if(selected&&properties.some(function(pos){return pos.id===selected;}))select.value=selected;
    else select.value='';
    if(hint){
      hint.textContent=properties.length
        ? 'Optional: Hypothek einer bereits erfassten Immobilienposition zuordnen.'
        : 'Für eine exakte Verknüpfung zuerst eine Immobilienposition erfassen.';
    }
  }
  var currentWealthEditId=null;
  var currentReviewState={triggers:[],logs:[],documents:[]};
  var currentDecisionChoice='option_a';
  function formatDateSwiss(value){
    if(!value)return '—';
    var txt=String(value).slice(0,10);
    if(!/^\d{4}-\d{2}-\d{2}$/.test(txt))return String(value);
    return txt.split('-').reverse().join('.');
  }
  function formatInputPercent(bps){
    if(bps==null||isNaN(Number(bps)))return '';
    return (Number(bps)/100).toFixed(2).replace(/\.00$/,'').replace(/(\.\d)0$/,'$1');
  }
  function formatInputCHF(rappen){
    if(rappen==null||isNaN(Number(rappen)))return '';
    return String(Math.round(Number(rappen)/100));
  }
  function ensureModalError(modalId,errorId){
    var modal=document.getElementById(modalId);
    if(!modal)return null;
    var existing=document.getElementById(errorId);
    if(existing)return existing;
    var footer=modal.querySelector('.mfooter');
    if(!footer||!footer.parentNode)return null;
    var box=document.createElement('div');
    box.id=errorId;
    box.style.cssText='display:none;color:var(--neg);font-size:11px;padding:4px 0;margin-top:4px';
    footer.parentNode.insertBefore(box,footer);
    return box;
  }
  function ensureWealthEditorDeleteButton(){
    var footer=document.querySelector('#m-aw .mfooter');
    var saveBtn=document.getElementById('btn-maw-save');
    if(!footer||!saveBtn)return;
    var del=document.getElementById('btn-maw-delete');
    if(!del){
      del=document.createElement('button');
      del.id='btn-maw-delete';
      del.type='button';
      del.textContent='Position löschen';
      del.style.cssText='display:none;background:var(--neg);color:#fff;border:none;border-radius:var(--r);font-family:var(--f-s);font-size:11px;padding:6px 13px;cursor:pointer;margin-right:auto';
      del.onclick=function(){ deleteCurrentWealthPosition(); };
      footer.insertBefore(del,saveBtn);
    }
  }
  function cleanupModalAfterClose(id){
    if(id==='m-aw')resetWealthEditor();
    if(id==='m-acf')resetCashflowModal();
    if(id==='m-nz')resetGoalModal();
    if(id==='m-ed'){
      var modal=document.getElementById('m-ed');
      if(modal)modal.dataset.triggerId='';
    }
    if(id==='m-ne'){
      var ne=document.getElementById('ne-trigger-id');
      if(ne)ne.value='';
    }
  }
  function prepareModalBeforeOpen(id){
    if(id==='m-edit-depot'){openLegacyWealthModalRedirect('Depot');return false;}
    if(id==='m-edit-immo'){openLegacyWealthModalRedirect('Immobilien');return false;}
    if(id==='m-edit-hypo'){openLegacyWealthModalRedirect('Hypothek');return false;}
    if(id==='m-edit-custom'){openLegacyWealthModalRedirect('Alternative');return false;}
    if(id==='m-ev')resetEventCaptureModal();
    if(id==='m-ne')resetAdvisoryLogModal();
    if(id==='m-nt')resetReviewTriggerModal();
    if(id==='m-contract-edit')resetContractDocumentModal();
    if(id==='m-ed')resetDecisionTemplateModal();
    if(id==='m-acf'&&!currentCashflowEditId)resetCashflowModal();
    if(id==='m-nz'&&!currentGoalEditId)resetGoalModal();
    if(id==='m-aw'&&!currentWealthEditId)resetWealthEditor();
    return true;
  }
  function openLegacyWealthModalRedirect(category){
    resetWealthEditor(category);
    var modal=document.getElementById('m-aw');
    if(modal)modal.classList.add('open');
    showModalFeedback('maw-error',document.getElementById('btn-maw-save'),'Legacy-Editor ersetzt: Bitte die Position im echten Gesamtvermögens-Formular pflegen.',false);
  }
  function resetWealthEditor(defaultCategory){
    currentWealthEditId=null;
    var cat=defaultCategory||'Depot';
    [
      'maw-depot-label','maw-depot-bank','maw-depot-account','maw-depot-value',
      'maw-liq-label','maw-liq-bank','maw-liq-value','maw-liq-rate','maw-liq-available',
      'maw-immo-label','maw-immo-address','maw-immo-value','maw-immo-valuation-date','maw-immo-rent',
      'maw-pension-label','maw-pension-institution','maw-pension-value','maw-pension-rate','maw-pension-age','maw-pension-available',
      'maw-alt-label','maw-alt-value','maw-alt-valuation-date','maw-alt-return','maw-alt-location',
      'maw-mortgage-label','maw-mortgage-bank','maw-mortgage-value','maw-mortgage-rate','maw-mortgage-maturity','maw-mortgage-amortization',
      'maw-note'
    ].forEach(function(id){ setInputValue(id,''); });
    ['sc-akt','sc-obl','sc-imm','sc-liq','sc-alt'].forEach(function(id){ setInputValue(id,'0'); });
    setSelectValue('maw-cat',cat);
    var catSelect=document.getElementById('maw-cat');
    if(catSelect)catSelect.disabled=false;
    setSelectValue('maw-typ',cat==='Hypothek'?'Verbindlichkeit':(cat==='Depot'||cat==='Liquiditaet'?'Beratungsvermögen':'Anderes Vermögen'));
    setSelectValue('maw-liq-instrument','Kontoguthaben');
    setSelectValue('maw-immo-usage','Selbstgenutzt');
    setSelectValue('maw-pension-type','BVG');
    setSelectValue('maw-pension-payout','Rente');
    setSelectValue('maw-pension-wef','Ja');
    setSelectValue('maw-alt-subtype','Private Equity / Beteiligung');
    setSelectValue('maw-alt-liquidity','Liquide (< 30 Tage)');
    setSelectValue('maw-alt-valuation-method','Marktpreis');
    setSelectValue('maw-mortgage-type','Festhypothek');
    setSelectValue('maw-mortgage-amortization-type','Indirekt (Säule 3a)');
    updateMortgageLinkedPropertyOptions('');
    showAwFields(cat);
    calcSCTotal();
    var saveBtn=document.getElementById('btn-maw-save');
    if(saveBtn){saveBtn.textContent='Speichern';saveBtn.disabled=false;}
    var delBtn=document.getElementById('btn-maw-delete');
    if(delBtn)delBtn.style.display='none';
    var err=document.getElementById('maw-error');
    if(err){err.style.display='none';err.textContent='';}
  }
  function openWealthPositionEditor(positionId){
    var pos=currentWealthPositions.find(function(item){return item&&String(item.id||'')===String(positionId||'');});
    if(!pos){openLegacyWealthModalRedirect('Depot');return;}
    currentWealthEditId=pos.id;
    var cat=pos.position_type==='Liquidität'?'Liquiditaet':(pos.position_type==='Custom'?'Alternative':pos.position_type);
    resetWealthEditor(cat);
    currentWealthEditId=pos.id;
    var catSelect=document.getElementById('maw-cat');
    if(catSelect)catSelect.disabled=true;
    setSelectValue('maw-cat',cat);
    setSelectValue('maw-typ',pos.assignment||'Anderes Vermögen');
    setInputValue('maw-note',pos.notes||'');
    if(pos.position_type==='Depot'){
      setInputValue('maw-depot-label',pos.label||'');
      setInputValue('maw-depot-bank',pos.depot_bank||'');
      setInputValue('maw-depot-account',pos.depot_account_number||'');
      setInputValue('maw-depot-value',formatInputCHF(pos.current_value_rappen));
      setInputValue('sc-akt',Math.round(Number(pos.alloc_equities_bps||0)/100));
      setInputValue('sc-obl',Math.round(Number(pos.alloc_bonds_bps||0)/100));
      setInputValue('sc-imm',Math.round(Number(pos.alloc_real_estate_bps||0)/100));
      setInputValue('sc-liq',Math.round(Number(pos.alloc_liquidity_bps||0)/100));
      setInputValue('sc-alt',Math.round(Number(pos.alloc_alternatives_bps||0)/100));
      calcSCTotal();
    } else if(pos.position_type==='Liquidität'){
      setInputValue('maw-liq-label',pos.label||'');
      setInputValue('maw-liq-value',formatInputCHF(pos.current_value_rappen));
      setSelectValue('maw-liq-instrument',pos.liquidity_instrument||'Kontoguthaben');
      setInputValue('maw-liq-rate',formatInputPercent(pos.liquidity_interest_rate_bps));
      setInputValue('maw-liq-available',pos.liquidity_available_from||'');
    } else if(pos.position_type==='Immobilien'){
      setInputValue('maw-immo-label',pos.label||'');
      setSelectValue('maw-immo-usage',pos.property_usage||'Selbstgenutzt');
      setInputValue('maw-immo-address',pos.property_address||'');
      setInputValue('maw-immo-value',formatInputCHF(pos.current_value_rappen));
      setInputValue('maw-immo-valuation-date',pos.valuation_date||'');
      setInputValue('maw-immo-rent',formatInputCHF(pos.property_rental_income_rappen));
    } else if(pos.position_type==='Vorsorge'){
      setInputValue('maw-pension-label',pos.label||'');
      setSelectValue('maw-pension-type',pos.pension_type||'BVG');
      setInputValue('maw-pension-institution',pos.pension_institution||'');
      setInputValue('maw-pension-value',formatInputCHF(pos.current_value_rappen));
      setInputValue('maw-pension-rate',formatInputPercent(pos.pension_technical_rate_bps));
      setInputValue('maw-pension-age',pos.pension_retirement_age==null?'':pos.pension_retirement_age);
      setSelectValue('maw-pension-payout',pos.pension_payout_form||'Rente');
      setSelectValue('maw-pension-wef',Number(pos.pension_wef_possible||0)?'Ja':'Nein');
    } else if(pos.position_type==='Alternative'||pos.position_type==='Custom'){
      setInputValue('maw-alt-label',pos.label||'');
      setSelectValue('maw-alt-subtype',pos.asset_subtype||'Private Equity / Beteiligung');
      setInputValue('maw-alt-value',formatInputCHF(pos.current_value_rappen));
      setInputValue('maw-alt-valuation-date',pos.valuation_date||'');
      setInputValue('maw-alt-return',formatInputPercent(pos.asset_expected_return_bps));
      setSelectValue('maw-alt-liquidity',pos.asset_liquidity||'Liquide (< 30 Tage)');
      setSelectValue('maw-alt-valuation-method',pos.asset_valuation_method||'Marktpreis');
      setInputValue('maw-alt-location',pos.asset_location||'');
    } else if(pos.position_type==='Hypothek'){
      setInputValue('maw-mortgage-label',pos.label||'');
      setInputValue('maw-mortgage-bank',pos.mortgage_bank||'');
      setInputValue('maw-mortgage-value',formatInputCHF(pos.current_value_rappen));
      setSelectValue('maw-mortgage-type',pos.mortgage_type||'Festhypothek');
      setInputValue('maw-mortgage-rate',formatInputPercent(pos.mortgage_interest_rate_bps));
      setInputValue('maw-mortgage-maturity',pos.mortgage_maturity_date||'');
      setInputValue('maw-mortgage-amortization',formatInputCHF(pos.mortgage_amortization_rappen));
      setSelectValue('maw-mortgage-amortization-type',pos.mortgage_amortization_type||'Indirekt (Säule 3a)');
      updateMortgageLinkedPropertyOptions(pos.mortgage_linked_property_id||'');
    }
    showAwFields(cat);
    var saveBtn=document.getElementById('btn-maw-save');
    if(saveBtn){saveBtn.textContent='Aktualisieren';saveBtn.disabled=false;}
    var delBtn=document.getElementById('btn-maw-delete');
    if(delBtn)delBtn.style.display='inline-block';
    var err=document.getElementById('maw-error');
    if(err){err.style.display='none';err.textContent='';}
    var modal=document.getElementById('m-aw');
    if(modal)modal.classList.add('open');
  }
  function deleteWealthPositionById(positionId){
    currentWealthEditId=positionId||null;
    deleteCurrentWealthPosition();
  }
  async function deleteCurrentWealthPosition(){
    var positionId=currentWealthEditId;
    if(!positionId)return;
    var cid=getActiveClientId();
    var isDemo=isDemoClientId(positionId)||isDemoClientId(cid);
    if(!confirm(isDemo?'Position entfernen (Demo)?':'Vermögensposition wirklich löschen?'))return;
    if(isDemo){
      currentWealthPositions=currentWealthPositions.filter(function(pos){return String(pos.id||'')!==String(positionId);});
      renderWealthPositions(currentWealthPositions);
      cm('m-aw');
      return;
    }
    try{
      await API.del('/clients/'+cid+'/wealth-positions/'+positionId);
      await refreshWealthUI(cid);
      markStrategyDirty('Vermögensposition gelöscht: Strategie neu berechnen.');
      cm('m-aw');
    }catch(e){
      showModalFeedback('maw-error',document.getElementById('btn-maw-save'),'Fehler: '+(e.detail||e.message||'?'),true);
    }
  }
  function resetCashflowModal(){
    currentCashflowEditId=null;
    setInputValue('acf-label','');
    setSelectValue('acf-cftype','Income');
    setInputValue('acf-amount','');
    setSelectValue('acf-cat','Sonstiges');
    setSelectValue('acf-freq','jährlich');
    var btn=document.getElementById('btn-acf-save');
    if(btn){btn.textContent='Speichern';btn.disabled=false;}
    var err=document.getElementById('acf-error');
    if(err){err.style.display='none';err.textContent='';}
  }
  function openCashflowEditor(cashflowId){
    var cashflow=(currentCashflows||[]).find(function(item){return String(item.id||'')===String(cashflowId||'');});
    if(!cashflow)return;
    currentCashflowEditId=cashflow.id;
    setInputValue('acf-label',cashflow.label||'');
    setSelectValue('acf-cftype',cashflow.cashflow_type||'Income');
    setInputValue('acf-amount',formatInputCHF(cashflow.amount_rappen));
    setSelectValue('acf-cat',cashflow.notes||'Sonstiges');
    setSelectValue('acf-freq',cashflow.frequency||'jährlich');
    var btn=document.getElementById('btn-acf-save');
    if(btn){btn.textContent='Aktualisieren';btn.disabled=false;}
    var err=document.getElementById('acf-error');
    if(err){err.style.display='none';err.textContent='';}
    var modal=document.getElementById('m-acf');
    if(modal)modal.classList.add('open');
  }
  function resetGoalModal(){
    currentGoalEditId=null;
    setInputValue('nz-label','');
    setSelectValue('nz-type','Einmalige_Ausgabe');
    setSelectValue('nz-prio','2');
    setInputValue('nz-amount','');
    setInputValue('nz-horizon','10');
    var btn=document.getElementById('btn-nz-save');
    if(btn){btn.textContent='Speichern';btn.disabled=false;}
    var err=document.getElementById('nz-error');
    if(err){err.style.display='none';err.textContent='';}
  }
  function openGoalEditor(goalId){
    var goal=(currentGoals||[]).find(function(item){return String(item.id||'')===String(goalId||'');});
    if(!goal)return;
    currentGoalEditId=goal.id;
    var goalType=goal.goal_type||'Einmalige_Ausgabe';
    var amount=goal.target_amount_rappen!=null?formatInputCHF(goal.target_amount_rappen)
      : goal.target_wealth_rappen!=null?formatInputCHF(goal.target_wealth_rappen)
      : goal.target_return_bps!=null?formatInputPercent(goal.target_return_bps):'';
    var priorityMap={Hart:'1',Primär:'2',Opportunistisch:'3'};
    setInputValue('nz-label',goal.label||'');
    setSelectValue('nz-type',goalType);
    setSelectValue('nz-prio',priorityMap[goal.hardness]||String(goal.rank||2));
    setInputValue('nz-amount',amount);
    setInputValue('nz-horizon',goal.horizon_years==null?'10':goal.horizon_years);
    var btn=document.getElementById('btn-nz-save');
    if(btn){btn.textContent='Aktualisieren';btn.disabled=false;}
    var err=document.getElementById('nz-error');
    if(err){err.style.display='none';err.textContent='';}
    var modal=document.getElementById('m-nz');
    if(modal)modal.classList.add('open');
  }
  function bindLegacyReviewModalActions(){
    var ev=document.getElementById('m-ev');
    if(ev){
      var evFields=ev.querySelectorAll('.mbody select, .mbody input, .mbody textarea');
      if(evFields[0])evFields[0].id='ev-type';
      if(evFields[1])evFields[1].id='ev-date';
      if(evFields[2])evFields[2].id='ev-details';
      if(evFields[3])evFields[3].id='ev-action';
      var evType=document.getElementById('ev-type');
      if(evType && !evType.dataset.runtimeBound){
        [
          'Pensionierung / Ruhestand',
          'Jobwechsel / Kuendigung',
          'Erbschaft erhalten',
          'Scheidung / Trennung',
          'Todesfall Haushaltsmitglied',
          'Immobilienkauf / -verkauf',
          'Grosse Einzahlung (>20%)',
          'Grosse Entnahme (>20%)',
          'Externe Depot-Aenderung',
          'Zielaenderung',
          'Gesundheitliche Veraenderung',
          'Anderes Ereignis'
        ].forEach(function(label,idx){
          if(evType.options[idx]){
            evType.options[idx].value=label;
            evType.options[idx].textContent=label;
          }
        });
        evType.dataset.runtimeBound='1';
      }
      var evAction=document.getElementById('ev-action');
      if(evAction && !evAction.dataset.runtimeBound){
        [
          ['review','Review-Termin ausloesen'],
          ['risk','Risikoprofil neu pruefen'],
          ['goals','Ziele anpassen'],
          ['document','Nur dokumentieren - kein Handlungsbedarf']
        ].forEach(function(meta,idx){
          if(evAction.options[idx]){
            evAction.options[idx].value=meta[0];
            evAction.options[idx].textContent=meta[1];
          }
        });
        evAction.dataset.runtimeBound='1';
      }
      ensureModalError('m-ev','ev-error');
      if(!document.getElementById('ev-calendar')){
        var row=document.createElement('div');
        row.className='frow';
        row.innerHTML='<div class="fg"><label style="display:flex;align-items:center;gap:8px;font-size:11px;color:var(--n6);cursor:pointer"><input id="ev-calendar" type="checkbox" checked>Kalendereintrag fuer den Review mitgeben (.ics)</label></div>';
        ev.querySelector('.mbody').appendChild(row);
      }
      var evSave=ev.querySelector('.mfooter .btn-p');
      if(evSave){evSave.id='btn-ev-save';evSave.setAttribute('onclick','runtimeProtokolliereEreignis()');}
    }
    var ne=document.getElementById('m-ne');
    if(ne){
      var neFields=ne.querySelectorAll('.mbody input, .mbody select, .mbody textarea');
      if(neFields[0])neFields[0].id='ne-date';
      if(neFields[1])neFields[1].id='ne-decision';
      if(neFields[2])neFields[2].id='ne-title';
      if(neFields[3])neFields[3].id='ne-description';
      if(!document.getElementById('ne-trigger-id')){
        var hidden=document.createElement('input');
        hidden.type='hidden';
        hidden.id='ne-trigger-id';
        ne.querySelector('.mbody').prepend(hidden);
      }
      ensureModalError('m-ne','ne-error');
      var neSave=ne.querySelector('.mfooter .btn-p');
      if(neSave){neSave.id='btn-ne-save';neSave.setAttribute('onclick','saveAdvisoryLogEntry()');}
    }
    var nt=document.getElementById('m-nt');
    if(nt){
      var ntFields=nt.querySelectorAll('.mbody input, .mbody select');
      if(ntFields[0])ntFields[0].id='nt-type';
      if(ntFields[1])ntFields[1].id='nt-name';
      if(ntFields[2])ntFields[2].id='nt-threshold';
      ensureModalError('m-nt','nt-error');
      var ntSave=nt.querySelector('.mfooter .btn-p');
      if(ntSave){ntSave.id='btn-nt-save';ntSave.setAttribute('onclick','saveReviewTrigger()');}
    }
    var ce=document.getElementById('m-contract-edit');
    if(ce){
      var ceFields=ce.querySelectorAll('.mbody input, .mbody textarea');
      if(ceFields[0])ceFields[0].id='contract-title';
      if(ceFields[1])ceFields[1].id='contract-intro';
      if(ceFields[2])ceFields[2].id='contract-disclaimer';
      if(ceFields[3])ceFields[3].id='contract-special';
      if(ceFields[4])ceFields[4].id='contract-place';
      if(ceFields[5])ceFields[5].id='contract-date';
      ensureModalError('m-contract-edit','contract-error');
      var ceSave=ce.querySelector('.mfooter .btn-p');
      if(ceSave){ceSave.id='btn-contract-save';ceSave.setAttribute('onclick','saveContractDocumentDraft()');}
      var cePrint=ce.querySelector('.mfooter .btn-g');
      if(cePrint)cePrint.setAttribute('onclick',"printReport({pages:['rp','ub','al']})");
    }
    var ed=document.getElementById('m-ed');
    if(ed){
      ensureModalError('m-ed','ed-error');
      var sections=ed.querySelectorAll('.mbody > div');
      var cards=sections[2]?sections[2].children:[];
      ['option_a','option_b','option_c'].forEach(function(key,idx){
        var card=cards[idx];
        if(!card)return;
        card.dataset.choice=key;
        card.onclick=function(){selectDecisionOption(key);};
      });
      var edSave=ed.querySelector('.mfooter .btn-p');
      if(edSave){edSave.id='btn-ed-save';edSave.setAttribute('onclick','documentDecisionTemplate()');}
    }
  }
function resetEventCaptureModal(){
  setSelectValue('ev-type','Pensionierung / Ruhestand');
  setInputValue('ev-date',new Date().toISOString().slice(0,10));
  setInputValue('ev-details','');
  setSelectValue('ev-action','review');
  var chk=document.getElementById('ev-calendar');
  if(chk)chk.checked=true;
  var err=document.getElementById('ev-error');
  if(err)err.textContent='';
  var btn=document.getElementById('btn-ev-save');
  if(btn){btn.textContent='Protokollieren';btn.disabled=false;}
}
function resetAdvisoryLogModal(){
  setInputValue('ne-date',new Date().toISOString().slice(0,10));
    setSelectValue('ne-decision','Keine Transaktion');
    setInputValue('ne-title','');
    setInputValue('ne-description','');
    var err=document.getElementById('ne-error');
    if(err){err.style.display='none';err.textContent='';}
    var btn=document.getElementById('btn-ne-save');
    if(btn){btn.textContent='Speichern';btn.disabled=false;}
  }
  function openAdvisoryLogModal(triggerId,title){
    var hidden=document.getElementById('ne-trigger-id');
    if(hidden)hidden.value=triggerId||'';
    resetAdvisoryLogModal();
    if(!title&&triggerId){
      var trigger=(currentReviewState.triggers||[]).find(function(item){return String(item.id||'')===String(triggerId||'');});
      if(trigger)title=trigger.trigger_name||'Review-Entscheid';
    }
    if(title)setInputValue('ne-title',title);
    var modal=document.getElementById('m-ne');
    if(modal)modal.classList.add('open');
  }
  function resetReviewTriggerModal(){
    setSelectValue('nt-type','Zeitbasiert');
    setInputValue('nt-name','');
    setInputValue('nt-threshold','');
    var err=document.getElementById('nt-error');
    if(err){err.style.display='none';err.textContent='';}
    var btn=document.getElementById('btn-nt-save');
    if(btn){btn.textContent='Aktivieren';btn.disabled=false;}
  }
  function resetContractDocumentModal(){
    var fullName=currentPersona?((currentPersona.first_name||currentPersona.name||'')+' '+(currentPersona.last_name||'')).trim():'';
    setInputValue('contract-title','Persönliche Anlagestrategie – Individuelle Vermögensberatung');
    if(!getInputValue('contract-intro'))setInputValue('contract-intro','Auf Grundlage der gemeinsamen Analyse der persönlichen und finanziellen Situation sowie der Anlageziele wurde folgende individuelle Anlagestrategie vereinbart.');
    if(!getInputValue('contract-disclaimer'))setInputValue('contract-disclaimer','Diese Empfehlung basiert auf den zum Zeitpunkt der Beratung bekannten Informationen und stellt keine Garantie künftiger Wertentwicklungen dar. Die Umsetzung erfolgt eigenverantwortlich durch den Kunden.');
    if(getInputValue('contract-special')==='')setInputValue('contract-special',fullName?'Mandat für '+fullName+'.':'');
    setInputValue('contract-place',getInputValue('contract-place')||'Zürich');
    setInputValue('contract-date',new Date().toISOString().slice(0,10));
    var err=document.getElementById('contract-error');
    if(err){err.style.display='none';err.textContent='';}
    var btn=document.getElementById('btn-contract-save');
    if(btn){btn.textContent='Speichern';btn.disabled=false;}
  }
  function selectDecisionOption(choice){
    currentDecisionChoice=choice||'option_a';
    var ed=document.getElementById('m-ed');
    if(!ed)return;
    ed.querySelectorAll('[data-choice]').forEach(function(card){
      var active=card.dataset.choice===currentDecisionChoice;
      card.style.borderColor=active?'var(--n6)':'var(--b1)';
      card.style.background=active?'var(--n0)':'transparent';
    });
    var err=document.getElementById('ed-error');
    if(err){err.style.display='none';err.textContent='';}
  }
  function resetDecisionTemplateModal(){
    var ed=document.getElementById('m-ed');
    if(ed&&!ed.dataset.triggerId)ed.dataset.triggerId='';
    currentDecisionChoice='option_a';
    selectDecisionOption(currentDecisionChoice);
    var btn=document.getElementById('btn-ed-save');
    if(btn){btn.textContent='Dokumentieren';btn.disabled=false;}
  }
  function openDecisionTemplateModal(triggerId){
    var ed=document.getElementById('m-ed');
    if(ed)ed.dataset.triggerId=triggerId||'';
    resetDecisionTemplateModal();
    if(ed)ed.classList.add('open');
  }
  function describeWealthPosition(pos){
  if(!pos)return '';
  var parts=[];
  if(pos.position_type==='Depot'){
    if(pos.depot_bank)parts.push(pos.depot_bank);
    if(pos.depot_account_number)parts.push(pos.depot_account_number);
  } else if(pos.position_type==='Liquidität'){
    if(pos.liquidity_instrument)parts.push(pos.liquidity_instrument);
    if(pos.liquidity_interest_rate_bps!=null)parts.push(bpsToPercentText(pos.liquidity_interest_rate_bps));
    if(pos.liquidity_available_from)parts.push('ab '+pos.liquidity_available_from);
  } else if(pos.position_type==='Immobilien'){
    if(pos.property_usage)parts.push(pos.property_usage);
    if(pos.property_address)parts.push(pos.property_address);
    if(pos.valuation_date)parts.push('bewertet '+pos.valuation_date);
  } else if(pos.position_type==='Vorsorge'){
    if(pos.pension_type)parts.push(pos.pension_type);
    if(pos.pension_institution)parts.push(pos.pension_institution);
    if(pos.pension_retirement_age)parts.push('RA '+pos.pension_retirement_age);
    if(pos.pension_payout_form)parts.push(pos.pension_payout_form);
  } else if(pos.position_type==='Alternative'){
    if(pos.asset_subtype)parts.push(pos.asset_subtype);
    if(pos.asset_liquidity)parts.push(pos.asset_liquidity);
    if(pos.asset_location)parts.push(pos.asset_location);
    } else if(pos.position_type==='Hypothek'){
      if(pos.mortgage_bank)parts.push(pos.mortgage_bank);
      if(pos.mortgage_type)parts.push(pos.mortgage_type);
      if(pos.mortgage_interest_rate_bps!=null)parts.push(bpsToPercentText(pos.mortgage_interest_rate_bps));
      if(pos.mortgage_maturity_date)parts.push('bis '+pos.mortgage_maturity_date);
      var linkedPropertyLabel=getPropertyPositionLabelById(pos.mortgage_linked_property_id);
      if(linkedPropertyLabel)parts.push('Objekt '+linkedPropertyLabel);
    }
  if(pos.notes&&parts.join(' | ').indexOf(pos.notes)<0)parts.push(pos.notes);
  if(!parts.length)parts.push(pos.position_type||'Position');
  return parts.join(' · ');
}
  function wealthSharePercent(part,total){
    var numerator=Math.max(0,Number(part||0));
    var denominator=Math.max(0,Number(total||0));
    if(!denominator)return 0;
    return Math.max(0,Math.min(100,Math.round((numerator/denominator)*100)));
  }
  function prependWealthSplitSummary(meta){
    var av=document.getElementById('asset-view');
    if(!av)return;
    var grossChf=Math.max(0,Number(meta&&meta.grossChf||0));
    var advisoryChf=Math.max(0,Number(meta&&meta.advisoryChf||0));
    var otherGrossChf=Math.max(0,Number(meta&&meta.otherGrossChf||0));
    var liabilitiesChf=Math.max(0,Number(meta&&meta.liabilitiesChf||0));
    var netChf=Number(meta&&meta.netChf||0);
    var advisoryPct=wealthSharePercent(advisoryChf,grossChf);
    var otherPct=wealthSharePercent(otherGrossChf,grossChf);
    var netPct=wealthSharePercent(Math.max(0,netChf),grossChf);
    var buildStatCard=function(label,value,subline,tone){
      var colors=tone==='accent'
        ? {bg:'rgba(22,101,52,0.08)',border:'rgba(22,101,52,0.18)',value:'var(--pos)'}
        : {bg:'var(--bg)',border:'var(--b1)',value:'var(--n8)'};
      var displayValue=typeof value==='string'?value:fmtCHF(value);
      return '<div style="padding:10px 11px;border-radius:var(--r2);border:1px solid '+colors.border+';background:'+colors.bg+'">'
        + '<div style="font-size:8px;font-weight:700;letter-spacing:0.09em;text-transform:uppercase;color:var(--n4);margin-bottom:5px">'+escapeHtml(label)+'</div>'
        + '<div style="font-family:var(--f-d);font-size:18px;color:'+colors.value+'">'+escapeHtml(displayValue)+'</div>'
        + '<div style="font-size:10px;color:var(--n5);margin-top:3px;line-height:1.45">'+escapeHtml(subline)+'</div>'
        + '</div>';
    };
    var advisoryNote=String(advisoryPct||0)+'% des Bruttovermoegens · '+String(Number(meta&&meta.advisoryCount||0))+' Position(en)';
    var otherNote=String(otherPct||0)+'% ausserhalb Beratung · '+String(Number(meta&&meta.otherCount||0))+' Position(en)';
    var liabilityNote=String(grossChf?wealthSharePercent(liabilitiesChf,grossChf):0)+'% Abzug · '+String(Number(meta&&meta.liabilityCount||0))+' Verbindlichkeit(en)';
    var liabilityValue=liabilitiesChf?('−'+fmtCHF(liabilitiesChf)):'CHF 0';
    var summaryHtml='<div data-wealth-split="1" style="margin-bottom:14px;padding:12px;border:1px solid var(--b1);border-radius:var(--r2);background:linear-gradient(135deg,#fbfcff 0%,#f4f6fb 100%)">'
      + '<div style="display:grid;grid-template-columns:minmax(0,1.15fr) minmax(0,0.85fr);gap:12px;align-items:stretch">'
        + '<div style="padding:12px 14px;border-radius:var(--r2);background:linear-gradient(135deg,var(--n8) 0%,#273548 100%);color:#fff;display:flex;flex-direction:column;justify-content:space-between">'
          + '<div><div style="font-size:8px;font-weight:700;letter-spacing:0.11em;text-transform:uppercase;color:rgba(255,255,255,0.45);margin-bottom:5px">Reinvermoegen Total</div><div style="font-family:var(--f-d);font-size:26px;color:#fff">'+escapeHtml(fmtCHF(netChf))+'</div></div>'
          + '<div style="font-size:10px;line-height:1.5;color:rgba(255,255,255,0.74);margin-top:10px">Bruttovermoegen '+escapeHtml(fmtCHF(grossChf))+' · Verbindlichkeiten -'+escapeHtml(fmtCHF(liabilitiesChf))+' · Nettoquote '+String(netPct)+'%</div>'
        + '</div>'
        + '<div style="display:grid;grid-template-columns:1fr;gap:8px">'
          + buildStatCard('Beratungsvermoegen',advisoryChf,advisoryNote,'accent')
          + buildStatCard('Holistischer Rest',otherGrossChf,otherNote,'default')
          + buildStatCard('Verbindlichkeiten',liabilityValue,liabilityNote,'default')
        + '</div>'
      + '</div>'
      + '<div style="display:grid;grid-template-columns:minmax(0,1fr) minmax(0,0.9fr);gap:12px;margin-top:12px">'
        + '<div style="padding:10px 11px;border-radius:var(--r2);border:1px solid var(--b1);background:#fff">'
          + '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px"><span style="font-size:9px;font-weight:700;letter-spacing:0.08em;text-transform:uppercase;color:var(--n4)">Split Bruttovermoegen</span><span style="font-size:10px;color:var(--n5)">Beratung vs. Rest</span></div>'
          + '<div style="height:12px;border-radius:999px;overflow:hidden;background:var(--bg2);display:flex">'
            + '<div style="width:'+String(advisoryPct)+'%;background:linear-gradient(90deg,#166534 0%,#2d7a46 100%)"></div>'
            + '<div style="width:'+String(otherPct)+'%;background:linear-gradient(90deg,#c9a84c 0%,#d6ba67 100%)"></div>'
          + '</div>'
          + '<div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-top:8px">'
            + '<div style="font-size:10px;color:var(--n6)"><span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:#1f6a3b;margin-right:5px"></span>Beratung '+escapeHtml(fmtCHF(advisoryChf))+'</div>'
            + '<div style="font-size:10px;color:var(--n6)"><span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:#c9a84c;margin-right:5px"></span>Rest '+escapeHtml(fmtCHF(otherGrossChf))+'</div>'
          + '</div>'
        + '</div>'
        + '<div style="padding:10px 11px;border-radius:var(--r2);border:1px solid var(--b1);background:#fff">'
          + '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px"><span style="font-size:9px;font-weight:700;letter-spacing:0.08em;text-transform:uppercase;color:var(--n4)">Netto nach Verbindlichkeiten</span><span style="font-size:10px;color:var(--n5)">Holistische Sicht</span></div>'
          + '<div style="height:12px;border-radius:999px;overflow:hidden;background:#f3e8e8;position:relative"><div style="width:'+String(netPct)+'%;height:100%;background:linear-gradient(90deg,var(--n8) 0%,#3c4b62 100%)"></div></div>'
          + '<div style="font-size:10px;color:var(--n6);line-height:1.5;margin-top:8px">Das Beratungsvermoegen ist der optimierbare Teil. Gesamtvermoegen und Verbindlichkeiten bleiben fuer Tragfaehigkeit, Zielplanung und Konzentrationssicht voll sichtbar.</div>'
        + '</div>'
      + '</div>'
    + '</div>';
    var existing=av.querySelector('[data-wealth-split="1"]');
    if(existing)existing.remove();
    av.insertAdjacentHTML('afterbegin',summaryHtml);
  }
  function renderWealthPositions(positions){
    var items=(Array.isArray(positions)?positions:[]).filter(function(pos){
      return pos&&(!Object.prototype.hasOwnProperty.call(pos,'is_active')||pos.is_active!==0);
    });
    currentWealthPositions=items.slice();
    updateMortgageLinkedPropertyOptions();
    var av=document.getElementById('asset-view');
    if(!av)return;
    var advisory=items.filter(function(pos){return pos.assignment==='Beratungsvermögen';});
  var other=items.filter(function(pos){return pos.assignment==='Anderes Vermögen';});
  var liabilities=items.filter(function(pos){return pos.assignment==='Verbindlichkeit';});
  var totalChf=function(list){
    return list.reduce(function(sum,pos){return sum+chfFromRappen(pos.current_value_rappen);},0);
  };
  var renderRows=function(list,tagClass,tagLabel,isLiability){
    if(!list.length)return '<div style="font-size:10px;color:var(--n4);padding:4px 0 8px">Noch keine Positionen erfasst.</div>';
    return list.map(function(pos){
      var amountText=(isLiability?'−':'')+fmtCHF(Math.abs(chfFromRappen(pos.current_value_rappen)));
      return '<div class="wr" data-posid="'+escapeHtml(pos.id||'')+'">'+
        '<div class="wn"><div class="wna">'+escapeHtml(pos.label||'Position')+'</div><div class="wnd">'+escapeHtml(describeWealthPosition(pos))+'</div></div>'+
        '<div class="wa"'+(isLiability?' style="color:var(--neg)"':'')+'>'+amountText+'</div>'+
        '<div class="wt"><span class="tag '+tagClass+'">'+tagLabel+'</span></div>'+
        '<div><button class="btn-ico e" onclick="openWealthPositionEditor(\''+escapeHtml(pos.id||'')+'\')" title="Bearbeiten">✎</button><button class="btn-ico" onclick="deleteWealthPositionById(\''+escapeHtml(pos.id||'')+'\')" title="Löschen">✕</button></div></div>';
    }).join('');
  };
  var advisoryTotal=totalChf(advisory);
  var otherTotal=totalChf(other)-totalChf(liabilities);
  var netWorth=advisoryTotal+otherTotal;
  var grossWealth=advisoryTotal+totalChf(other);
  var liabilitiesTotal=totalChf(liabilities);
  av.innerHTML=
    '<div style="margin-bottom:10px">'+
      '<div style="font-size:9px;font-weight:600;letter-spacing:0.07em;text-transform:uppercase;color:var(--n6);margin-bottom:5px;padding-bottom:3px;border-bottom:1px solid var(--b1)">Beratungsvermögen</div>'+
      renderRows(advisory,'tb','Beratung',false)+
      '<div style="display:flex;justify-content:space-between;padding:6px 0 0;border-top:1px solid var(--b1);margin-top:2px"><span style="font-size:11px;font-weight:600">Total Beratungsvermögen</span><span style="font-family:var(--f-d);font-size:15px;color:var(--pos)">'+fmtCHF(advisoryTotal)+'</span></div>'+
    '</div>'+
    '<div>'+
      '<div style="font-size:9px;font-weight:600;letter-spacing:0.07em;text-transform:uppercase;color:var(--n4);margin-bottom:5px;padding-bottom:3px;border-bottom:1px solid var(--b1)">Anderes Vermögen (holistischer Überblick)</div>'+
      renderRows(other,'tn','Andere',false)+
      renderRows(liabilities,'tr2','Verbindl.',true)+
      '<div style="display:flex;justify-content:space-between;padding:6px 0 0;border-top:1px solid var(--b1);margin-top:2px"><span style="font-size:11px;font-weight:600">Total Anderes (netto)</span><span style="font-family:var(--f-d);font-size:15px;color:var(--n8)">'+fmtCHF(otherTotal)+'</span></div>'+
    '</div>'+
    '<div style="display:flex;justify-content:space-between;padding:9px 0 0;border-top:2px solid var(--n8);margin-top:7px">'+
      '<span style="font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:0.04em">Reinvermögen Total</span>'+
      '<span style="font-family:var(--f-d);font-size:20px;color:var(--n8)">'+fmtCHF(netWorth)+'</span></div>';
  prependWealthSplitSummary({
    netChf:netWorth,
    grossChf:grossWealth,
    advisoryChf:advisoryTotal,
    otherGrossChf:totalChf(other),
    liabilitiesChf:liabilitiesTotal,
    advisoryCount:advisory.length,
    otherCount:other.length,
    liabilityCount:liabilities.length
  });
}
var allocationPreferencesCache={};
var allocationPreferenceStoragePrefix='5eyes.allocprefs.';
var allocationBandBaseline={};
function getAllocationPreferenceKey(){
  var mid=getActiveMandateId();
  if(mid)return 'mandate:'+mid;
  var cid=getActiveClientId();
  if(cid)return (isDemoClientId(cid)?'demo:':'client:')+cid;
  if(currentPersona&&currentPersona.id)return 'persona:'+currentPersona.id;
  return 'default';
}
function buildDefaultAllocationPreferences(){
  var prefs={
    policy:{esg:'esg_integration',universe:'standard',homeBias:'ch_focus',hedging:'none'},
    tilts:{fossil:'neutral',defense:'neutral',tobacco:'neutral',alcohol:'neutral',gaming:'neutral',nuclear:'neutral'},
    product:{noDerivatives:false,noLeverage:false,noStructured:false,listedOnly:false,fundsOnly:false},
    limits:{singlePosition:'',singleIssuer:'',minReserve:'',maxIlliquid:''},
    geo:{chFocus:false,noEm:false,hedgingRequired:false,chfOnly:false,noUsd:false},
    bands:{},
    simulation:{horizonYears:'10',stressMultiplier:'1.0',rebalanceMode:'bands',monteCarloRuns:'750'},
    assetClasses:{
      equitiesGeo:'Schweiz Fokus',
      equitiesLargeCap:true,
      equitiesSmid:false,
      bondsDuration:'Langfristig',
      bondsInvestmentGrade:true,
      bondsHighYield:false,
      bondsEmerging:false,
      realestateMarket:'Schweiz',
      realestateFunds:true,
      realestateDirect:false,
      altsGold:true,
      altsLiquidAlts:false,
      altsHedge:false,
      altsPe:false,
      altsCrypto:false,
      liquidityInstrument:'Geldmarktfonds',
      liquidityReserveTarget:'',
    },
  };
  if(currentPersona&&currentPersona.preferences){
    var personaPrefs=currentPersona.preferences;
    if(String(personaPrefs.esg||'').toLowerCase().includes('neutral'))prefs.policy.esg='none';
    if(String(personaPrefs.homeBias||'').toLowerCase().includes('ch'))prefs.policy.homeBias='ch_focus';
  }
  return prefs;
}
function loadAllocationPreferences(){
  var key=getAllocationPreferenceKey();
  if(allocationPreferencesCache[key])return allocationPreferencesCache[key];
  var prefs=buildDefaultAllocationPreferences();
  try{
    var raw=localStorage.getItem(allocationPreferenceStoragePrefix+key);
    if(raw){
      var stored=JSON.parse(raw);
      if(stored&&typeof stored==='object')prefs=mergeAllocationPreferences(prefs,stored);
    }
  }catch(e){}
  allocationPreferencesCache[key]=prefs;
  return prefs;
}
function cloneJSON(value){
  try{return JSON.parse(JSON.stringify(value||{}));}catch(e){return value||{};}
}
function mergeAllocationPreferences(base,override){
  var merged=cloneJSON(base);
  var incoming=override&&typeof override==='object'?override:{};
  ['policy','tilts','product','limits','geo','bands','simulation','assetClasses'].forEach(function(section){
    if(incoming[section]&&typeof incoming[section]==='object'){
      merged[section]=Object.assign({},merged[section]||{},incoming[section]);
    }else if(merged[section]==null){
      merged[section]={};
    }
  });
  return merged;
}
function formatBandPercent(bps){
  var pct=Number(bps||0)/100;
  return (Math.abs(pct-Math.round(pct))<0.05?String(Math.round(pct)):pct.toFixed(1))+'%';
}
function parseBandPercentInput(value){
  if(typeof value==='number'&&isFinite(value))return Math.round(Math.abs(value)>100?value:value*100);
  var raw=String(value||'').replace('%','').replace(/'/g,'').replace(/\s+/g,'').replace(',','.').trim();
  if(!raw)return null;
  var numeric=Number(raw);
  if(!isFinite(numeric))return null;
  return Math.round(Math.abs(numeric)>100?numeric:numeric*100);
}
function normalizeBandOverrideEntry(entry){
  if(!entry||typeof entry!=='object')return null;
  var minimum=parseBandPercentInput(entry.min_bps);
  var target=parseBandPercentInput(entry.target_bps);
  var maximum=parseBandPercentInput(entry.max_bps);
  if(minimum==null&&target==null&&maximum==null)return null;
  return {
    min_bps:minimum==null?null:minimum,
    target_bps:target==null?null:target,
    max_bps:maximum==null?null:maximum,
  };
}
function normalizeBandKey(value){
  var raw=String(value||'').toLowerCase();
  var map={
    aktien:'equities',
    equities:'equities',
    obligationen:'bonds',
    bonds:'bonds',
    immobilien:'real_estate',
    real_estate:'real_estate',
    alternative:'alternatives',
    alternatives:'alternatives',
    liquiditaet:'liquidity',
    liquidity:'liquidity',
  };
  return map[raw]||raw;
}
function collectBandOverridesFromModal(){
  var inputs=document.querySelectorAll('#qt-modal .qtinp[data-bucket][data-field]');
  if(!inputs.length)return null;
  var collected={};
  inputs.forEach(function(input){
    var bucket=normalizeBandKey(input.getAttribute('data-bucket'));
    var field=String(input.getAttribute('data-field')||'');
    if(!bucket||!field)return;
    if(!collected[bucket])collected[bucket]={};
    collected[bucket][field]=input.value;
  });
  var overrides={};
  Object.keys(collected).forEach(function(bucket){
    var normalized=normalizeBandOverrideEntry(collected[bucket]);
    var baseline=allocationBandBaseline[bucket]||{};
    if(!normalized)return;
    var minimum=normalized.min_bps==null?baseline.min_bps:normalized.min_bps;
    var target=normalized.target_bps==null?baseline.target_bps:normalized.target_bps;
    var maximum=normalized.max_bps==null?baseline.max_bps:normalized.max_bps;
    if(minimum===baseline.min_bps&&target===baseline.target_bps&&maximum===baseline.max_bps)return;
    overrides[bucket]={
      min_bps:minimum,
      target_bps:target,
      max_bps:maximum,
    };
  });
  return overrides;
}
function hasCanonicalBandBaseline(){
  return ['equities','bonds','real_estate','alternatives','liquidity'].every(function(key){
    return !!allocationBandBaseline[key];
  });
}
function countBandOverrides(bands){
  return Object.keys(bands||{}).filter(function(key){
    return !!normalizeBandOverrideEntry(bands[key]);
  }).length;
}
function updateBandOverrideStatus(bands){
  var status=document.getElementById('aa-band-status');
  if(!status)return;
  var activeBands=bands;
  if(activeBands==null){
    var prefs=loadAllocationPreferences();
    activeBands=prefs&&prefs.bands?prefs.bands:{};
  }
  var count=countBandOverrides(activeBands);
  if(!count){
    status.textContent='House-Matrix-Basis aktiv. Individuelle Overrides werden nur gesendet, wenn sie von der aktuellen Engine-Basis abweichen.';
    status.style.color='var(--n4)';
    return;
  }
  status.textContent='Individuelle Bandbreiten aktiv fuer '+count+' Asset-Klasse(n). Diese Overrides werden in die naechste Engine-Berechnung uebernommen.';
  status.style.color='var(--n6)';
}
function ensureAllocationRuntimePanels(){
  var page=document.getElementById('page-al');
  if(!page)return;
  if(!document.getElementById('aa-engine-grid')){
    var status=document.getElementById('aa-pref-status');
    if(status&&status.parentNode&&status.parentNode.parentNode){
      var host=status.parentNode.parentNode;
      var wrap=document.createElement('div');
      wrap.className='g2';
      wrap.style.margin='0 24px 16px';
      wrap.innerHTML=''
        + '<div class="card">'
        + '<div class="chd"><span class="cht">Engine & Markt-Setup</span><span style="font-size:9px;color:var(--n4)">Risikobudget, House Matrix, Liquiditaet und Marktdaten</span></div>'
        + '<div class="cbody">'
        + '<div id="aa-engine-grid" style="display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin-bottom:10px"></div>'
        + '<div style="padding-top:8px;border-top:1px solid var(--b1)"><div style="font-size:9px;text-transform:uppercase;letter-spacing:0.07em;color:var(--n4);margin-bottom:6px">Engine-Reasoning</div><div id="aa-engine-rationale" style="display:flex;flex-direction:column;gap:6px"></div></div>'
        + '<div style="padding-top:8px;border-top:1px solid var(--b1);margin-top:10px"><div style="font-size:9px;text-transform:uppercase;letter-spacing:0.07em;color:var(--n4);margin-bottom:6px">Marktdaten & Kapitalmarktannahmen</div><div id="aa-market-runtime" style="display:flex;flex-direction:column;gap:6px"></div></div>'
        + '<div style="padding-top:8px;border-top:1px solid var(--b1);margin-top:10px"><div style="font-size:9px;text-transform:uppercase;letter-spacing:0.07em;color:var(--n4);margin-bottom:6px">Live-Drift & Rebalancing</div><div id="aa-live-summary" style="display:flex;flex-direction:column;gap:6px"></div><div id="aa-live-assets" style="display:flex;flex-direction:column;gap:5px;margin-top:8px"></div><div id="aa-live-positions" style="display:flex;flex-direction:column;gap:5px;margin-top:8px"></div></div>'
        + '<div style="padding-top:8px;border-top:1px solid var(--b1);margin-top:10px"><div style="font-size:9px;text-transform:uppercase;letter-spacing:0.07em;color:var(--n4);margin-bottom:6px">Simulation & Rebalancing</div><div id="aa-sim-events" style="display:flex;flex-direction:column;gap:6px"></div></div>'
        + '<div style="padding-top:8px;border-top:1px solid var(--b1);margin-top:10px"><div style="font-size:9px;text-transform:uppercase;letter-spacing:0.07em;color:var(--n4);margin-bottom:6px">Monte Carlo</div><div id="aa-mc-summary" style="display:flex;flex-direction:column;gap:6px"></div></div>'
        + '<div style="padding-top:8px;border-top:1px solid var(--b1);margin-top:10px"><div style="font-size:9px;text-transform:uppercase;letter-spacing:0.07em;color:var(--n4);margin-bottom:6px">Zielpfade</div><div id="aa-mc-goals" style="display:flex;flex-direction:column;gap:6px"></div></div>'
        + '</div></div>'
        + '<div class="card">'
        + '<div class="chd"><span class="cht">Building Blocks & Risk Weights</span><span style="font-size:9px;color:var(--n4)">Subanlageklassen, Zielquote und Risky Fraction</span></div>'
        + '<div class="cbody">'
        + '<div style="font-size:9px;text-transform:uppercase;letter-spacing:0.07em;color:var(--n4);margin-bottom:6px">Asset-Class-Annahmen</div><div id="aa-assumption-table" style="display:flex;flex-direction:column;gap:5px"></div>'
        + '<div style="padding-top:8px;border-top:1px solid var(--b1);margin-top:10px"><div style="font-size:9px;text-transform:uppercase;letter-spacing:0.07em;color:var(--n4);margin-bottom:6px">Aktive Subanlageklassen</div><div id="aa-suballoc-table" style="display:flex;flex-direction:column;gap:5px"></div></div>'
        + '<div style="padding-top:8px;border-top:1px solid var(--b1);margin-top:10px"><div style="font-size:9px;text-transform:uppercase;letter-spacing:0.07em;color:var(--n4);margin-bottom:6px">Hinterlegte Risiko-Gewichte</div><div id="aa-block-reference" style="display:flex;flex-direction:column;gap:5px;max-height:240px;overflow:auto;padding-right:4px"></div></div>'
        + '</div></div>';
      host.insertAdjacentElement('afterend',wrap);
    }
  }
  var modal=document.getElementById('m-eq');
  if(modal){
    var footer=modal.querySelector('.mfooter');
    if(footer&&!footer.getAttribute('data-bandwired')){
      footer.setAttribute('data-bandwired','1');
      var primary=footer.querySelector('.btn-p');
      var secondary=footer.querySelector('.btn');
      if(primary)primary.setAttribute('onclick','applyAllocationBandOverrides()');
      if(secondary&&String(secondary.textContent||'').toLowerCase().indexOf('schliessen')>=0){
        var reset=document.createElement('button');
        reset.className='btn';
        reset.textContent='Zuruecksetzen';
        reset.setAttribute('onclick','resetAllocationBandOverrides()');
        footer.insertBefore(reset,secondary);
      }
    }
    var body=modal.querySelector('.mbody');
    if(body&&!document.getElementById('aa-band-status')){
      var statusBox=document.createElement('div');
      statusBox.id='aa-band-status';
      statusBox.style.fontSize='10px';
      statusBox.style.color='var(--n4)';
      statusBox.style.marginTop='10px';
      statusBox.textContent='House-Matrix-Basis aktiv. Individuelle Overrides werden nur gesendet, wenn sie von der aktuellen Engine-Basis abweichen.';
      body.appendChild(statusBox);
    }
  }
}
function setInputValue(id,value){
  var el=document.getElementById(id);
  if(el)el.value=value==null?'':String(value);
}
function setSelectValue(id,value){
  var el=document.getElementById(id);
  if(el&&value!=null)el.value=value;
}
function setCheckboxValue(id,value){
  var el=document.getElementById(id);
  if(el)el.checked=!!value;
}
function setRadioValue(name,value){
  document.querySelectorAll('input[name="'+name+'"]').forEach(function(el){
    el.checked=String(el.value||'')===String(value||'');
  });
}
function renderPreferenceChips(targetId,items,variant){
  var el=document.getElementById(targetId);
  if(!el)return;
  var palette=variant==='restriction'
    ? 'background:rgba(14,107,65,0.08);border:1px solid rgba(14,107,65,0.3);color:var(--pos);'
    : 'background:rgba(42,74,112,0.08);border:1px solid rgba(42,74,112,0.2);color:var(--n6);';
  var chips=(items||[]).filter(Boolean);
  if(!chips.length)chips=[variant==='restriction'?'Keine aktiven Restriktionen':'Keine Präferenzen gesetzt'];
  el.innerHTML=chips.map(function(item){
    return '<span style="font-size:10px;padding:3px 8px;'+palette+'border-radius:var(--r2)">'+escapeHtml(item)+'</span>';
  }).join('');
  Array.prototype.forEach.call(grid.querySelectorAll('button[onclick="printReport()"]'),function(btn,idx){
    var doc=docs[idx];
    if(!doc)return;
    btn.textContent='Kapitel drucken';
    btn.setAttribute('onclick',"printDocumentTypeReport('"+String(doc.document_type||'Dokument').replace(/'/g,"\\'")+"')");
  });
}
function renderAllocationPreferenceSummary(prefs){
  if(!prefs)return;
  var esgLabels={
    none:'Keine ESG-Präferenz',
    esg_integration:'ESG-Integration',
    best_in_class:'Best-in-Class',
    negative_screening:'Negativ-Screening',
    impact:'Impact Investing',
    net_zero:'Paris-aligned / Net Zero'
  };
  var universeLabels={standard:'Standard',extended:'Erweitert',funds_only:'Nur Fonds/ETFs',listed_only:'Nur kotierte Instrumente'};
  var homeBiasLabels={none:'Kein Heimmarkt-Bias',ch_focus:'CH-Fokus bevorzugt',europe_focus:'Europa-Fokus',global:'Global neutral'};
  var hedgingLabels={none:'Keine FX-Vorgabe',hedged:'FX-gehedgt bevorzugt',chf_only:'Nur CHF-Instrumente',risk_budget:'FX ausserhalb Risiko-Budget'};
  var tiltActionLabels={exclude:'Ausschliessen',underweight:'Untergewichten',overweight:'Übergewichten'};
  var tiltNames={fossil:'Fossile Energie',defense:'Verteidigung',tobacco:'Tabak',alcohol:'Alkohol',gaming:'Glücksspiel',nuclear:'Kernenergie'};
  var altPrefs=['Gold / Rohstoffe','Liquid Alternatives','Hedge Funds','Private Equity','Krypto'].filter(function(label,idx){
    return [prefs.assetClasses.altsGold,prefs.assetClasses.altsLiquidAlts,prefs.assetClasses.altsHedge,prefs.assetClasses.altsPe,prefs.assetClasses.altsCrypto][idx];
  });
  var summary=[
    esgLabels[prefs.policy.esg]||'ESG-Integration',
    'Universum: '+(universeLabels[prefs.policy.universe]||'Standard'),
    'Heimmarkt: '+(homeBiasLabels[prefs.policy.homeBias]||'CH-Fokus bevorzugt'),
    hedgingLabels[prefs.policy.hedging]||'Keine FX-Vorgabe'
  ];
  var focus=[
    'Aktien: '+(prefs.assetClasses.equitiesGeo||'Schweiz Fokus'),
    'Obligationen: '+(prefs.assetClasses.bondsDuration||'Langfristig'),
    'Immobilien: '+(prefs.assetClasses.realestateMarket||'Schweiz'),
    'Alternative: '+(altPrefs.length?altPrefs.join(' + '):'keine Schwerpunkte'),
    'Liquidität: '+(prefs.assetClasses.liquidityInstrument||'Geldmarktfonds'),
    'Simulation: '+String((prefs.simulation&&prefs.simulation.horizonYears)||'10')+' J / '
      +(prefs.simulation&&prefs.simulation.rebalanceMode==='calendar'?'jaehrlich':(prefs.simulation&&prefs.simulation.rebalanceMode==='none'?'ohne Rebalancing':'bei Bandbruch'))
      +' / Stress '+String((prefs.simulation&&prefs.simulation.stressMultiplier)||'1.0')+'x'
      +' / MC '+String((prefs.simulation&&prefs.simulation.monteCarloRuns)||'750')
  ];
  var restrictions=[];
  if(prefs.policy.esg&&prefs.policy.esg!=='none')restrictions.push('✓ '+(esgLabels[prefs.policy.esg]||'ESG-Integration'));
  if(prefs.product.noDerivatives)restrictions.push('✓ Keine Derivate');
  if(prefs.product.noLeverage)restrictions.push('✓ Keine Hebelprodukte');
  if(prefs.product.noStructured)restrictions.push('✓ Keine Strukturierten');
  if(prefs.product.listedOnly)restrictions.push('✓ Nur kotierte Titel');
  if(prefs.product.fundsOnly)restrictions.push('✓ Nur Fonds/ETFs');
  if(prefs.geo.chFocus)restrictions.push('✓ CH-Fokus');
  if(prefs.geo.noEm)restrictions.push('✓ Kein EM-Exposure');
  if(prefs.geo.hedgingRequired)restrictions.push('✓ FX-Absicherung obligatorisch');
  if(prefs.geo.chfOnly)restrictions.push('✓ Nur CHF-Instrumente');
  if(prefs.geo.noUsd)restrictions.push('✓ Kein USD');
  Object.keys(prefs.tilts||{}).forEach(function(key){
    var mode=prefs.tilts[key];
    if(mode&&mode!=='neutral'&&tiltNames[key])restrictions.push(tiltActionLabels[mode]+' '+tiltNames[key]);
  });
  if(countBandOverrides(prefs.bands||{}))restrictions.push('Individuelle Bandbreiten aktiv');
  renderPreferenceChips('sd-pref-summary',summary,'summary');
  renderPreferenceChips('sr-pref-focus-chips',focus,'summary');
  renderPreferenceChips('sr-pref-restriction-chips',restrictions,'restriction');
  updateBandOverrideStatus(prefs.bands||{});
}
function collectAllocationPreferencesFromUI(){
  var stored=loadAllocationPreferences();
  var prefs=mergeAllocationPreferences(buildDefaultAllocationPreferences(),stored);
  var live={
    policy:{
      esg:getInputValue('aa-policy-esg')||'esg_integration',
      universe:getInputValue('aa-policy-universe')||'standard',
      homeBias:getInputValue('aa-policy-home-bias')||'ch_focus',
      hedging:getInputValue('aa-policy-hedging')||'none',
    },
    tilts:{
      fossil:getInputValue('aa-tilt-fossil')||'neutral',
      defense:getInputValue('aa-tilt-defense')||'neutral',
      tobacco:getInputValue('aa-tilt-tobacco')||'neutral',
      alcohol:getInputValue('aa-tilt-alcohol')||'neutral',
      gaming:getInputValue('aa-tilt-gaming')||'neutral',
      nuclear:getInputValue('aa-tilt-nuclear')||'neutral',
    },
    product:{
      noDerivatives:getCheckboxValue('aa-product-no-derivatives'),
      noLeverage:getCheckboxValue('aa-product-no-leverage'),
      noStructured:getCheckboxValue('aa-product-no-structured'),
      listedOnly:getCheckboxValue('aa-product-listed-only'),
      fundsOnly:getCheckboxValue('aa-product-funds-only'),
    },
    limits:{
      singlePosition:getInputValue('aa-limit-single-position'),
      singleIssuer:getInputValue('aa-limit-single-issuer'),
      minReserve:getInputValue('aa-liquidity-min-reserve'),
      maxIlliquid:getInputValue('aa-liquidity-max-illiquid'),
    },
    geo:{
      chFocus:getCheckboxValue('aa-geo-ch-focus'),
      noEm:getCheckboxValue('aa-geo-no-em'),
      hedgingRequired:getCheckboxValue('aa-geo-hedging-required'),
      chfOnly:getCheckboxValue('aa-geo-chf-only'),
      noUsd:getCheckboxValue('aa-geo-no-usd'),
    },
    simulation:{
      horizonYears:getInputValue('aa-sim-horizon')||'10',
      stressMultiplier:getInputValue('aa-sim-stress')||'1.0',
      rebalanceMode:getInputValue('aa-sim-rebalance')||'bands',
      monteCarloRuns:getInputValue('aa-sim-mc-runs')||'750',
    },
    assetClasses:{
      equitiesGeo:getRadioValue('aa-equities-geo','Schweiz Fokus'),
      equitiesLargeCap:getCheckboxValue('aa-equities-large-cap'),
      equitiesSmid:getCheckboxValue('aa-equities-smid'),
      bondsDuration:getRadioValue('aa-bonds-duration','Langfristig'),
      bondsInvestmentGrade:getCheckboxValue('aa-bonds-investment-grade'),
      bondsHighYield:getCheckboxValue('aa-bonds-high-yield'),
      bondsEmerging:getCheckboxValue('aa-bonds-emerging'),
      realestateMarket:getRadioValue('aa-realestate-market','Schweiz'),
      realestateFunds:getCheckboxValue('aa-realestate-funds'),
      realestateDirect:getCheckboxValue('aa-realestate-direct'),
      altsGold:getCheckboxValue('aa-alts-gold'),
      altsLiquidAlts:getCheckboxValue('aa-alts-liquid-alts'),
      altsHedge:getCheckboxValue('aa-alts-hedge'),
      altsPe:getCheckboxValue('aa-alts-pe'),
      altsCrypto:getCheckboxValue('aa-alts-crypto'),
      liquidityInstrument:getRadioValue('aa-liquidity-instrument','Geldmarktfonds'),
      liquidityReserveTarget:getInputValue('aa-liquidity-reserve-target'),
    },
  };
  prefs.policy=live.policy;
  prefs.tilts=live.tilts;
  prefs.product=live.product;
  prefs.limits=live.limits;
  prefs.geo=live.geo;
  prefs.simulation=live.simulation;
  prefs.assetClasses=live.assetClasses;
  var modal=document.getElementById('m-eq');
  var modalBands=(modal&&modal.classList.contains('open')&&hasCanonicalBandBaseline())?collectBandOverridesFromModal():null;
  prefs.bands=modalBands==null?(prefs.bands||{}):modalBands;
  return prefs;
}
function applyAllocationPreferencesToUI(prefs){
  if(!prefs)return;
  setSelectValue('aa-policy-esg',prefs.policy&&prefs.policy.esg);
  setSelectValue('aa-policy-universe',prefs.policy&&prefs.policy.universe);
  setSelectValue('aa-policy-home-bias',prefs.policy&&prefs.policy.homeBias);
  setSelectValue('aa-policy-hedging',prefs.policy&&prefs.policy.hedging);
  setSelectValue('aa-tilt-fossil',prefs.tilts&&prefs.tilts.fossil);
  setSelectValue('aa-tilt-defense',prefs.tilts&&prefs.tilts.defense);
  setSelectValue('aa-tilt-tobacco',prefs.tilts&&prefs.tilts.tobacco);
  setSelectValue('aa-tilt-alcohol',prefs.tilts&&prefs.tilts.alcohol);
  setSelectValue('aa-tilt-gaming',prefs.tilts&&prefs.tilts.gaming);
  setSelectValue('aa-tilt-nuclear',prefs.tilts&&prefs.tilts.nuclear);
  setCheckboxValue('aa-product-no-derivatives',prefs.product&&prefs.product.noDerivatives);
  setCheckboxValue('aa-product-no-leverage',prefs.product&&prefs.product.noLeverage);
  setCheckboxValue('aa-product-no-structured',prefs.product&&prefs.product.noStructured);
  setCheckboxValue('aa-product-listed-only',prefs.product&&prefs.product.listedOnly);
  setCheckboxValue('aa-product-funds-only',prefs.product&&prefs.product.fundsOnly);
  setSelectValue('aa-limit-single-position',prefs.limits&&prefs.limits.singlePosition);
  setSelectValue('aa-limit-single-issuer',prefs.limits&&prefs.limits.singleIssuer);
  setSelectValue('aa-liquidity-min-reserve',prefs.limits&&prefs.limits.minReserve);
  setSelectValue('aa-liquidity-max-illiquid',prefs.limits&&prefs.limits.maxIlliquid);
  setCheckboxValue('aa-geo-ch-focus',prefs.geo&&prefs.geo.chFocus);
  setCheckboxValue('aa-geo-no-em',prefs.geo&&prefs.geo.noEm);
  setCheckboxValue('aa-geo-hedging-required',prefs.geo&&prefs.geo.hedgingRequired);
  setCheckboxValue('aa-geo-chf-only',prefs.geo&&prefs.geo.chfOnly);
  setCheckboxValue('aa-geo-no-usd',prefs.geo&&prefs.geo.noUsd);
  setSelectValue('aa-sim-horizon',prefs.simulation&&prefs.simulation.horizonYears);
  setSelectValue('aa-sim-stress',prefs.simulation&&prefs.simulation.stressMultiplier);
  setSelectValue('aa-sim-rebalance',prefs.simulation&&prefs.simulation.rebalanceMode);
  setSelectValue('aa-sim-mc-runs',prefs.simulation&&prefs.simulation.monteCarloRuns);
  setRadioValue('aa-equities-geo',prefs.assetClasses&&prefs.assetClasses.equitiesGeo);
  setCheckboxValue('aa-equities-large-cap',prefs.assetClasses&&prefs.assetClasses.equitiesLargeCap);
  setCheckboxValue('aa-equities-smid',prefs.assetClasses&&prefs.assetClasses.equitiesSmid);
  setRadioValue('aa-bonds-duration',prefs.assetClasses&&prefs.assetClasses.bondsDuration);
  setCheckboxValue('aa-bonds-investment-grade',prefs.assetClasses&&prefs.assetClasses.bondsInvestmentGrade);
  setCheckboxValue('aa-bonds-high-yield',prefs.assetClasses&&prefs.assetClasses.bondsHighYield);
  setCheckboxValue('aa-bonds-emerging',prefs.assetClasses&&prefs.assetClasses.bondsEmerging);
  setRadioValue('aa-realestate-market',prefs.assetClasses&&prefs.assetClasses.realestateMarket);
  setCheckboxValue('aa-realestate-funds',prefs.assetClasses&&prefs.assetClasses.realestateFunds);
  setCheckboxValue('aa-realestate-direct',prefs.assetClasses&&prefs.assetClasses.realestateDirect);
  setCheckboxValue('aa-alts-gold',prefs.assetClasses&&prefs.assetClasses.altsGold);
  setCheckboxValue('aa-alts-liquid-alts',prefs.assetClasses&&prefs.assetClasses.altsLiquidAlts);
  setCheckboxValue('aa-alts-hedge',prefs.assetClasses&&prefs.assetClasses.altsHedge);
  setCheckboxValue('aa-alts-pe',prefs.assetClasses&&prefs.assetClasses.altsPe);
  setCheckboxValue('aa-alts-crypto',prefs.assetClasses&&prefs.assetClasses.altsCrypto);
  setRadioValue('aa-liquidity-instrument',prefs.assetClasses&&prefs.assetClasses.liquidityInstrument);
  setSelectValue('aa-liquidity-reserve-target',prefs.assetClasses&&prefs.assetClasses.liquidityReserveTarget);
  renderAllocationPreferenceSummary(prefs);
}
function persistAllocationPreferences(prefs){
  prefs=prefs||collectAllocationPreferencesFromUI();
  var key=getAllocationPreferenceKey();
  allocationPreferencesCache[key]=prefs;
  if(currentPersona)currentPersona.allocation_preferences=prefs;
  try{localStorage.setItem(allocationPreferenceStoragePrefix+key,JSON.stringify(prefs));}catch(e){}
  renderAllocationPreferenceSummary(prefs);
  updateBandOverrideStatus(prefs.bands||{});
  var status=document.getElementById('aa-pref-status');
  if(status)status.textContent='Mandatspräferenzen lokal aktualisiert: '+new Date().toLocaleTimeString('de-CH',{hour:'2-digit',minute:'2-digit'});
}
function syncAllocationPreferences(){
  ensureAllocationRuntimePanels();
  applyAllocationPreferencesToUI(loadAllocationPreferences());
  buildQT('qt-modal');
}
function bindAllocationPreferenceControls(){
  var selectors=[
    '#aa-policy-esg','#aa-policy-universe','#aa-policy-home-bias','#aa-policy-hedging',
    '#aa-tilt-fossil','#aa-tilt-defense','#aa-tilt-tobacco','#aa-tilt-alcohol','#aa-tilt-gaming','#aa-tilt-nuclear',
    '#aa-product-no-derivatives','#aa-product-no-leverage','#aa-product-no-structured','#aa-product-listed-only','#aa-product-funds-only',
    '#aa-limit-single-position','#aa-limit-single-issuer','#aa-liquidity-min-reserve','#aa-liquidity-max-illiquid',
    '#aa-geo-ch-focus','#aa-geo-no-em','#aa-geo-hedging-required','#aa-geo-chf-only','#aa-geo-no-usd',
    '#aa-sim-horizon','#aa-sim-stress','#aa-sim-rebalance','#aa-sim-mc-runs',
    '#aa-equities-large-cap','#aa-equities-smid','#aa-bonds-investment-grade','#aa-bonds-high-yield','#aa-bonds-emerging',
    '#aa-realestate-funds','#aa-realestate-direct','#aa-alts-gold','#aa-alts-liquid-alts','#aa-alts-hedge','#aa-alts-pe','#aa-alts-crypto',
    '#aa-liquidity-reserve-target'
  ];
  document.querySelectorAll(selectors.join(',')).forEach(function(el){
    el.addEventListener('change',function(){persistAllocationPreferences();markStrategyDirty('MandatsprÃ¤ferenzen aktualisiert: Strategie neu berechnen.');});
    el.addEventListener('input',function(){persistAllocationPreferences();markStrategyDirty('MandatsprÃ¤ferenzen aktualisiert: Strategie neu berechnen.');});
  });
  [
    'aa-equities-geo','aa-bonds-duration','aa-realestate-market','aa-liquidity-instrument'
  ].forEach(function(name){
    document.querySelectorAll('input[name="'+name+'"]').forEach(function(el){
      el.addEventListener('change',function(){persistAllocationPreferences();markStrategyDirty('MandatsprÃ¤ferenzen aktualisiert: Strategie neu berechnen.');});
    });
  });
}
function activePageKey(){
  var active=document.querySelector('.page.active');
  return active?String(active.id||'').replace('page-',''):'sd';
}
function setText(id,text){
  var el=document.getElementById(id);
  if(el)el.textContent=text;
}
function formatBpsPercent(bps){
  var n=Number(bps||0)/100;
  return (Math.abs(n-Math.round(n))<0.05?Math.round(n):n.toFixed(1))+'%';
}
function formatRiskLossBps(bps){
  if(bps===null||bps===undefined||bps==='')return 'n/a';
  var loss=Math.max(0,Math.round(Number(bps||0)));
  if(loss<=0)return '0%';
  return '-'+formatBpsPercent(loss);
}
function formatProbabilityPct(value){
  if(value===null||value===undefined||value==='')return 'n/a';
  return String(Math.max(0,Math.round(Number(value||0))))+'%';
}
function formatRappen(rappen){
  return 'CHF '+Math.round((Number(rappen)||0)/100).toLocaleString('de-CH');
}
function formatSignedBpsPercent(bps){
  if(bps===null||bps===undefined||bps==='')return 'n/a';
  var n=Math.round(Number(bps||0));
  if(!n)return '0%';
  return (n>0?'+':'-')+formatBpsPercent(Math.abs(n));
}
function formatSignedRappen(rappen){
  if(rappen===null||rappen===undefined||rappen==='')return 'n/a';
  var n=Math.round(Number(rappen||0));
  if(!n)return 'CHF 0';
  return (n>0?'+':'-')+'CHF '+Math.round(Math.abs(n)/100).toLocaleString('de-CH');
}
function formatUnitsMilli(value){
  if(value===null||value===undefined||value==='')return 'n/a';
  return (Number(value||0)/1000).toLocaleString('de-CH',{minimumFractionDigits:0,maximumFractionDigits:3});
}
function formatCompactCHF(chf){
  var n=Number(chf||0);
  if(n>=1000000)return 'CHF '+(n/1000000).toFixed(2).replace('.',"'")+' Mio';
  if(n>=1000)return 'CHF '+Math.round(n).toLocaleString('de-CH');
  return 'CHF '+Math.round(n).toLocaleString('de-CH');
}
function projectionContributionAt(contributionInput,index){
  if(Array.isArray(contributionInput)){
    if(index<contributionInput.length)return Number(contributionInput[index]||0);
    return contributionInput.length?Number(contributionInput[contributionInput.length-1]||0):0;
  }
  return Number(contributionInput||0);
}
function scaleProjectionContribution(contributionInput,factor){
  if(Array.isArray(contributionInput)){
    return contributionInput.map(function(value){return Math.round(Number(value||0)*factor);});
  }
  return Math.round(Number(contributionInput||0)*factor);
}
function projectionValueRappen(principalRappen,annualContributionRappen,returnBps,years){
  var future=Number(principalRappen||0);
  var rate=(Number(returnBps||0)/10000);
  for(var i=0;i<years;i++)future=future*(1+rate)+projectionContributionAt(annualContributionRappen,i);
  return Math.round(future);
}
function buildProjectionSeriesK(startRappen,annualContributionRappen,returnBps,years){
  var values=[];
  for(var i=0;i<=years;i++){
    var val=i===0?Number(startRappen||0):projectionValueRappen(startRappen,annualContributionRappen,returnBps,i);
    values.push(Math.round(val/100000));
  }
  return values;
}
function simulationPayload(result){
  return result&&result.simulation&&Array.isArray(result.simulation.target_mix_series_rappen)?result.simulation:null;
}
function monteCarloPayload(result){
  return result&&result.monte_carlo&&Array.isArray(result.monte_carlo.target_p50_series_rappen)?result.monte_carlo:null;
}
function liveRebalancingPayload(result){
  return result&&result.live_rebalancing&&Array.isArray(result.live_rebalancing.bucket_drifts)?result.live_rebalancing:null;
}
function simulationSeriesK(series){
  return (Array.isArray(series)?series:[]).map(function(value){
    return Math.round(Number(value||0)/100000);
  });
}
function simulationTerminalRappen(result,key,fallbackYears){
  var sim=simulationPayload(result);
  var series=sim&&Array.isArray(sim[key])?sim[key]:null;
  if(series&&series.length)return Number(series[series.length-1]||0);
  return projectionValueRappen(
    result&&result.advisory_wealth_rappen,
    result&&((result.cashflow_projection_series_rappen)||result.annual_net_cashflow_rappen),
    result&&result.expected_return_bps,
    fallbackYears||7
  );
}
function updateProjectionChartsFromSimulation(result){
  var sim=simulationPayload(result);
  if(!sim)return;
  var labels=(sim.year_labels||[]).map(function(year){return String(year);});
  var targetSeries=simulationSeriesK(sim.target_mix_series_rappen);
  var currentSeries=simulationSeriesK(sim.current_mix_series_rappen);
  if(charts.opt&&charts.opt.data){
    charts.opt.data.labels=labels;
    if(charts.opt.data.datasets[0])charts.opt.data.datasets[0].data=targetSeries;
    if(charts.opt.data.datasets[1])charts.opt.data.datasets[1].data=currentSeries;
    charts.opt.update();
  }
  if(charts.ist&&charts.ist.data&&charts.ist.data.datasets&&charts.ist.data.datasets[0]){
    charts.ist.data.labels=labels;
    charts.ist.data.datasets[0].data=currentSeries;
    charts.ist.update();
  }
}
function simulationCagrBps(series){
  var values=Array.isArray(series)?series:[];
  if(values.length<2)return 0;
  var start=Number(values[0]||0);
  var end=Number(values[values.length-1]||0);
  var years=Math.max(1,values.length-1);
  if(start<=0||end<=0)return 0;
  return Math.round((Math.pow(end/start,1/years)-1)*10000);
}
function assetDisplayName(name){
  var map={Liquiditaet:'Liquidität',Alternative:'Alternative',Immobilien:'Immobilien',Obligationen:'Obligationen',Aktien:'Aktien'};
  return map[name]||name;
}
function renderSubAllocationGroups(items){
  var rows=Array.isArray(items)?items:[];
  if(!rows.length)return '<div style="font-size:10px;color:var(--n4)">Noch keine Subanlageklassen berechnet.</div>';
  var orderedKeys=[];
  var groups={};
  rows.forEach(function(item){
    var key=String(item.asset_class||'Unbekannt');
    if(!groups[key]){
      groups[key]=[];
      orderedKeys.push(key);
    }
    groups[key].push(item);
  });
  return orderedKeys.map(function(key){
    var entries=groups[key]||[];
    var isExpanded=Object.prototype.hasOwnProperty.call(allocationSuballocExpanded,key)?Boolean(allocationSuballocExpanded[key]):true;
    var totalWeight=entries.reduce(function(sum,item){return sum+Number(item.target_weight_bps||0);},0);
    var body=isExpanded?entries.map(function(item){
      var riskValue=item.risky_fraction_bps==null||item.risky_fraction_bps===undefined?'n/a':formatBpsPercent(item.risky_fraction_bps||0);
      return '<div style="display:grid;grid-template-columns:1.3fr 70px 78px;gap:8px;align-items:center;padding:7px 9px;background:#fff;border:1px solid var(--b1);border-radius:var(--r)"><div><div style="font-size:11px;font-weight:500;color:var(--n8)">'+escapeHtml(item.sub_asset_class||item.asset_class||'Baustein')+'</div><div style="font-size:10px;color:var(--n5);margin-top:3px">'+escapeHtml(item.rationale||'')+'</div></div><div style="font-size:10px;color:var(--n7);text-align:right">'+formatBpsPercent(item.target_weight_bps||0)+'</div><div style="font-size:10px;color:var(--n7);text-align:right">'+escapeHtml(riskValue)+'</div></div>';
    }).join(''):'';
    return '<div style="border:1px solid var(--b1);border-radius:var(--r2);background:var(--bg)"><button type="button" onclick="toggleSubAllocationGroup('+JSON.stringify(key)+')" style="width:100%;display:flex;align-items:center;justify-content:space-between;gap:12px;padding:9px 10px;border:none;background:transparent;cursor:pointer"><div style="display:flex;align-items:center;gap:8px"><span style="font-size:12px;color:var(--n5)">'+(isExpanded?'▾':'▸')+'</span><div><div style="font-size:11px;font-weight:600;color:var(--n8);text-align:left">'+escapeHtml(assetDisplayName(key))+'</div><div style="font-size:9px;color:var(--n5);margin-top:2px;text-align:left">'+String(entries.length)+' Subanlageklasse(n)</div></div></div><div style="display:flex;align-items:center;gap:10px"><span style="font-size:10px;color:var(--n5)">Soll</span><span style="font-size:11px;font-weight:600;color:var(--n8)">'+formatBpsPercent(totalWeight)+'</span></div></button>'+(isExpanded?('<div style="display:flex;flex-direction:column;gap:5px;padding:0 10px 10px">'+body+'</div>'):'')+'</div>';
  }).join('');
}
function toggleSubAllocationGroup(assetClass){
  var key=String(assetClass||'Unbekannt');
  var current=Object.prototype.hasOwnProperty.call(allocationSuballocExpanded,key)?Boolean(allocationSuballocExpanded[key]):true;
  allocationSuballocExpanded[key]=!current;
  renderEngineRuntimePanels(strategyState.allocation||null);
}
function renderLiveRebalancingBuckets(live){
  var rows=live&&Array.isArray(live.bucket_drifts)?live.bucket_drifts:[];
  if(!rows.length)return '<div style="font-size:10px;color:var(--n4)">Noch keine live bewerteten Drift-Daten vorhanden.</div>';
  return rows.map(function(item){
    var breached=Boolean(item.breached);
    var tone=breached?'var(--neg)':(Math.abs(Number(item.delta_weight_bps||0))>=100?'var(--warn)':'var(--pos)');
    var label=breached?'Band verletzt':'Im Band';
    return '<div style="display:grid;grid-template-columns:1fr 62px 62px 78px;gap:8px;align-items:center;padding:8px 9px;background:var(--bg);border:1px solid var(--b1);border-radius:var(--r)"><div><div style="font-size:11px;font-weight:500;color:var(--n8)">'+escapeHtml(assetDisplayName(item.asset_class||'Asset-Klasse'))+'</div><div style="font-size:9px;color:var(--n5);margin-top:3px">Live '+formatRappen(item.current_market_value_rappen||0)+' / Soll '+formatRappen(item.target_market_value_rappen||0)+'</div></div><div style="font-size:10px;color:var(--n7);text-align:right">'+formatBpsPercent(item.current_weight_bps||0)+'</div><div style="font-size:10px;color:'+tone+';text-align:right;font-weight:600">'+formatSignedBpsPercent(item.delta_weight_bps||0)+'</div><div style="text-align:right"><div style="font-size:10px;color:'+tone+';font-weight:600">'+formatSignedRappen(item.rebalance_amount_rappen||0)+'</div><div style="font-size:9px;color:var(--n5);margin-top:3px">'+escapeHtml(label)+'</div></div></div>';
  }).join('');
}
function renderLiveRebalancingPositions(live){
  var rows=live&&Array.isArray(live.position_drifts)?live.position_drifts.slice(0,5):[];
  if(!rows.length)return '<div style="font-size:10px;color:var(--n4)">Titel-Hotspots erscheinen, sobald ein Live-Rezept mit Preisen vorliegt.</div>';
  return rows.map(function(item){
    return '<div style="display:grid;grid-template-columns:1.2fr 62px 78px;gap:8px;align-items:center;padding:8px 9px;background:#fff;border:1px solid var(--b1);border-radius:var(--r)"><div><div style="font-size:11px;font-weight:500;color:var(--n8)">'+escapeHtml(item.product_name||'Titel')+'</div><div style="font-size:9px;color:var(--n5);margin-top:3px">'+escapeHtml(item.sub_asset_class||item.asset_class||'')+' / Ref. '+(item.reference_price_date?escapeHtml(item.reference_price_date):'n/a')+' / Live '+(item.latest_price_date?escapeHtml(item.latest_price_date):'n/a')+'</div></div><div style="font-size:10px;color:var(--n7);text-align:right">'+formatSignedBpsPercent(item.delta_weight_bps||0)+'</div><div style="text-align:right"><div style="font-size:10px;font-weight:600;color:var(--n7)">'+formatSignedRappen(item.rebalance_amount_rappen||0)+'</div><div style="font-size:9px;color:var(--n5);margin-top:3px">'+escapeHtml(item.rebalance_action||'Beobachten')+'</div></div></div>';
  }).join('');
}
function renderPortfolioRebalancingSummary(live){
  var box=document.getElementById('po-rebalance-summary');
  if(!box)return;
  if(!live){
    box.style.display='none';
    box.innerHTML='';
    return;
  }
  box.style.display='grid';
  box.style.gridTemplateColumns='repeat(4,minmax(0,1fr))';
  box.innerHTML=''
    + '<div style="background:var(--bg);border:1px solid var(--b1);border-radius:var(--r);padding:9px 10px"><div style="font-size:9px;text-transform:uppercase;letter-spacing:0.07em;color:var(--n4);margin-bottom:4px">Live-Marktwert</div><div style="font-family:var(--f-d);font-size:16px;color:var(--n8)">'+formatRappen(live.live_total_value_rappen||0)+'</div><div style="font-size:9px;color:var(--n5);margin-top:3px">Stand '+escapeHtml(live.as_of_date||'n/a')+'</div></div>'
    + '<div style="background:var(--bg);border:1px solid var(--b1);border-radius:var(--r);padding:9px 10px"><div style="font-size:9px;text-transform:uppercase;letter-spacing:0.07em;color:var(--n4);margin-bottom:4px">Turnover</div><div style="font-family:var(--f-d);font-size:16px;color:var(--n8)">'+formatRappen(live.turnover_required_rappen||0)+'</div><div style="font-size:9px;color:var(--n5);margin-top:3px">'+String((live.breached_asset_classes||[]).length)+' Bandbruch(e)</div></div>'
    + '<div style="background:var(--bg);border:1px solid var(--b1);border-radius:var(--r);padding:9px 10px"><div style="font-size:9px;text-transform:uppercase;letter-spacing:0.07em;color:var(--n4);margin-bottom:4px">Preisabdeckung</div><div style="font-family:var(--f-d);font-size:16px;color:var(--n8)">'+String(((live.market_data_quality||{}).fresh_coverage_pct||0))+'%</div><div style="font-size:9px;color:var(--n5);margin-top:3px">'+String(live.missing_prices_count||0)+' ohne Preis / '+String(live.stale_positions_count||0)+' stale</div></div>'
    + '<div style="background:var(--bg);border:1px solid var(--b1);border-radius:var(--r);padding:9px 10px"><div style="font-size:9px;text-transform:uppercase;letter-spacing:0.07em;color:var(--n4);margin-bottom:4px">Bestandsbasis</div><div style="font-family:var(--f-d);font-size:16px;color:var(--n8)">'+String(live.holding_positions_count||0)+' / '+String((live.holding_positions_count||0)+(live.implied_positions_count||0))+'</div><div style="font-size:9px;color:var(--n5);margin-top:3px">'+String(live.implied_positions_count||0)+' noch implizit</div></div>';
}
function markStrategyDirty(message){
  strategyState.dirty=true;
  if(message)updateStrategyStatus(message,false);
}
function updateStrategyStatus(message,isError){
  var status=document.getElementById('aa-pref-status');
  if(status){
    status.textContent=message;
    status.style.color=isError?'var(--neg)':'var(--n4)';
  }
  var recipe=document.getElementById('recipe-status');
  if(recipe){
    recipe.textContent=message;
    recipe.style.color=isError?'var(--neg)':'var(--n4)';
  }
}
function renderActionCards(buckets,reasoning,totalRappen,liveRebalancing){
  var el=document.getElementById('aa-action-list');
  if(!el)return;
  var liveBuckets=liveRebalancing&&Array.isArray(liveRebalancing.bucket_drifts)?liveRebalancing.bucket_drifts:[];
  var sourceRows=(liveBuckets.length?liveBuckets:(Array.isArray(buckets)?buckets:[])).slice();
  var items=sourceRows.sort(function(a,b){
    var left=liveBuckets.length?Number(a.rebalance_amount_rappen||0):Number(a.delta_weight_bps||0);
    var right=liveBuckets.length?Number(b.rebalance_amount_rappen||0):Number(b.delta_weight_bps||0);
    return Math.abs(right)-Math.abs(left);
  }).filter(function(item){
    return liveBuckets.length?Math.abs(Number(item.rebalance_amount_rappen||0))>=5000:Math.abs(Number(item.delta_weight_bps||0))>=100;
  }).slice(0,4).map(function(item){
    var up=liveBuckets.length?Number(item.rebalance_amount_rappen||0)>0:Number(item.delta_weight_bps||0)>0;
    var magnitude=liveBuckets.length?Math.abs(Number(item.rebalance_amount_rappen||0)):Math.abs(Number(item.delta_weight_bps||0));
    var severity=liveBuckets.length
      ? (magnitude>=3000000?'Hoch':(magnitude>=1500000?'Mittel':'Tief'))
      : (magnitude>=300?'Hoch':(magnitude>=150?'Mittel':'Tief'));
    var tagClass=severity==='Hoch'?'tr2':(severity==='Mittel'?'ta':'tn');
    var amount=liveBuckets.length?Math.round(Math.abs(Number(item.rebalance_amount_rappen||0))/100):Math.round((Number(totalRappen||0)*Math.abs(Number(item.delta_weight_bps||0))/10000)/100);
    var verb=up?'aufbauen':'reduzieren';
    var detail=liveBuckets.length?(formatSignedBpsPercent(item.delta_weight_bps||0)+' Live-Drift. Ca. CHF '+amount.toLocaleString('de-CH')+' Richtung Soll'+(item.breached?' / Band verletzt':'')):(formatBpsPercent(Math.abs(item.delta_weight_bps))+' Drift. Ca. CHF '+amount.toLocaleString('de-CH')+' Richtung Soll.');
    return '<div style="border:1px solid var(--b1);border-radius:var(--r);padding:8px 10px"><div style="display:flex;justify-content:space-between;margin-bottom:3px"><span style="font-size:11px;font-weight:500">'+assetDisplayName(item.asset_class)+' '+verb+'</span><span class="tag '+tagClass+'">'+severity+'</span></div><div style="font-size:10px;color:var(--n6);line-height:1.5">'+detail+'</div></div>';
  });
  if(!items.length&&Array.isArray(reasoning)&&reasoning.length){
    items=reasoning.slice(0,3).map(function(text){
      return '<div style="border:1px solid var(--b1);border-radius:var(--r);padding:8px 10px"><div style="font-size:10px;color:var(--n6);line-height:1.5">'+escapeHtml(text)+'</div></div>';
    });
  }
  el.innerHTML=items.join('');
}
function renderPortfolioSections(positions){
  var wrap=document.getElementById('po-portfolio-sections');
  if(!wrap)return;
  var items=Array.isArray(positions)?positions:[];
  items=items.filter(function(item,index){return items.indexOf(item)===index;});
  if(!items.length){
    wrap.innerHTML='<div class="ps"><div class="prow"><div class="pisin">–</div><div><div class="pname">Noch keine Produktempfehlungen</div><div class="pdet">Bitte Strategie berechnen.</div></div><div><span class="tag tn">Leer</span></div><div class="pval">0%</div><div class="pval">0</div><div class="pval">–</div><div class="pperf">–</div><div class="pval" style="font-size:9px;color:var(--n4)">–</div></div></div>';
    return;
  }
  var groups={};
  items.forEach(function(item){
    var key=assetDisplayName(item.asset_class||'Portfolio');
    if(!groups[key])groups[key]=[];
    groups[key].push(item);
  });
  wrap.innerHTML=Object.keys(groups).map(function(group){
    var rows=groups[group];
    var subtotal=rows.reduce(function(sum,row){return sum+Number(row.current_market_value_rappen||row.target_amount_rappen||0);},0);
    var pct=rows.reduce(function(sum,row){return sum+Number(row.target_weight_bps||0);},0);
    var rowHtml=rows.map(function(row){
      var priceBits=[];
      if(row.latest_price_date)priceBits.push('Preis '+row.latest_price_date);
      if(row.price_age_days!=null)priceBits.push((Number(row.price_is_fresh)?'frisch ':'alt ')+String(row.price_age_days)+'T');
      if(row.lookup_mode==='proxy'&&row.lookup_symbol)priceBits.push('Proxy '+String(row.lookup_symbol));
      else if(row.lookup_mode==='synthetic_par')priceBits.push('Par-Wert');
      else if(row.lookup_mode==='direct'&&row.lookup_symbol)priceBits.push('Lookup '+String(row.lookup_symbol));
      if(row.reference_recalibrated)priceBits.push('Referenz neu kalibriert');
      if(row.holding_present){
        if(row.holding_depot_bank)priceBits.push('Depot '+String(row.holding_depot_bank));
        if(row.holding_as_of_date)priceBits.push('Bestand '+String(row.holding_as_of_date));
        if(row.current_units_milli!=null)priceBits.push(formatUnitsMilli(row.current_units_milli)+' Stk');
      }else{
        priceBits.push('Noch kein echter Bestand');
      }
      var refLabel=row.reference_price_rappen?formatRappen(row.reference_price_rappen):(row.reference_price_date?String(row.reference_price_date):'n/a');
      var driftLabel=row.price_change_bps==null?'n/a':formatSignedBpsPercent(row.price_change_bps);
      return '<div class="prow"><div class="pisin">'+escapeHtml(row.isin||'–')+'</div><div><div class="pname">'+escapeHtml(row.product_name||'Produkt')+'</div><div class="pdet">'+escapeHtml((row.provider||'')+(row.currency?' · '+row.currency:'')+(row.rationale?' · '+row.rationale:'')+(priceBits.length?' · '+priceBits.join(' / '):''))+'</div></div><div><span class="tag tn">'+escapeHtml(row.sub_asset_class||row.asset_class||'Titel')+'</span></div><div class="pval">'+formatBpsPercent(row.target_weight_bps)+'</div><div class="pval">'+formatRappen(row.current_market_value_rappen!=null?row.current_market_value_rappen:row.target_amount_rappen||0)+'</div><div class="pval" style="color:var(--n4)">'+escapeHtml(refLabel)+'</div><div class="pperf" style="color:var(--n4)">'+escapeHtml(driftLabel+' / '+String(row.rebalance_action||'Beobachten'))+'</div><div class="pval" style="font-size:9px;color:var(--n4)">'+((row.ter_bps||0)/100).toFixed(2)+'%</div></div>';
    }).join('');
    return '<div class="ps"><div class="psh"><span class="psn">'+escapeHtml(group)+'</span><div class="psr"><span class="psp">'+formatBpsPercent(pct)+'</span><span class="psc">'+formatRappen(subtotal)+'</span></div></div>'+rowHtml+'<div class="ptot"><span style="font-size:10px;font-weight:600">Total '+escapeHtml(group)+'</span><span style="font-size:11px;font-weight:600">'+formatRappen(subtotal)+'</span></div></div>';
  }).join('');
}
function renderRecommendationWarnings(warnings,marketDataQuality,live){
  var box=document.getElementById('po-engine-warnings');
  if(!box)return;
  var items=Array.isArray(warnings)?warnings.filter(Boolean):[];
  var quality=marketDataQuality||{};
  var rebalance=live||null;
  if(rebalance&&Number(rebalance.holding_positions_count||0)>0)items.unshift('Echte Depotbestände aktiv: '+String(rebalance.holding_positions_count)+' Position(en) werden direkt aus hinterlegten Holdings bewertet.');
  if(rebalance&&Number(rebalance.implied_positions_count||0)>0)items.unshift('Bestandsabgleich offen: '+String(rebalance.implied_positions_count)+' Position(en) nutzen für Drift noch die implizite Rezept-Rekonstruktion.');
  if(Number(quality.proxy_lookup_products_count||0)>0)items.unshift('Proxy-Marktdaten aktiv: '+String(quality.proxy_lookup_products_count)+' Produkt(e) werden ueber liquide Stellvertreter bewertet.');
  if(Number(quality.synthetic_lookup_products_count||0)>0)items.unshift('Par-Bewertung aktiv: '+String(quality.synthetic_lookup_products_count)+' Cash-/Festgeld-Produkt(e) werden synthetisch zum Nominalwert gefuehrt.');
  if(Number(quality.stale_products_count||0)>0)items.unshift('Marktdaten veraltet: '+String(quality.stale_products_count)+' Produkt(e) älter als '+String(quality.stale_after_days||5)+' Tage.');
  if(Number(quality.missing_price_count||0)>0)items.unshift('Marktdaten unvollständig: '+String(quality.missing_price_count)+' Produkt(e) ohne Preis.');
  if(Number(quality.mapping_gap_count||0)>0)items.unshift('Mapping-Lücke: '+String(quality.mapping_gap_count)+' Produkt(e) ohne Symbol/Lookup.');
  if(!items.length){
    box.style.display='none';
    box.innerHTML='';
    return;
  }
  box.style.display='block';
  box.innerHTML='<div style="font-size:10px;font-weight:700;letter-spacing:0.05em;text-transform:uppercase;color:#9a3412;margin-bottom:6px">Umsetzungshinweise</div>'
    + items.map(function(item){
      return '<div style="font-size:11px;color:#9a3412;line-height:1.5;margin-top:3px">• '+escapeHtml(item)+'</div>';
    }).join('');
}
function renderStrategySummary(){
  var allocation=strategyState.allocation;
  if(!allocation)return;
  var risk=strategyState.risk||null;
  var recommendation=strategyState.recommendation||null;
  var advisoryChf=Math.round((Number(allocation.advisory_wealth_rappen||0))/100);
  var totalChf=Math.round((Number(allocation.total_wealth_rappen||0))/100);
  var sim=simulationPayload(allocation);
  var projectedRappen=simulationTerminalRappen(allocation,'target_mix_series_rappen',7);
  var scoredGoals=allocation.goal_analysis||[];
  var scoreWeightTotal=scoredGoals.reduce(function(sum,item){return sum+Math.max(1,Number(item.weight_bps||0));},0);
  var avgGoalScore=scoreWeightTotal
    ? Math.round(scoredGoals.reduce(function(sum,item){return sum+(Math.max(1,Number(item.weight_bps||0))*Number(item.achievement_score||0));},0)/scoreWeightTotal)
    : 0;
  var goalsWithPath=allocation.goal_analysis?allocation.goal_analysis.filter(function(item){return item.path_success_rate_pct!=null;}):[];
  var pathWeightTotal=goalsWithPath.reduce(function(sum,item){return sum+Math.max(1,Number(item.weight_bps||0));},0);
  var avgPathSuccess=pathWeightTotal
    ? Math.round(goalsWithPath.reduce(function(sum,item){return sum+(Math.max(1,Number(item.weight_bps||0))*Number(item.path_success_rate_pct||0));},0)/pathWeightTotal)
    : null;
  var endangered=allocation.goal_analysis?allocation.goal_analysis.filter(function(item){return Number(item.achievement_score||0)<45;}).length:0;
  if(risk){
    setText('sr-risk-score',Math.round(Number(risk.final_score_x10||0)/10)+' / 10');
    setText('sr-risk-profile',risk.final_profile||'Nicht definiert');
    var ovr=document.getElementById('sr-ovr-badge');
    if(ovr)ovr.style.display=Number(risk.is_overridden||0)?'block':'none';
  }
  setText('sr-wealth',formatCompactCHF(advisoryChf));
  setText('sr-wealth-share',totalChf?Math.round(advisoryChf/Math.max(1,totalChf)*100)+'% des Reinvermögens':'Kein Gesamtvermögen verfügbar');
  setText('sr-goal-score',avgGoalScore+'%');
  setText('sr-goal-sub',endangered?(endangered+' Ziel(e) gefährdet'+(avgPathSuccess!=null?' / Pfad '+avgPathSuccess+'%':'')):('Ziele mehrheitlich on track'+(avgPathSuccess!=null?' / Pfad '+avgPathSuccess+'%':'')));
  setText('sr-proj-wealth',formatCompactCHF(projectedRappen/100));
  setText('sr-proj-sub',sim?('Simulation bis '+String((sim.year_labels&&sim.year_labels[sim.year_labels.length-1])||'')):'Nach Umsetzung Soll');
  var srProjValue=document.getElementById('sr-proj-wealth');
  if(srProjValue&&srProjValue.previousElementSibling){
    srProjValue.previousElementSibling.textContent='Prognose '+String((sim&&sim.year_labels&&sim.year_labels[sim.year_labels.length-1])||'2033');
  }
  setText('sr-strategy-name',risk&&risk.final_profile?('TBI · '+risk.final_profile):'TBI V1');
  setText('sr-horizon',risk&&risk.investment_horizon_years?(risk.investment_horizon_years+' Jahre'):'Langfristig');
  var bars=document.getElementById('sr-allocation-bars');
  if(bars){
    bars.innerHTML=(allocation.buckets||[]).map(function(bucket){
      var pct=Math.max(0,Math.min(100,Math.round(Number(bucket.target_weight_bps||0)/100)));
      return '<div style="display:flex;align-items:center;gap:6px"><span style="font-size:10px;width:90px;color:var(--n6)">'+escapeHtml(assetDisplayName(bucket.asset_class))+'</span><div style="flex:1;height:6px;background:var(--bg2);border-radius:3px"><div style="width:'+pct+'%;height:100%;background:var(--n5);border-radius:3px"></div></div><span style="font-size:10px;font-weight:500;color:var(--n7);width:40px;text-align:right">'+formatBpsPercent(bucket.target_weight_bps)+'</span></div>';
    }).join('');
  }
  var goals=document.getElementById('sr-goal-priority-list');
  if(goals){
    goals.innerHTML=(allocation.goal_analysis||[]).slice(0,3).map(function(goal){
      var color=Number(goal.achievement_score||0)>=70?'var(--pos)':(Number(goal.achievement_score||0)>=45?'var(--warn)':'var(--neg)');
      return '<div style="display:flex;justify-content:space-between;align-items:center;padding:6px 8px;background:var(--bg);border-radius:var(--r);border:1px solid var(--b1)"><div><span style="font-size:9px;font-weight:600;color:var(--n5);margin-right:6px">RANG '+escapeHtml(goal.rank)+'</span><span style="font-size:11px;color:var(--n8)">'+escapeHtml(goal.label||'Ziel')+'</span></div><span style="font-size:10px;color:'+color+';font-weight:500">'+formatRappen(goal.target_amount_rappen||0)+'</span></div>';
    }).join('');
  }
  var steps=document.getElementById('sr-implementation-steps');
  if(steps){
    var stepItems=(recommendation&&recommendation.implementation_steps&&recommendation.implementation_steps.length?recommendation.implementation_steps:(allocation.reasoning||[])).slice(0,3);
    steps.innerHTML=stepItems.map(function(item,idx){
      var tone=idx===2?'var(--pos)':'var(--n6)';
      var action=idx===0?'1':'2';
      return '<div style="border:1px solid var(--b1);border-radius:var(--r2);padding:10px"><div style="display:flex;align-items:center;gap:6px;margin-bottom:6px"><div style="width:20px;height:20px;border-radius:50%;background:'+tone+';color:#fff;font-size:10px;font-weight:600;display:flex;align-items:center;justify-content:center">'+(idx+1)+'</div><span style="font-size:11px;font-weight:500;color:var(--n8)">'+(idx===0?'Anpassen':idx===1?'Aufbauen':'Review')+'</span></div><div style="font-size:10px;color:var(--n6);line-height:1.5">'+escapeHtml(item)+'</div></div>';
    }).join('');
  }
}
function applyAllocationEngineResult(result){
  strategyState.allocation=result;
  TOTAL=Math.round((Number(result.advisory_wealth_rappen||0))/100);
  var colors={Aktien:'#1e4b8f',Obligationen:'#78601a',Immobilien:'#2c5080',Alternative:'#4a6080',Liquiditaet:'#166534'};
  alloc=(result.buckets||[]).map(function(bucket){
    var key=String(bucket.asset_class||'');
    return {n:assetDisplayName(key),c:colors[key]||'#5a6878',ist:Number(bucket.current_weight_bps||0)/100,soll:Number(bucket.target_weight_bps||0)/100,chf:Math.round((Number(bucket.current_amount_rappen||0))/100)};
  });
  quoten=(result.buckets||[]).map(function(bucket){
    var key=String(bucket.asset_class||'');
    return {key:normalizeBandKey(key),n:assetDisplayName(key),c:colors[key]||'#5a6878',ist:Number(bucket.current_weight_bps||0)/100,min:Number(bucket.band_min_bps||0)/100,ziel:Number(bucket.target_weight_bps||0)/100,max:Number(bucket.band_max_bps||0)/100};
  });
  buildAT();buildQT('qt-modal');buildDLegend();
  if(charts.dn){
    charts.dn.data.labels=alloc.map(function(r){return r.n;});
    charts.dn.data.datasets[0].data=alloc.map(function(r){return r.ist;});
    charts.dn.data.datasets[0].backgroundColor=alloc.map(function(r){return r.c;});
    charts.dn.update();
  }
  updateProjectionChartsFromSimulation(result);
  var projectedRappen=simulationTerminalRappen(result,'target_mix_series_rappen',7);
  var currentProjectedRappen=simulationTerminalRappen(result,'current_mix_series_rappen',7);
  var sim=simulationPayload(result);
  var mc=monteCarloPayload(result);
  var cagrBps=sim?simulationCagrBps(sim.target_mix_series_rappen):Number(result.expected_return_bps||0);
  var deltaChf=Math.round((projectedRappen-currentProjectedRappen)/100);
  setText('aa-proj-wealth',formatCompactCHF(projectedRappen/100));
  var aaProjValue=document.getElementById('aa-proj-wealth');
  if(aaProjValue&&aaProjValue.previousElementSibling){
    aaProjValue.previousElementSibling.textContent='Prognose '+String((sim&&sim.year_labels&&sim.year_labels[sim.year_labels.length-1])||'2033');
  }
  var overviewIstKpi=document.querySelector('#page-ub .kpir .kpi:last-child');
  if(overviewIstKpi){
    var overviewLabel=overviewIstKpi.querySelector('.kl');
    var overviewValue=overviewIstKpi.querySelector('.kv');
    var overviewSub=overviewIstKpi.querySelector('.ks');
    if(overviewLabel)overviewLabel.innerHTML='IST-Prognose '+String((sim&&sim.year_labels&&sim.year_labels[sim.year_labels.length-1])||'2033')+' <span style="font-size:8px;color:var(--n3)">↗</span>';
    if(overviewValue)overviewValue.textContent=formatCompactCHF(currentProjectedRappen/100);
    if(overviewSub)overviewSub.innerHTML='<span class="a">Ohne Optimierung</span>';
  }
  var istCanvas=document.getElementById('ch-ist');
  if(istCanvas&&istCanvas.closest){
    var istBody=istCanvas.closest('.cbody');
    var istStats=istBody&&istBody.children&&istBody.children[2]?istBody.children[2]:null;
    var currentCagrBps=sim?simulationCagrBps(sim.current_mix_series_rappen):Math.max(0,Number(result.expected_return_bps||0)-120);
    if(istStats&&istStats.children&&istStats.children.length>=4){
      if(istStats.children[0]&&istStats.children[0].children&&istStats.children[0].children[0])istStats.children[0].children[0].textContent='Prognose '+String((sim&&sim.year_labels&&sim.year_labels[sim.year_labels.length-1])||'2033');
      if(istStats.children[0]&&istStats.children[0].children&&istStats.children[0].children[1])istStats.children[0].children[1].textContent=formatCompactCHF(currentProjectedRappen/100);
      if(istStats.children[1]&&istStats.children[1].children&&istStats.children[1].children[1])istStats.children[1].children[1].textContent=((Number(currentCagrBps||0)/100).toFixed(2))+'%';
      if(istStats.children[2]&&istStats.children[2].children&&istStats.children[2].children[1])istStats.children[2].children[1].textContent=((Number(result.expected_volatility_bps||0)/100).toFixed(2))+'%';
      if(istStats.children[3]&&istStats.children[3].children&&istStats.children[3].children[1])istStats.children[3].children[1].textContent=(deltaChf>=0?'+':'−')+'CHF '+Math.abs(deltaChf).toLocaleString('de-CH');
    }
  }
  setText('aa-proj-delta',(deltaChf>=0?'+':'-')+'CHF '+Math.abs(deltaChf).toLocaleString('de-CH'));
  setText('aa-proj-cagr',((Number(cagrBps||0)/100).toFixed(2))+'%');
  setText('aa-proj-vol',((Number(result.expected_volatility_bps||0)/100).toFixed(2))+'%');
  setText('aa-proj-var95',formatRiskLossBps(mc&&mc.target_var_95_1y_bps));
  setText('aa-proj-cvar95',formatRiskLossBps(mc&&mc.target_cvar_95_1y_bps));
  setText('aa-proj-drawdown',formatRiskLossBps(mc&&mc.target_max_drawdown_p50_bps));
  setText('aa-proj-lossprob',formatProbabilityPct(mc&&mc.target_loss_probability_1y_pct));
  renderActionCards(result.buckets,result.reasoning,result.advisory_wealth_rappen,liveRebalancingPayload(result));
  renderEngineRuntimePanels(result);
  renderStrategySummary();
}
function applyRecommendationEngineResult(result){
  strategyState.recommendation=result;
  var live=liveRebalancingPayload(result);
  var liveTotal=live&&live.live_total_value_rappen!=null?live.live_total_value_rappen:(result.advisory_wealth_rappen||0);
  setText('po-advisory-wealth',formatRappen(liveTotal));
  setText('po-total-footer',formatRappen(liveTotal));
  setText('po-performance',((Number(result.expected_return_bps||0)/100).toFixed(2))+'%');
  setText('po-position-count',String((result.positions||[]).length));
  setText('po-average-ter',((Number(result.average_ter_bps||0)/100).toFixed(2))+'%');
  renderPortfolioRebalancingSummary(live);
  renderRecommendationWarnings(result.warnings||[],result.market_data_quality||{},live);
  renderPortfolioSections(result.positions||[]);
  var pageSubtitle=document.querySelector('#page-po .ph .ph-s');
  if(pageSubtitle)pageSubtitle.textContent='ISIN · Anlageklasse · Live-Marktwert · Preisdrift & Rebalancing';
  if(strategyState.allocation){
    renderActionCards(
      strategyState.allocation.buckets||[],
      strategyState.allocation.reasoning||[],
      strategyState.allocation.advisory_wealth_rappen||result.advisory_wealth_rappen||0,
      live
    );
    renderEngineRuntimePanels(strategyState.allocation);
  }
  renderStrategySummary();
}
async function loadCurrentAllocationResult(mid){
  var riskPromise=API.get('/mandates/'+mid+'/risk-assessments/current');
  var metaPromise=Promise.allSettled([
    API.get('/building-blocks/current'),
    API.get('/health/ready')
  ]);
  var results=await Promise.all([
    API.get('/mandates/'+mid+'/target-allocation/current/payload'),
    riskPromise,
    metaPromise
  ]);
  var allocationResult=results[0];
  strategyState.risk=results[1];
  var metaResults=results[2]||[];
  strategyState.buildingBlocks=metaResults[0]&&metaResults[0].status==='fulfilled'?metaResults[0].value:[];
  strategyState.marketRuntime=metaResults[1]&&metaResults[1].status==='fulfilled'?metaResults[1].value:null;
  strategyState.activeMandateId=mid;
  applyAllocationEngineResult(allocationResult);
  return allocationResult;
}
async function loadCurrentRecommendationResult(mid){
  try{
    return await API.get('/mandates/'+mid+'/recommendations/current/payload');
  }catch(e){
    if(e&&e.status===404)return null;
    throw e;
  }
}
async function refreshStrategyData(force,includeRecommendation,retriedAfterBandReset){
  var mid=getActiveMandateId();
  var page=activePageKey();
  var wantsRecommendation=includeRecommendation!=null?includeRecommendation:(page==='po'||page==='sr');
  if(!mid||isDemoMandateId(mid)){
    updateStrategyStatus('Demo- oder lokaler Modus: Engine wird nur für Live-Mandate ausgeführt.',false);
    return false;
  }
  if(strategyState.loading)return false;
  var cacheFresh=!force&&!strategyState.dirty&&strategyState.activeMandateId===mid&&(Date.now()-strategyState.lastGeneratedAt<60000);
  if(cacheFresh&&(!wantsRecommendation||strategyState.recommendation)){
    updateProjectionChartsFromSimulation(strategyState.allocation);
    renderEngineRuntimePanels(strategyState.allocation);
    renderStrategySummary();
    if(wantsRecommendation&&strategyState.recommendation)applyRecommendationEngineResult(strategyState.recommendation);
    return true;
  }
  if(!force&&!strategyState.dirty){
    strategyState.loading=true;
    updateStrategyStatus('Aktuelle Strategie wird geladen...',false);
    try{
      var currentAllocation=await loadCurrentAllocationResult(mid);
      if(wantsRecommendation){
        var currentRecommendation=await loadCurrentRecommendationResult(mid);
        if(currentRecommendation){
          applyRecommendationEngineResult(currentRecommendation);
          strategyState.lastGeneratedAt=Date.now();
          strategyState.dirty=false;
          updateStrategyStatus('Aktuelle Strategie geladen: '+new Date().toLocaleTimeString('de-CH',{hour:'2-digit',minute:'2-digit'}),false);
          return true;
        }
        var currentPrefs=collectAllocationPreferencesFromUI();
        var currentDepotBank=getInputValue('recipe-depot-bank')||'UBS AG ZÃ¼rich';
        var hydratedRecommendation=await API.post('/mandates/'+mid+'/recommendations/generate',{preferences:currentPrefs,target_allocation_id:currentAllocation.target_allocation.id,run_type:'Optimizer',depot_bank:currentDepotBank});
        applyRecommendationEngineResult(hydratedRecommendation);
        strategyState.lastGeneratedAt=Date.now();
        strategyState.dirty=false;
        updateStrategyStatus('Aktuelle Soll-Allokation geladen, Empfehlung aktualisiert: '+new Date().toLocaleTimeString('de-CH',{hour:'2-digit',minute:'2-digit'}),false);
        return true;
      }
      strategyState.lastGeneratedAt=Date.now();
      strategyState.dirty=false;
      updateStrategyStatus('Aktuelle Strategie geladen: '+new Date().toLocaleTimeString('de-CH',{hour:'2-digit',minute:'2-digit'}),false);
      return true;
    }catch(e){
      if(!(e&&String(e.status||'')==='404')&&!(e&&String(e.status||'')==='409')){
        updateStrategyStatus('Aktuelle Strategie konnte nicht geladen werden. Engine berechnet neu...',false);
      }
    }finally{
      strategyState.loading=false;
    }
  }
  strategyState.loading=true;
  updateStrategyStatus('Strategie wird neu berechnet...',false);
  try{
    var prefs=collectAllocationPreferencesFromUI();
    var allocationPromise=API.post('/mandates/'+mid+'/target-allocation/generate',{preferences:prefs});
    var riskPromise=API.get('/mandates/'+mid+'/risk-assessments/current');
    var metaPromise=Promise.allSettled([
      API.get('/building-blocks/current'),
      API.get('/health/ready')
    ]);
    var results=await Promise.all([allocationPromise,riskPromise,metaPromise]);
    var allocationResult=results[0];
    strategyState.risk=results[1];
    var metaResults=results[2]||[];
    strategyState.buildingBlocks=metaResults[0]&&metaResults[0].status==='fulfilled'?metaResults[0].value:[];
    strategyState.marketRuntime=metaResults[1]&&metaResults[1].status==='fulfilled'?metaResults[1].value:null;
    strategyState.activeMandateId=mid;
    applyAllocationEngineResult(allocationResult);
    if(wantsRecommendation){
      var depotBank=getInputValue('recipe-depot-bank')||'UBS AG Zürich';
      var recommendationResult=await API.post('/mandates/'+mid+'/recommendations/generate',{preferences:prefs,target_allocation_id:allocationResult.target_allocation.id,run_type:'Optimizer',depot_bank:depotBank});
      applyRecommendationEngineResult(recommendationResult);
    }
    strategyState.lastGeneratedAt=Date.now();
    strategyState.dirty=false;
    updateStrategyStatus('Strategie live berechnet: '+new Date().toLocaleTimeString('de-CH',{hour:'2-digit',minute:'2-digit'}),false);
    return true;
  }catch(e){
    var detail=String(e.detail||e.message||'?');
    var prefs=loadAllocationPreferences();
    if(!retriedAfterBandReset&&detail.indexOf('Bandbreiten')>=0){
      prefs=mergeAllocationPreferences(buildDefaultAllocationPreferences(),prefs);
      prefs.bands={};
      persistAllocationPreferences(prefs);
      strategyState.loading=false;
      updateStrategyStatus('Ungueltige lokale Bandbreiten wurden zurueckgesetzt. Strategie wird neu berechnet...',false);
      return refreshStrategyData(true,wantsRecommendation,true);
    }
    updateStrategyStatus('Strategie konnte nicht berechnet werden: '+(e.detail||e.message||'?'),true);
    return false;
  }finally{
    strategyState.loading=false;
  }
}
async function openAllocationEngineModal(){
  await refreshStrategyData(true,false);
  om('m-eq');
}
async function openImplementationRecipe(){
  await refreshStrategyData(true,true);
  om('m-ums');
}
async function confirmImplementationRecipe(){
  var ok=await refreshStrategyData(true,true);
  if(!ok)return;
  var mid=getActiveMandateId();
  var runId=strategyState&&strategyState.recommendation&&strategyState.recommendation.run?strategyState.recommendation.run.id:null;
  try{
    if(mid&&runId&&!isDemoMandateId(mid)){
      await API.fetch('/mandates/'+mid+'/recommendations/'+runId+'/finalize',{method:'PUT'});
      updateStrategyStatus('Aktuelles Rezept wurde finalisiert und für den Druck vorbereitet.',false);
    }else{
      updateStrategyStatus('Aktuelles Rezept wurde live aufgebaut und kann jetzt gedruckt werden.',false);
    }
    cm('m-ums');
    printReport({pages:['al','po','sr']});
  }catch(e){
    updateStrategyStatus('Rezept konnte nicht finalisiert werden: '+(e.detail||e.message||'?'),true);
  }
}
function getActiveClientId(){
  if(currentClientId)return currentClientId;
  if(currentPersona&&currentPersona.id&&String(currentPersona.id).indexOf('HH-')<0)return currentPersona.id;
  var a=document.querySelector('.client.active');
  return a?(a.dataset.cid||a.dataset.pid||null):null;
}
function getActiveMandateId(){
  if(currentMandateId)return currentMandateId;
  if(currentPersona&&currentPersona.mandate_id)return currentPersona.mandate_id;
  return null;
}
function normalizeFrequencyValue(value){
  var raw=String(value||'').trim();
  var norm=raw.toLowerCase()
    .replace(/ä/g,'ae').replace(/ö/g,'oe').replace(/ü/g,'ue')
    .replace(/Ã¤/g,'ae').replace(/Ã¶/g,'oe').replace(/Ã¼/g,'ue')
    .replace(/\?/g,'')
    .replace(/\s+/g,'');
  var map={
    monatlich:'monatlich',
    monthly:'monatlich',
    quartalsweise:'quartalsweise',
    quarterly:'quartalsweise',
    halbjaehrlich:'halbjährlich',
    semiannual:'halbjährlich',
    semiannually:'halbjährlich',
    jaehrlich:'jährlich',
    yearly:'jährlich',
    annually:'jährlich',
    einmalig:'einmalig',
    once:'einmalig',
    oneoff:'einmalig'
  };
  return map[norm]||raw||'jährlich';
}
// ════════════════════════════════════════════════════════════
// SECTION: SAVE HANDLERS (saveCashflow, saveGoal, saveWealthPosition, saveClientData)
// ════════════════════════════════════════════════════════════

function cashflowFrequencyKey(value){
  return String(normalizeFrequencyValue(value)||'')
    .toLowerCase()
    .replace(/ä/g,'ae').replace(/ö/g,'oe').replace(/ü/g,'ue')
    .replace(/Ã¤/g,'ae').replace(/Ã¶/g,'oe').replace(/Ã¼/g,'ue')
    .replace(/\?/g,'')
    .replace(/\s+/g,'');
}
function normalizeCashflowDateValue(value){
  var raw=String(value||'').trim().slice(0,10);
  return /^\d{4}-\d{2}-\d{2}$/.test(raw)?raw:'';
}
function isOneOffCashflow(value){
  return cashflowFrequencyKey(value)==='einmalig';
}
function cashflowDisplayFrequency(value){
  var map={
    monatlich:'monatlich',
    quartalsweise:'quartalsweise',
    halbjaehrlich:'halbjährlich',
    jaehrlich:'jährlich',
    einmalig:'einmalig'
  };
  return map[cashflowFrequencyKey(value)]||String(value||'');
}
function cashflowAmountLabel(freq){
  return isOneOffCashflow(freq)?'Betrag (CHF) *':'Betrag pro Periode (CHF) *';
}
function cashflowTimingLabel(cashflow){
  var start=normalizeCashflowDateValue(cashflow&&cashflow.valid_from);
  var end=normalizeCashflowDateValue(cashflow&&cashflow.valid_until);
  var parts=[];
  if(cashflow&&cashflow.notes)parts.push(cashflow.notes);
  if(isOneOffCashflow(cashflow&&cashflow.frequency)){
    parts.push('einmalig');
    if(start||end)parts.push('am '+(start||end));
  }else{
    parts.push(cashflowDisplayFrequency(cashflow&&cashflow.frequency||'jaehrlich'));
    if(start&&end)parts.push('ab '+start+' bis '+end);
    else if(start)parts.push('ab '+start);
    else if(end)parts.push('bis '+end);
    else parts.push('unbefristet');
  }
  return parts.join(' · ');
}
function syncCashflowModalState(){
  var freq=getInputValue('acf-freq')||'jaehrlich';
  var amountLabel=document.getElementById('acf-amount-label');
  var startLabel=document.getElementById('acf-start-label');
  var endWrap=document.getElementById('acf-end-wrap');
  var hint=document.getElementById('acf-date-hint');
  var validFrom=normalizeCashflowDateValue(getInputValue('acf-valid-from'));
  var validUntil=normalizeCashflowDateValue(getInputValue('acf-valid-until'));
  if(amountLabel)amountLabel.textContent=cashflowAmountLabel(freq);
  if(isOneOffCashflow(freq)){
    if(startLabel)startLabel.textContent='Datum / Fälligkeit *';
    if(endWrap)endWrap.style.display='none';
    if(!validFrom&&validUntil)validFrom=validUntil;
    if(validFrom)setInputValue('acf-valid-from',validFrom);
    setInputValue('acf-valid-until',validFrom||'');
    if(hint)hint.textContent='Einmalige Cashflows benötigen ein genaues Datum, zum Beispiel 3a-Kapital im Jahr 2028.';
  }else{
    if(startLabel)startLabel.textContent='Start ab';
    if(endWrap)endWrap.style.display='block';
    if(hint)hint.textContent='Laufende Cashflows können ab einem Startdatum laufen und optional enden, zum Beispiel Lohn bis 2032.';
  }
}
async function saveCashflow(){
  var label=(document.getElementById('acf-label')||{value:''}).value.trim();
  var cftype=(document.getElementById('acf-cftype')||{value:'Income'}).value;
  var amount=(document.getElementById('acf-amount')||{value:''}).value;
  var cat=(document.getElementById('acf-cat')||{value:'Sonstiges'}).value;
  var freq=normalizeFrequencyValue((document.getElementById('acf-freq')||{value:'jährlich'}).value);
  var btn=document.getElementById('btn-acf-save');
  var isEdit=!!currentCashflowEditId;
  if(!label){showModalFeedback('acf-error',btn,'Bitte Bezeichnung eingeben.',true);return;}
  if(!amount||isNaN(parseFloat(amount))){showModalFeedback('acf-error',btn,'Bitte gültigen Betrag eingeben.',true);return;}
  var cid=getActiveClientId();
  if(btn){btn._origText=isEdit?'Aktualisieren':'Speichern';btn.disabled=true;btn.textContent=isEdit?'Aktualisieren...':'Speichern...';}
  var payload={cashflow_type:cftype,label:label,amount_rappen:parseCHF(amount),currency:'CHF',
    frequency:freq,nature:freq==='einmalig'?'einmalig':'wiederkehrend',is_inflation_linked:false,notes:cat};
  if(cid&&!isDemoClientId(cid)){
    try{
      if(isEdit)await API.put('/clients/'+cid+'/cashflows/'+currentCashflowEditId,payload);
      else await API.post('/clients/'+cid+'/cashflows',payload);
      showModalFeedback('acf-error',btn,isEdit?'✓ Cashflow aktualisiert':'✓ Cashflow gespeichert',false);
      cm('m-acf');
      refreshCashflowsUI(cid);
      markStrategyDirty(isEdit?'Cashflow aktualisiert: Strategie neu berechnen.':'Cashflow gespeichert: Strategie neu berechnen.');
    }catch(e){showModalFeedback('acf-error',btn,'Fehler: '+(e.detail||e.message||'?'),true);}
  } else {
    var isInc=cftype==='Income';
    var rows=document.getElementById(isInc?'zufluss-rows':'abfluss-rows');
    if(rows){
      var row=document.createElement('div');row.className='cf-row';row.dataset.cfid='local-'+Date.now();
      row.innerHTML='<div class="cfi" style="background:var('+(isInc?'--pos-lt':'--neg-lt')+')">'+(isInc?'💰':'📋')+'</div>'+
        '<div class="cfn"><div class="cfna">'+label+'</div><div class="cfnd">'+freq+' (Demo)</div></div>'+
        '<div class="cfa '+(isInc?'ci':'co')+'">'+(isInc?'+':'−')+'CHF '+parseFloat(amount).toLocaleString('de-CH')+'</div>'+
        '<div><button class="btn-ico" onclick="dcf(this)">✕</button></div>';
      var tot=rows.querySelector('.cft');if(tot)rows.insertBefore(row,tot);else rows.appendChild(row);
    }
    showModalFeedback('acf-error',btn,'✓ Demo-Modus: angezeigt',false);
    setTimeout(function(){cm('m-acf');},1200);
  }
}
async function refreshCashflowsUI(cid){
  try{
    var items=await API.get('/clients/'+cid+'/cashflows');
    if(!Array.isArray(items))items=items.items||[];
    currentCashflows=items.slice();
    var fmt=function(r){return 'CHF '+Math.round(r/100).toLocaleString('de-CH');};
    var inc=items.filter(function(c){return c.cashflow_type==='Income';});
    var exp=items.filter(function(c){return c.cashflow_type==='Expense';});
    var tIn=inc.reduce(function(s,c){return s+(c.amount_rappen||0);},0);
    var tOut=exp.reduce(function(s,c){return s+(c.amount_rappen||0);},0);
    var zf=document.getElementById('zufluss-rows');
    if(zf)zf.innerHTML='<div class="cf-sec">Laufende Zuflüsse</div>'+
      inc.map(function(c){return '<div class="cf-row" data-cfid="'+c.id+'"><div class="cfi" style="background:var(--pos-lt)">💰</div>'+
        '<div class="cfn"><div class="cfna">'+c.label+'</div><div class="cfnd">'+c.frequency+'</div></div>'+
        '<div class="cfa ci">+'+fmt(c.amount_rappen)+'</div>'+
        '<div><button class="btn-ico e" onclick="openCashflowEditor(\''+escapeHtml(c.id||'')+'\')">✎</button><button class="btn-ico" onclick="dcf(this)">✕</button></div></div>';}).join('')+
      '<div class="cft"><span style="font-size:11px;font-weight:600">Total p.a.</span><span style="font-family:var(--f-d);font-size:17px;color:var(--pos)">+'+fmt(tIn)+'</span></div>';
    var af=document.getElementById('abfluss-rows');
    if(af)af.innerHTML='<div class="cf-sec">Laufende Ausgaben</div>'+
      exp.map(function(c){return '<div class="cf-row" data-cfid="'+c.id+'"><div class="cfi" style="background:var(--neg-lt)">📋</div>'+
        '<div class="cfn"><div class="cfna">'+c.label+'</div><div class="cfnd">'+c.frequency+'</div></div>'+
        '<div class="cfa co">−'+fmt(c.amount_rappen)+'</div>'+
        '<div><button class="btn-ico e" onclick="openCashflowEditor(\''+escapeHtml(c.id||'')+'\')">✎</button><button class="btn-ico" onclick="dcf(this)">✕</button></div></div>';}).join('')+
      '<div class="cft"><div style="font-size:11px;font-weight:600">Netto p.a.</div>'+
      '<span style="font-family:var(--f-d);font-size:18px;color:'+(tIn>=tOut?'var(--pos)':'var(--neg)')+'">'+
      (tIn>=tOut?'+':'−')+fmt(Math.abs(tIn-tOut))+'</span></div>';
  }catch(e){console.warn('refreshCashflowsUI:',e);}
}

function resetCashflowModal(){
  currentCashflowEditId=null;
  setInputValue('acf-label','');
  setSelectValue('acf-cftype','Income');
  setInputValue('acf-amount','');
  setSelectValue('acf-cat','Sonstiges');
  setSelectValue('acf-freq','jaehrlich');
  setInputValue('acf-valid-from','');
  setInputValue('acf-valid-until','');
  var btn=document.getElementById('btn-acf-save');
  if(btn){btn.textContent='Speichern';btn.disabled=false;}
  var err=document.getElementById('acf-error');
  if(err){err.style.display='none';err.textContent='';}
  syncCashflowModalState();
}
function openCashflowEditor(cashflowId){
  var cashflow=(currentCashflows||[]).find(function(item){return String(item.id||'')===String(cashflowId||'');});
  if(!cashflow)return;
  currentCashflowEditId=cashflow.id;
  setInputValue('acf-label',cashflow.label||'');
  setSelectValue('acf-cftype',cashflow.cashflow_type||'Income');
  setInputValue('acf-amount',formatInputCHF(cashflow.amount_rappen));
  setSelectValue('acf-cat',cashflow.notes||'Sonstiges');
  setSelectValue('acf-freq',cashflowFrequencyKey(cashflow.frequency)||'jaehrlich');
  setInputValue('acf-valid-from',cashflow.valid_from||'');
  setInputValue('acf-valid-until',cashflow.valid_until||'');
  var btn=document.getElementById('btn-acf-save');
  if(btn){btn.textContent='Aktualisieren';btn.disabled=false;}
  var err=document.getElementById('acf-error');
  if(err){err.style.display='none';err.textContent='';}
  syncCashflowModalState();
  var modal=document.getElementById('m-acf');
  if(modal)modal.classList.add('open');
}
async function saveCashflow(){
  var label=(document.getElementById('acf-label')||{value:''}).value.trim();
  var cftype=(document.getElementById('acf-cftype')||{value:'Income'}).value;
  var amount=(document.getElementById('acf-amount')||{value:''}).value;
  var cat=(document.getElementById('acf-cat')||{value:'Sonstiges'}).value;
  var freq=getInputValue('acf-freq')||'jaehrlich';
  var validFrom=normalizeCashflowDateValue(getInputValue('acf-valid-from'));
  var validUntil=normalizeCashflowDateValue(getInputValue('acf-valid-until'));
  var btn=document.getElementById('btn-acf-save');
  var isEdit=!!currentCashflowEditId;
  if(!label){showModalFeedback('acf-error',btn,'Bitte Bezeichnung eingeben.',true);return;}
  if(!amount||isNaN(parseFloat(amount))){showModalFeedback('acf-error',btn,'Bitte gültigen Betrag eingeben.',true);return;}
  if(isOneOffCashflow(freq)){
    if(!validFrom&&!validUntil){showModalFeedback('acf-error',btn,'Bitte Datum für den einmaligen Cashflow eingeben.',true);return;}
    if(!validFrom)validFrom=validUntil;
    validUntil=validFrom;
  }else if(validFrom&&validUntil&&validUntil<validFrom){
    showModalFeedback('acf-error',btn,'Enddatum darf nicht vor dem Startdatum liegen.',true);return;
  }
  var cid=getActiveClientId();
  if(btn){btn._origText=isEdit?'Aktualisieren':'Speichern';btn.disabled=true;btn.textContent=isEdit?'Aktualisieren...':'Speichern...';}
  var payload={
    cashflow_type:cftype,
    label:label,
    amount_rappen:parseCHF(amount),
    currency:'CHF',
    frequency:cashflowFrequencyKey(freq)||'jaehrlich',
    nature:isOneOffCashflow(freq)?'einmalig':'wiederkehrend',
    valid_from:validFrom||null,
    valid_until:validUntil||null,
    is_inflation_linked:false,
    notes:cat
  };
  if(cid&&!isDemoClientId(cid)){
    try{
      if(isEdit)await API.put('/clients/'+cid+'/cashflows/'+currentCashflowEditId,payload);
      else await API.post('/clients/'+cid+'/cashflows',payload);
      showModalFeedback('acf-error',btn,isEdit?'✓ Cashflow aktualisiert':'✓ Cashflow gespeichert',false);
      cm('m-acf');
      refreshCashflowsUI(cid);
      markStrategyDirty(isEdit?'Cashflow aktualisiert: Strategie neu berechnen.':'Cashflow gespeichert: Strategie neu berechnen.');
    }catch(e){showModalFeedback('acf-error',btn,'Fehler: '+(e.detail||e.message||'?'),true);}
  }else{
    var isInc=cftype==='Income';
    var rows=document.getElementById(isInc?'zufluss-rows':'abfluss-rows');
    if(rows){
      var row=document.createElement('div');row.className='cf-row';row.dataset.cfid='local-'+Date.now();
      var detailLabel=cashflowTimingLabel({frequency:payload.frequency,valid_from:validFrom,valid_until:validUntil,notes:cat});
      row.innerHTML='<div class="cfi" style="background:var('+(isInc?'--pos-lt':'--neg-lt')+')">'+(isInc?'💼':'📋')+'</div>'+
        '<div class="cfn"><div class="cfna">'+escapeHtml(label)+'</div><div class="cfnd">'+escapeHtml(detailLabel)+' (Demo)</div></div>'+
        '<div class="cfa '+(isInc?'ci':'co')+'">'+(isInc?'+':'−')+'CHF '+parseFloat(amount).toLocaleString('de-CH')+'</div>'+
        '<div><button class="btn-ico" onclick="dcf(this)">✕</button></div>';
      var tot=rows.querySelector('.cft');if(tot)rows.insertBefore(row,tot);else rows.appendChild(row);
    }
    showModalFeedback('acf-error',btn,'✓ Demo-Modus: angezeigt',false);
    setTimeout(function(){cm('m-acf');},1200);
  }
}
async function refreshCashflowsUI(cid){
  try{
    var results=await Promise.all([
      API.get('/clients/'+cid+'/cashflows'),
      API.get('/clients/'+cid+'/cashflow-summary')
    ]);
    var items=results[0];
    var summary=results[1]||{};
    if(!Array.isArray(items))items=items.items||[];
    currentCashflows=items.slice();
    var fmt=function(r){return 'CHF '+Math.round(Number(r||0)/100).toLocaleString('de-CH');};
    var inc=items.filter(function(c){return c.cashflow_type==='Income';});
    var exp=items.filter(function(c){return c.cashflow_type==='Expense';});
    var tIn=Number(summary.total_income_rappen||0);
    var tOut=Number(summary.total_expense_rappen||0);
    var net=tIn-tOut;
    var summaryYear=Number(summary.summary_year||new Date().getFullYear());
    var renderRow=function(c,isIncome){
      return '<div class="cf-row" data-cfid="'+escapeHtml(c.id||'')+'"><div class="cfi" style="background:var('+(isIncome?'--pos-lt':'--neg-lt')+')">'+(isIncome?'💼':'📋')+'</div>'+
        '<div class="cfn"><div class="cfna">'+escapeHtml(c.label||'Cashflow')+'</div><div class="cfnd">'+escapeHtml(cashflowTimingLabel(c))+'</div></div>'+
        '<div class="cfa '+(isIncome?'ci':'co')+'">'+(isIncome?'+':'−')+fmt(c.amount_rappen||0)+'</div>'+
        '<div><button class="btn-ico e" onclick="openCashflowEditor(\''+escapeHtml(c.id||'')+'\')">✎</button><button class="btn-ico" onclick="dcf(this)">✕</button></div></div>';
    };
    var zf=document.getElementById('zufluss-rows');
    if(zf)zf.innerHTML='<div class="cf-sec">Zuflüsse</div>'+
      (inc.length?inc.map(function(c){return renderRow(c,true);}).join(''):'<div style="font-size:10px;color:var(--n4);padding:6px 0 8px">Noch keine Zuflüsse erfasst.</div>')+
      '<div class="cft"><span style="font-size:11px;font-weight:600">Total aktiv '+summaryYear+'</span><span style="font-family:var(--f-d);font-size:17px;color:var(--pos)">+'+fmt(tIn)+'</span></div>';
    var af=document.getElementById('abfluss-rows');
    if(af)af.innerHTML='<div class="cf-sec">Ausgaben</div>'+
      (exp.length?exp.map(function(c){return renderRow(c,false);}).join(''):'<div style="font-size:10px;color:var(--n4);padding:6px 0 8px">Noch keine Ausgaben erfasst.</div>')+
      '<div class="cft"><div style="font-size:11px;font-weight:600">Netto aktiv '+summaryYear+'</div>'+
      '<span style="font-family:var(--f-d);font-size:18px;color:'+(net>=0?'var(--pos)':'var(--neg)')+'">'+
      (net>=0?'+':'−')+fmt(Math.abs(net))+'</span></div>';
    var kCF=document.getElementById('kpi-cashflow');
    if(kCF)kCF.textContent=(net>=0?'+':'−')+'CHF '+Math.abs(Math.round(net/100)).toLocaleString('de-CH');
  }catch(e){console.warn('refreshCashflowsUI:',e);}
}
async function saveGoal(){
  var label=(document.getElementById('nz-label')||{value:''}).value.trim();
  var type=(document.getElementById('nz-type')||{value:'Einmalige_Ausgabe'}).value;
  var prio=(document.getElementById('nz-prio')||{value:'2'}).value;
  var amount=(document.getElementById('nz-amount')||{value:''}).value;
  var horizon=parseInt((document.getElementById('nz-horizon')||{value:'10'}).value)||10;
  var btn=document.getElementById('btn-nz-save');
  var isEdit=!!currentGoalEditId;
  if(!label){showModalFeedback('nz-error',btn,'Bitte Bezeichnung eingeben.',true);return;}
  if(!amount||isNaN(parseFloat(amount))){showModalFeedback('nz-error',btn,'Bitte gültigen Betrag eingeben.',true);return;}
  var mid=getActiveMandateId();
  if(btn){btn._origText=isEdit?'Aktualisieren':'Speichern';btn.disabled=true;btn.textContent=isEdit?'Aktualisieren...':'Speichern...';}
  var hMap={'1':'Hart','2':'Primär','3':'Opportunistisch'};
  var fMap={'Einmalige_Ausgabe':'Cashflow','Wiederkehrende_Ausgabe':'Cashflow','Pensionsausgabe':'Cashflow',
    'Kapitalerhalt':'Vermögen','Vermögensziel':'Vermögen','Renditeziel':'Rendite'};
  var isW=type==='Kapitalerhalt'||type==='Vermögensziel';
  var payload={goal_family:fMap[type]||'Cashflow',goal_type:type,label:label,rank:parseInt(prio),
    goal_scope:'Beratungsvermögen',value_mode:'nominal',
    target_amount_rappen:isW?null:parseCHF(amount),
    target_wealth_rappen:isW?parseCHF(amount):null,
    target_return_bps:type==='Renditeziel'?Math.round(parseFloat(amount)*100):null,
    horizon_years:horizon,hardness:hMap[prio]||'Primär',
    is_ongoing:type==='Wiederkehrende_Ausgabe'||type==='Pensionsausgabe'};
  if(mid&&!isDemoMandateId(mid)){
    try{
      if(isEdit)await API.put('/mandates/'+mid+'/goals/'+currentGoalEditId,payload);
      else await API.post('/mandates/'+mid+'/goals',payload);
      showModalFeedback('nz-error',btn,isEdit?'✓ Ziel aktualisiert':'✓ Ziel gespeichert',false);
      cm('m-nz');
      refreshGoalsUI(mid);
      markStrategyDirty(isEdit?'Ziel aktualisiert: Strategie neu berechnen.':'Ziel gespeichert: Strategie neu berechnen.');
    }catch(e){showModalFeedback('nz-error',btn,'Fehler: '+(e.detail||e.message||'?'),true);}
  } else {
    var zl=document.getElementById('zl');
    if(zl){
      var el=document.createElement('div');el.className='goal';el.draggable=true;el.dataset.goalid='local-'+Date.now();
      var cnt=zl.querySelectorAll('.goal').length+1;
      var pc={'1':'p1','2':'p2','3':'p3'};
      el.innerHTML='<div class="pd '+(pc[prio]||'p2')+'">'+cnt+'</div>'+
        '<div class="gi"><div class="gn">'+label+'</div><div class="gd">CHF '+parseFloat(amount).toLocaleString('de-CH')+' · '+horizon+' J. (Demo)</div></div>'+
        '<span class="tag ta">Demo</span><div class="gbw"><div class="gp">50 %</div><div class="gb"><div class="gf fa" style="width:50%"></div></div></div>'+
        '<div><button class="btn-ico" onclick="dg(this)">✕</button></div>';
      zl.appendChild(el);setupDrag();
    }
    showModalFeedback('nz-error',btn,'✓ Demo-Modus: angezeigt',false);
    setTimeout(function(){cm('m-nz');},1200);
  }
}
async function refreshGoalsUI(mid){
  try{
    var data=await API.get('/mandates/'+mid+'/goals');
    var items=Array.isArray(data)?data:(data.items||[]);
    currentGoals=items.slice();
    var zl=document.getElementById('zl');if(!zl)return;
    if(!items.length){zl.innerHTML='';return;}
    var pc={'Hart':'p1','Primär':'p2','Opportunistisch':'p3'};
    zl.innerHTML=items.map(function(g,i){
      var pct=g.achievement_score!=null?g.achievement_score:50;
      var gcl=pct>=70?'fg':pct>=45?'fa':'fr';var tcl=pct>=70?'tg':pct>=45?'ta':'tr2';
      var lbl=pct>=70?'On Track':pct>=45?'Prüfen':'Gefährdet';
      var amt=g.target_amount_rappen||g.target_wealth_rappen||0;
      return '<div class="goal" draggable="true" data-goalid="'+g.id+'">'+
        '<div class="pd '+(pc[g.hardness]||'p2')+'">'+(i+1)+'</div>'+
        '<div class="gi"><div class="gn">'+g.label+'</div><div class="gd">CHF '+Math.round(amt/100).toLocaleString('de-CH')+' · '+g.horizon_years+' J.</div></div>'+
        '<span class="tag '+tcl+'">'+lbl+'</span>'+
        '<div class="gbw"><div class="gp">'+pct+' %</div><div class="gb"><div class="gf '+gcl+'" style="width:'+pct+'%"></div></div></div>'+
        '<div><button class="btn-ico e" onclick="openGoalEditor(\''+escapeHtml(g.id||'')+'\')">✎</button><button class="btn-ico" onclick="dg(this)">✕</button></div></div>';
    }).join('');setupDrag();
  }catch(e){console.warn('refreshGoalsUI:',e);}
}

function buildWealthPositionPayload(cat,typ,note){
  var tMap={'Depot':'Depot','Liquiditaet':'Liquidität','Immobilien':'Immobilien','Vorsorge':'Vorsorge','Alternative':'Alternative','Hypothek':'Hypothek'};
  var posType=tMap[cat]||'Custom';
  var assignment=posType==='Hypothek'?'Verbindlichkeit':typ;
  var akt=parseFloat(getInputValue('sc-akt'))||0;
  var obl=parseFloat(getInputValue('sc-obl'))||0;
  var imm=parseFloat(getInputValue('sc-imm'))||0;
  var liq=parseFloat(getInputValue('sc-liq'))||0;
  var alt=parseFloat(getInputValue('sc-alt'))||0;
  var tot=akt+obl+imm+liq+alt;
  if(posType==='Depot'&&tot>0&&Math.abs(tot-100)>0.5){
    throw new Error('Allokation muss 100% ergeben (aktuell: '+Math.round(tot)+'%)');
  }
  var payload={
    label:'',
    position_type:posType,
    assignment:assignment,
    current_value_rappen:0,
    currency:'CHF',
    notes:null,
    alloc_equities_bps:Math.round(akt*100),
    alloc_bonds_bps:Math.round(obl*100),
    alloc_real_estate_bps:Math.round(imm*100),
    alloc_liquidity_bps:Math.round(liq*100),
    alloc_alternatives_bps:Math.round(alt*100),
    is_available_for_goal_funding:false
  };
  var noteParts=[note];
  if(posType==='Depot'){
    payload.label=getInputValue('maw-depot-label').trim();
    payload.current_value_rappen=parseCHF(getInputValue('maw-depot-value'));
    payload.depot_bank=getInputValue('maw-depot-bank').trim()||null;
    payload.depot_account_number=getInputValue('maw-depot-account').trim()||null;
  } else if(posType==='Liquidität'){
    payload.label=getInputValue('maw-liq-label').trim();
    payload.current_value_rappen=parseCHF(getInputValue('maw-liq-value'));
    payload.liquidity_instrument=getInputValue('maw-liq-instrument')||null;
    payload.liquidity_interest_rate_bps=parsePercentToBps(getInputValue('maw-liq-rate'));
    payload.liquidity_available_from=getInputValue('maw-liq-available')||null;
    var liqBank=getInputValue('maw-liq-bank').trim();
    if(liqBank)noteParts.push('Institut: '+liqBank);
  } else if(posType==='Immobilien'){
    payload.label=getInputValue('maw-immo-label').trim();
    payload.current_value_rappen=parseCHF(getInputValue('maw-immo-value'));
    payload.valuation_date=getInputValue('maw-immo-valuation-date')||null;
    payload.property_address=getInputValue('maw-immo-address').trim()||null;
    payload.property_usage=getInputValue('maw-immo-usage')||null;
    payload.property_rental_income_rappen=parseCHF(getInputValue('maw-immo-rent'));
  } else if(posType==='Vorsorge'){
    payload.label=getInputValue('maw-pension-label').trim();
    payload.current_value_rappen=parseCHF(getInputValue('maw-pension-value'));
    payload.pension_type=getInputValue('maw-pension-type')||null;
    payload.pension_institution=getInputValue('maw-pension-institution').trim()||null;
    payload.pension_technical_rate_bps=parsePercentToBps(getInputValue('maw-pension-rate'));
    var retirementAge=parseInt(getInputValue('maw-pension-age'),10);
    payload.pension_retirement_age=isFinite(retirementAge)?retirementAge:null;
    payload.pension_payout_form=getInputValue('maw-pension-payout')||null;
    payload.pension_wef_possible=getInputValue('maw-pension-wef')==='Ja';
    var pensionAvailable=getInputValue('maw-pension-available');
    if(pensionAvailable)noteParts.push('Verfügbar ab '+pensionAvailable);
    if(getInputValue('maw-pension-wef')==='Bereits bezogen')noteParts.push('WEF bereits bezogen');
  } else if(posType==='Alternative'){
    payload.label=getInputValue('maw-alt-label').trim();
    payload.current_value_rappen=parseCHF(getInputValue('maw-alt-value'));
    payload.valuation_date=getInputValue('maw-alt-valuation-date')||null;
    payload.asset_subtype=getInputValue('maw-alt-subtype')||null;
    payload.asset_expected_return_bps=parsePercentToBps(getInputValue('maw-alt-return'));
    payload.asset_liquidity=getInputValue('maw-alt-liquidity')||null;
    payload.asset_valuation_method=getInputValue('maw-alt-valuation-method')||null;
    payload.asset_location=getInputValue('maw-alt-location').trim()||null;
  } else if(posType==='Hypothek'){
    payload.label=getInputValue('maw-mortgage-label').trim();
    payload.current_value_rappen=parseCHF(getInputValue('maw-mortgage-value'));
    payload.mortgage_bank=getInputValue('maw-mortgage-bank').trim()||null;
    payload.mortgage_type=getInputValue('maw-mortgage-type')||null;
    payload.mortgage_interest_rate_bps=parsePercentToBps(getInputValue('maw-mortgage-rate'));
    payload.mortgage_maturity_date=getInputValue('maw-mortgage-maturity')||null;
    payload.mortgage_amortization_rappen=parseCHF(getInputValue('maw-mortgage-amortization'));
    payload.mortgage_amortization_type=getInputValue('maw-mortgage-amortization-type')||null;
    payload.mortgage_linked_property_id=getInputValue('maw-mortgage-linked-property').trim()||null;
  }
  payload.notes=joinNotes(noteParts);
  if(!payload.label)throw new Error('Bitte Bezeichnung eingeben.');
  if(payload.current_value_rappen<=0)throw new Error('Bitte gültigen Betrag / Wert eingeben.');
  return payload;
}
async function saveWealthPosition(){
  var cat=(document.getElementById('maw-cat')||{value:'Depot'}).value;
  var typ=(document.getElementById('maw-typ')||{value:'Beratungsvermögen'}).value;
  var note=(document.getElementById('maw-note')||{value:''}).value;
  var btn=document.getElementById('btn-maw-save');
  var isEdit=!!currentWealthEditId;
  var cid=getActiveClientId();
  var payload;
  try{
    payload=buildWealthPositionPayload(cat,typ,note);
  }catch(err){
    showModalFeedback('maw-error',btn,err.message||String(err),true);
    return;
  }
  if(btn){btn._origText=isEdit?'Aktualisieren':'Speichern';btn.disabled=true;btn.textContent=isEdit?'Aktualisieren...':'Speichern...';}
  if(cid&&!isDemoClientId(cid)){
    try{
      if(isEdit)await API.put('/clients/'+cid+'/wealth-positions/'+currentWealthEditId,payload);
      else await API.post('/clients/'+cid+'/wealth-positions',payload);
      await refreshWealthUI(cid);
      showModalFeedback('maw-error',btn,isEdit?'✓ Position aktualisiert':'✓ Position gespeichert',false);
      markStrategyDirty(isEdit?'Vermögensposition aktualisiert: Strategie neu berechnen.':'Vermögensposition gespeichert: Strategie neu berechnen.');
      setTimeout(function(){cm('m-aw');},600);
    }catch(e){
      showModalFeedback('maw-error',btn,'Fehler: '+(e.detail||e.message||'?'),true);
    }
  } else {
    if(isEdit){
      currentWealthPositions=currentWealthPositions.map(function(pos){
        if(String(pos.id||'')!==String(currentWealthEditId||''))return pos;
        return Object.assign({},pos,payload,{id:pos.id,position_type:pos.position_type,assignment:payload.assignment});
      });
    } else {
      currentWealthPositions=currentWealthPositions.concat([Object.assign({},payload,{id:'local-'+Date.now(),is_active:1})]);
    }
    renderWealthPositions(currentWealthPositions);
    showModalFeedback('maw-error',btn,isEdit?'✓ Demo-Modus: Position aktualisiert':'✓ Demo-Modus: angezeigt',false);
    setTimeout(function(){cm('m-aw');},1200);
  }
}
async function refreshWealthUI(cid){
  try{
    var results=await Promise.allSettled([
      API.get('/clients/'+cid+'/wealth-summary'),
      API.get('/clients/'+cid+'/wealth-positions'),
    ]);
    var summaryRes=results[0];
    var positionsRes=results[1];
    if(summaryRes.status==='fulfilled'&&summaryRes.value){
      var d=summaryRes.value;
      var fmt=function(v){return 'CHF '+Math.round(v).toLocaleString('de-CH');};
      var k=document.getElementById('kpi-reinvermoegen');
      if(k)k.textContent=fmt(d.net_worth_chf||0);
      var k2=document.getElementById('kpi-beratungsvermoegen');
      if(k2)k2.textContent=fmt(d.advisory_wealth_chf||0);
      var k2Card=k2&&k2.closest?k2.closest('.kpi'):null;
      var k2Sub=k2Card?k2Card.querySelector('.ks'):null;
      if(k2Sub){
        var share=wealthSharePercent(d.advisory_wealth_chf||0,d.gross_wealth_chf||0);
        k2Sub.textContent=share+'% des Bruttovermoegens';
      }
    }
    if(positionsRes.status==='fulfilled'){
      renderWealthPositions(positionsRes.value);
    }
  }catch(e){console.warn('refreshWealthUI:',e);}
}

function getDecisionChoiceMeta(choice){
  var map={
    option_a:{
      title:'Option A – Zuflüsse umlenken',
      detail:'CHF 155k in Anleihen und Liquidität. Organische Normalisierung innerhalb 12–18 Monaten.',
      decision:'Strategie angepasst'
    },
    option_b:{
      title:'Option B – Teilverkauf Aktien',
      detail:'Teilverkauf Aktien CHF 300k. Sofortige Normalisierung, Steuerfolgen separat prüfen.',
      decision:'Transaktion empfohlen'
    },
    option_c:{
      title:'Option C – Drift tolerieren',
      detail:'Drift für ein weiteres Quartal dokumentiert tolerieren, mit aktiver Kundenkommunikation.',
      decision:'Override bestätigt'
    }
  };
  return map[choice]||map.option_a;
}
function inferAdvisoryEntryType(title,decision){
  var text=(String(title||'')+' '+String(decision||'')).toLowerCase();
  if(text.indexOf('jahres')>=0)return 'Jahresreview';
  if(text.indexOf('quartal')>=0)return 'Quartalscheck';
  if(text.indexOf('drift')>=0)return 'Drift-Entscheid';
  if(text.indexOf('strategie')>=0)return 'Strategie-Anpassung';
  if(text.indexOf('override')>=0)return 'Override-Entscheid';
  if(text.indexOf('ereignis')>=0||text.indexOf('event')>=0)return 'Ereignis-Reaktion';
  if(text.indexOf('ziel')>=0)return 'Zieländerung';
  if(text.indexOf('restrik')>=0)return 'Restriktionsänderung';
  if(text.indexOf('eignung')>=0)return 'Eignungsprüfung';
  return 'Sonstiges';
}
function normalizeAdvisoryDecision(value){
  var raw=String(value||'').trim();
  var map={
    'Keine Transaktion':'Keine Transaktion',
    'Kauf':'Transaktion empfohlen',
    'Verkauf':'Transaktion empfohlen',
    'Umschichtung':'Strategie angepasst',
    'Profil anpassen':'Profil angepasst',
    'Override bestätigt':'Override bestätigt',
    'Kein Handlungsbedarf':'Kein Handlungsbedarf',
    'Transaktion empfohlen':'Transaktion empfohlen',
    'Strategie angepasst':'Strategie angepasst',
    'Profil angepasst':'Profil angepasst'
  };
  return map[raw]||raw||'Keine Transaktion';
}
function isCriticalReviewTrigger(trigger){
  if(!trigger)return false;
  var status=String(trigger.status||'');
  if(status==='Erledigt')return false;
  if(trigger.trigger_type==='Markt')return true;
  if(trigger.next_due_at){
    var dueText=String(trigger.next_due_at).slice(0,10);
    var due=new Date(dueText+'T00:00:00');
    var today=new Date();
    today.setHours(0,0,0,0);
    if(!isNaN(due.getTime())&&due<today)return true;
  }
  return false;
}
function renderReviewAlertStrip(triggers){
  var strip=document.getElementById('rv-alert-strip');
  if(!strip)return;
  var critical=(triggers||[]).filter(isCriticalReviewTrigger);
  if(!critical.length){
    strip.innerHTML='<div><div class="st">Keine kritischen Trigger offen</div><div class="ss">Review- und Governance-Lage ist aktuell stabil.</div></div><button class="btn-p" onclick="om(\'m-nt\')">Trigger definieren →</button>';
    return;
  }
  var first=critical[0];
  var label=critical.length+' kritische Trigger ausgelöst';
  var detail=(first.trigger_name||'Trigger')+(first.threshold_bps!=null?' · Schwelle '+formatInputPercent(first.threshold_bps)+'%':'')+(first.next_due_at?' · fällig '+formatDateSwiss(first.next_due_at):'');
  var action=first.trigger_type==='Markt'
    ? 'openDecisionTemplateModal(\''+escapeHtml(first.id||'')+'\')'
    : 'openAdvisoryLogModal(\''+escapeHtml(first.id||'')+'\')';
  strip.innerHTML='<div><div class="st">'+escapeHtml(label)+'</div><div class="ss">'+escapeHtml(detail)+'</div></div><button class="btn-p" onclick="'+action+'">Entscheidungsvorlage →</button>';
}
function renderReviewSummaryGrid(triggers){
  var grid=document.getElementById('rv-summary-grid');
  if(!grid)return;
  var items=Array.isArray(triggers)?triggers:[];
  var critical=items.filter(isCriticalReviewTrigger).length;
  var active=items.filter(function(item){return String(item.status||'')!=='Erledigt';}).length;
  var done=items.filter(function(item){return String(item.status||'')==='Erledigt';}).length;
  var nextDue=items
    .filter(function(item){return item&&item.next_due_at&&String(item.status||'')!=='Erledigt';})
    .sort(function(a,b){return String(a.next_due_at||'').localeCompare(String(b.next_due_at||''));})[0];
  grid.innerHTML=
    '<div style="background:var(--neg-lt);border:1px solid rgba(139,30,30,0.2);border-radius:var(--r2);padding:10px 12px"><div style="font-size:9px;font-weight:600;letter-spacing:0.08em;text-transform:uppercase;color:var(--neg);margin-bottom:4px">Kritisch</div><div style="font-family:var(--f-d);font-size:22px;font-weight:500;color:var(--neg)">'+critical+'</div><div style="font-size:10px;color:var(--n6)">Offene Markt- oder Überfälligkeits-Trigger</div></div>'+
    '<div style="background:var(--warn-lt);border:1px solid rgba(122,82,0,0.2);border-radius:var(--r2);padding:10px 12px"><div style="font-size:9px;font-weight:600;letter-spacing:0.08em;text-transform:uppercase;color:var(--warn);margin-bottom:4px">Aktiv</div><div style="font-family:var(--f-d);font-size:22px;font-weight:500;color:var(--warn)">'+active+'</div><div style="font-size:10px;color:var(--n6)">Noch nicht erledigt</div></div>'+
    '<div style="background:var(--pos-lt);border:1px solid rgba(14,107,65,0.2);border-radius:var(--r2);padding:10px 12px"><div style="font-size:9px;font-weight:600;letter-spacing:0.08em;text-transform:uppercase;color:var(--pos);margin-bottom:4px">Erledigt</div><div style="font-family:var(--f-d);font-size:22px;font-weight:500;color:var(--pos)">'+done+'</div><div style="font-size:10px;color:var(--n6)">Dokumentierte Reviews</div></div>'+
    '<div style="background:var(--surface);border:1px solid var(--b1);border-radius:var(--r2);padding:10px 12px"><div style="font-size:9px;font-weight:600;letter-spacing:0.08em;text-transform:uppercase;color:var(--n4);margin-bottom:4px">Nächster Review</div><div style="font-family:var(--f-d);font-size:22px;font-weight:500;color:var(--n8)">'+escapeHtml(nextDue?formatDateSwiss(nextDue.next_due_at):'—')+'</div><div style="font-size:10px;color:var(--n6)">'+escapeHtml(nextDue?(nextDue.trigger_name||'Trigger'):'Kein Termin offen')+'</div></div>';
}
function renderTriggerBucket(targetId,triggers){
  var root=document.getElementById(targetId);
  if(!root)return;
  var items=Array.isArray(triggers)?triggers:[];
  if(!items.length){
    root.innerHTML='<div style="padding:12px 14px;font-size:10px;color:var(--n4)">Keine Trigger in dieser Kategorie definiert.</div>';
    return;
  }
  root.innerHTML=items.map(function(trigger){
    var critical=isCriticalReviewTrigger(trigger);
    var status=String(trigger.status||'Aktiv');
    var tagClass=status==='Erledigt'?'tg':(critical?'tr2':'ta');
    var tagLabel=status==='Erledigt'?'Erledigt':(trigger.threshold_bps!=null?formatInputPercent(trigger.threshold_bps)+'%':'Aktiv');
    var detail=trigger.trigger_type==='Zeit'
      ? ((trigger.next_due_at?'Nächster Termin '+formatDateSwiss(trigger.next_due_at):'Kein Termin gesetzt')+(trigger.frequency?' · '+trigger.frequency:''))
      : trigger.trigger_type==='Markt'
        ? ((trigger.threshold_bps!=null?'Schwelle ±'+formatInputPercent(trigger.threshold_bps)+'%':'Markt-Trigger')+(trigger.triggered_notes?' · '+trigger.triggered_notes:''))
        : (trigger.next_due_at?'Review bis '+formatDateSwiss(trigger.next_due_at):'Event-basierter Review-Trigger');
    var actions=status==='Erledigt'
      ? ''
      : '<div style="display:flex;gap:5px;margin-top:6px"><button onclick="openAdvisoryLogModal(\''+escapeHtml(trigger.id||'')+'\')" style="font-size:9px;padding:3px 8px;background:'+(critical?'var(--neg)':'none')+';color:'+(critical?'#fff':'var(--n5)')+';border:'+(critical?'none':'1px solid var(--b2)')+';border-radius:var(--r);cursor:pointer;font-family:var(--f-s)">Protokoll erfassen</button>'+(trigger.trigger_type==='Markt'?'<button onclick="openDecisionTemplateModal(\''+escapeHtml(trigger.id||'')+'\')" style="font-size:9px;padding:3px 8px;background:none;border:1px solid var(--b2);border-radius:var(--r);cursor:pointer;color:var(--n5);font-family:var(--f-s)">Entscheidung</button>':'')+'</div>';
    return '<div class="trig '+(critical?'al':'')+'" style="padding:10px 14px;border-bottom:1px solid var(--b1)"><div class="trigh"><span class="trign">'+escapeHtml(trigger.trigger_name||'Trigger')+'</span><span class="tag '+tagClass+'">'+escapeHtml(tagLabel)+'</span></div><div class="trigd">'+escapeHtml(detail)+'</div>'+actions+'</div>';
  }).join('');
}
function renderAdvisoryLogList(logs){
  var root=document.getElementById('rv-log-list');
  if(!root)return;
  var items=Array.isArray(logs)?logs:[];
  if(!items.length){
    root.innerHTML='<div style="font-size:10px;color:var(--n4)">Noch keine Advisory-Einträge dokumentiert.</div>';
    return;
  }
  root.innerHTML=items.map(function(entry){
    var decision=entry.decision||entry.entry_type||'Dokumentiert';
    var tagClass=/keine/i.test(decision)?'tg':(/kauf|verkauf|umschichtung/i.test(decision)?'ta':'tn');
    return '<div class="logi"><div class="logh"><div class="logt">'+escapeHtml(entry.title||'Advisory-Eintrag')+'</div><div class="logm"><span class="logd">'+escapeHtml(formatDateSwiss(entry.entry_date))+'</span><span class="tag '+tagClass+'">'+escapeHtml(decision)+'</span></div></div><div class="logdesc">'+escapeHtml(entry.description||'Ohne Zusatzbegründung dokumentiert.')+'</div></div>';
  }).join('');
}
function renderDocumentGrid(documents){
  var grid=document.getElementById('rv-doc-grid');
  if(!grid)return;
  var docs=Array.isArray(documents)?documents:[];
  var createCard='<div style="border:1px dashed var(--b2);border-radius:var(--r2);padding:12px;text-align:center"><div style="font-size:26px;margin-bottom:6px">✎</div><div style="font-size:11px;font-weight:500;color:var(--n8);margin-bottom:3px">Neuer Entwurf</div><div style="font-size:9px;color:var(--n5);margin-bottom:10px">Anlagestrategie oder Beratungsdokument erfassen</div><button onclick="om(\'m-contract-edit\')" style="background:var(--n6);color:#fff;border:none;border-radius:var(--r);font-size:10px;padding:5px 12px;cursor:pointer;font-family:var(--f-s);width:100%">Entwurf öffnen</button></div>';
  if(!docs.length){
    grid.innerHTML=createCard+'<div style="grid-column:span 3;border:1px dashed var(--b2);border-radius:var(--r2);padding:16px;font-size:11px;color:var(--n5);line-height:1.6">Noch keine Beratungsdokumente gespeichert. Über den Entwurfs-Block links kann eine Anlagestrategie als echter Dokumenten-Entwurf persistiert werden.</div>';
    return;
  }
  grid.innerHTML=createCard+docs.map(function(doc){
    var signedAdvisor=Number(doc.signed_by_advisor||0)===1;
    var printAction='printDocumentTypeReport(\''+escapeHtml(doc.document_type||'Dokument')+'\')';
    var action=signedAdvisor
      ? '<div style="font-size:9px;color:var(--pos);margin-top:6px">Berater unterzeichnet</div>'
      : '<button onclick="signDocumentAsAdvisor(\''+escapeHtml(doc.id||'')+'\')" style="background:none;border:1px solid var(--b2);color:var(--n5);border-radius:var(--r);font-size:10px;padding:5px 8px;cursor:pointer;font-family:var(--f-s);margin-top:6px;width:100%">Berater signieren</button>';
    return '<div style="border:1px solid var(--b1);border-radius:var(--r2);padding:12px;text-align:center"><div style="font-size:26px;margin-bottom:6px">📄</div><div style="font-size:11px;font-weight:500;color:var(--n8);margin-bottom:3px">'+escapeHtml(doc.title||doc.document_type||'Dokument')+'</div><div style="font-size:9px;color:var(--n5);margin-bottom:10px">'+escapeHtml((doc.document_type||'Dokument')+' · '+(doc.status||'Entwurf'))+'</div><button onclick="printReport()" style="background:var(--n6);color:#fff;border:none;border-radius:var(--r);font-size:10px;padding:5px 12px;cursor:pointer;font-family:var(--f-s);width:100%">Seite drucken</button>'+action+'</div>';
  }).join('');
  Array.prototype.forEach.call(grid.querySelectorAll('button[onclick="printReport()"]'),function(btn,idx){
    var doc=docs[idx];
    if(!doc)return;
    btn.textContent='Kapitel drucken';
    btn.setAttribute('onclick',"printDocumentTypeReport('"+String(doc.document_type||'Dokument').replace(/'/g,"\\'")+"')");
  });
}
function renderReviewState(state){
  var triggers=(state&&state.triggers)||[];
  var time=triggers.filter(function(item){return item.trigger_type==='Zeit';});
  var market=triggers.filter(function(item){return item.trigger_type==='Markt';});
  var event=triggers.filter(function(item){return item.trigger_type==='Ereignis';});
  renderReviewAlertStrip(triggers);
  renderReviewSummaryGrid(triggers);
  renderTriggerBucket('rv-trigger-time',time);
  renderTriggerBucket('rv-trigger-market',market);
  renderTriggerBucket('rv-trigger-event',event);
  renderAdvisoryLogList((state&&state.logs)||[]);
  renderDocumentGrid((state&&state.documents)||[]);
  var counter=document.getElementById('trigger-count');
  if(counter)counter.textContent=String(triggers.filter(function(item){return String(item.status||'')!=='Erledigt';}).length)+' Trigger';
}
function buildDemoReviewState(){
  var baseDate=new Date().toISOString().slice(0,10);
  var personaName=currentPersona?((currentPersona.first_name||currentPersona.name||'Kunde')):'Kunde';
  return {
    triggers:[
      {id:'demo-trigger-review',trigger_type:'Zeit',trigger_name:'Jahres-Review',frequency:'12 Monate',status:'Aktiv',next_due_at:baseDate},
      {id:'demo-trigger-drift',trigger_type:'Markt',trigger_name:'Aktienquote-Drift',threshold_bps:500,status:'Aktiv',triggered_notes:'Demo-Modus – keine Live-Bewertung'},
      {id:'demo-trigger-event',trigger_type:'Ereignis',trigger_name:'Lebensevent / Zieländerung',status:'Aktiv',next_due_at:null}
    ],
    logs:[
      {id:'demo-log-1',title:'Demo-Review für '+personaName,entry_date:baseDate,decision:'Keine Transaktion',description:'Demo-Modus: Review- und Governance-Daten werden nicht persistent gespeichert.',entry_type:'Sonstiges'}
    ],
    documents:[
      {id:'demo-doc-1',document_type:'Anlagestrategie',title:'Anlagestrategie (Demo)',status:'Entwurf',signed_by_advisor:0}
    ]
  };
}
function renderDemoReviewUI(){
  currentReviewState=buildDemoReviewState();
  renderReviewState(currentReviewState);
}
async function refreshReviewUI(mid){
  if(!mid||isDemoMandateId(mid)){
    renderDemoReviewUI();
    return;
  }
  try{
    await API.fetch('/mandates/'+mid+'/triggers/system-refresh',{method:'POST'}).catch(function(e){
      console.warn('refreshSystemReviewTriggers:',e);
      return null;
    });
    var results=await Promise.allSettled([
      API.get('/mandates/'+mid+'/triggers'),
      API.get('/mandates/'+mid+'/advisory-log'),
      API.get('/mandates/'+mid+'/documents')
    ]);
    currentReviewState={
      triggers:results[0].status==='fulfilled'&&Array.isArray(results[0].value)?results[0].value:[],
      logs:results[1].status==='fulfilled'&&Array.isArray(results[1].value)?results[1].value:[],
      documents:results[2].status==='fulfilled'&&Array.isArray(results[2].value)?results[2].value:[]
    };
    renderReviewState(currentReviewState);
  }catch(e){
    console.warn('refreshReviewUI:',e);
  }
}
async function saveAdvisoryLogEntry(){
  var title=getInputValue('ne-title').trim();
  var decisionRaw=getInputValue('ne-decision')||'Keine Transaktion';
  var decision=normalizeAdvisoryDecision(decisionRaw);
  var description=getInputValue('ne-description').trim();
  var entryDate=getInputValue('ne-date')||new Date().toISOString().slice(0,10);
  var triggerId=getInputValue('ne-trigger-id')||null;
  var btn=document.getElementById('btn-ne-save');
  var mid=getActiveMandateId();
  if(!title){showModalFeedback('ne-error',btn,'Bitte Anlass / Titel eingeben.',true);return;}
  var descriptionText=description;
  if(decisionRaw&&decisionRaw!==decision){
    descriptionText=joinNotes(['Operative Ausprägung: '+decisionRaw,description]);
  }
  var payload={
    entry_type:inferAdvisoryEntryType(title,decision),
    title:title,
    description:descriptionText||null,
    decision:decision,
    trigger_id:triggerId,
    entry_date:entryDate
  };
  if(btn){btn.disabled=true;btn.textContent='Speichern...';}
  if(mid&&!isDemoMandateId(mid)){
    try{
      await API.post('/mandates/'+mid+'/advisory-log',payload);
      showModalFeedback('ne-error',btn,'✓ Protokolleintrag gespeichert',false);
      await refreshReviewUI(mid);
      setTimeout(function(){cm('m-ne');},500);
    }catch(e){
      showModalFeedback('ne-error',btn,'Fehler: '+(e.detail||e.message||'?'),true);
    }
  } else {
    currentReviewState.logs=[Object.assign({id:'demo-log-'+Date.now()},payload)].concat(currentReviewState.logs||[]);
    renderReviewState(currentReviewState);
    showModalFeedback('ne-error',btn,'✓ Demo-Modus: Eintrag ergänzt',false);
    setTimeout(function(){cm('m-ne');},700);
  }
}
function buildTriggerPayload(){
  var rawType=getInputValue('nt-type')||'Zeitbasiert';
  var triggerName=getInputValue('nt-name').trim();
  var rawThreshold=getInputValue('nt-threshold').trim();
  var triggerType=rawType==='Zeitbasiert'?'Zeit':(rawType==='Bandbreite / Drift'?'Markt':'Ereignis');
  var payload={trigger_type:triggerType,trigger_name:triggerName,threshold_bps:null,frequency:null,next_due_at:null};
  if(triggerType==='Zeit'){
    var months=12;
    if(/quartal/i.test(triggerName))months=3;
    var match=rawThreshold.match(/(\d+)/);
    if(match)months=Math.max(1,parseInt(match[1],10)||months);
    payload.frequency=months<=1?'monatlich':(months<=3?'quartalsweise':(months<=6?'halbjährlich':'jährlich'));
    var due=new Date();
    due.setMonth(due.getMonth()+months);
    payload.next_due_at=due.toISOString().slice(0,10);
  } else if(triggerType==='Markt'){
    var pct=parseFloat(rawThreshold.replace(',', '.').replace(/[^\d.-]/g,''));
    payload.threshold_bps=isFinite(pct)?Math.round(Math.abs(pct)*100):500;
  } else {
    payload.frequency='bei Ereignis';
  }
  return payload;
}
async function saveReviewTrigger(){
  var btn=document.getElementById('btn-nt-save');
  var mid=getActiveMandateId();
  var payload=buildTriggerPayload();
  if(!payload.trigger_name){showModalFeedback('nt-error',btn,'Bitte Bezeichnung eingeben.',true);return;}
  if(btn){btn.disabled=true;btn.textContent='Aktivieren...';}
  if(mid&&!isDemoMandateId(mid)){
    try{
      await API.post('/mandates/'+mid+'/triggers',payload);
      showModalFeedback('nt-error',btn,'✓ Trigger angelegt',false);
      await refreshReviewUI(mid);
      setTimeout(function(){cm('m-nt');},500);
    }catch(e){
      showModalFeedback('nt-error',btn,'Fehler: '+(e.detail||e.message||'?'),true);
    }
  } else {
    currentReviewState.triggers=[Object.assign({id:'demo-trigger-'+Date.now(),status:'Aktiv'},payload)].concat(currentReviewState.triggers||[]);
    renderReviewState(currentReviewState);
    showModalFeedback('nt-error',btn,'✓ Demo-Modus: Trigger ergänzt',false);
    setTimeout(function(){cm('m-nt');},700);
  }
}
async function saveContractDocumentDraft(){
  var title=getInputValue('contract-title').trim();
  var intro=getInputValue('contract-intro').trim();
  var disclaimer=getInputValue('contract-disclaimer').trim();
  var special=getInputValue('contract-special').trim();
  var place=getInputValue('contract-place').trim();
  var signDate=getInputValue('contract-date')||new Date().toISOString().slice(0,10);
  var btn=document.getElementById('btn-contract-save');
  var mid=getActiveMandateId();
  if(!title){showModalFeedback('contract-error',btn,'Bitte Dokumenttitel eingeben.',true);return;}
  var payload={
    document_type:'Anlagestrategie',
    title:title,
    content_json:JSON.stringify({
      intro:intro,
      disclaimer:disclaimer,
      special:special,
      place:place,
      sign_date:signDate,
      client_name:currentPersona?((currentPersona.first_name||currentPersona.name||'')+' '+(currentPersona.last_name||'')).trim():null
    })
  };
  if(btn){btn.disabled=true;btn.textContent='Speichern...';}
  if(mid&&!isDemoMandateId(mid)){
    try{
      await API.post('/mandates/'+mid+'/documents',payload);
      showModalFeedback('contract-error',btn,'✓ Dokument-Entwurf gespeichert',false);
      await refreshReviewUI(mid);
      setTimeout(function(){cm('m-contract-edit');},500);
    }catch(e){
      showModalFeedback('contract-error',btn,'Fehler: '+(e.detail||e.message||'?'),true);
    }
  } else {
    currentReviewState.documents=[{
      id:'demo-doc-'+Date.now(),
      document_type:'Anlagestrategie',
      title:title,
      status:'Entwurf',
      signed_by_advisor:0
    }].concat(currentReviewState.documents||[]);
    renderReviewState(currentReviewState);
    showModalFeedback('contract-error',btn,'✓ Demo-Modus: Dokument ergänzt',false);
    setTimeout(function(){cm('m-contract-edit');},700);
  }
}
async function signDocumentAsAdvisor(docId){
  var mid=getActiveMandateId();
  if(!docId)return;
  if(mid&&!isDemoMandateId(mid)){
    try{
      await API.post('/mandates/'+mid+'/documents/'+docId+'/sign',{signed_by_advisor:true});
      await refreshReviewUI(mid);
    }catch(e){
      console.error('signDocumentAsAdvisor:',e);
    }
  } else {
    currentReviewState.documents=(currentReviewState.documents||[]).map(function(doc){
      if(String(doc.id||'')!==String(docId||''))return doc;
      return Object.assign({},doc,{signed_by_advisor:1,status:'Unterzeichnet'});
    });
    renderReviewState(currentReviewState);
  }
}
async function documentDecisionTemplate(){
  var btn=document.getElementById('btn-ed-save');
  var mid=getActiveMandateId();
  var ed=document.getElementById('m-ed');
  var triggerId=ed?ed.dataset.triggerId||'':'';
  var meta=getDecisionChoiceMeta(currentDecisionChoice);
  var payload={
    entry_type:'Drift-Entscheid',
    title:'Entscheidungsvorlage – '+meta.title,
    description:meta.detail,
    decision:meta.decision,
    trigger_id:triggerId||null,
    entry_date:new Date().toISOString().slice(0,10)
  };
  if(btn){btn.disabled=true;btn.textContent='Dokumentieren...';}
  if(mid&&!isDemoMandateId(mid)){
    try{
      await API.post('/mandates/'+mid+'/advisory-log',payload);
      if(triggerId){
        await API.put('/mandates/'+mid+'/triggers/'+triggerId+'/resolve',{
          decision:meta.title,
          triggered_notes:meta.detail
        });
      }
      await refreshReviewUI(mid);
      setTimeout(function(){cm('m-ed');},500);
    }catch(e){
      showModalFeedback('ed-error',btn,'Fehler: '+(e.detail||e.message||'?'),true);
    }
  } else {
    currentReviewState.logs=[Object.assign({id:'demo-log-'+Date.now()},payload)].concat(currentReviewState.logs||[]);
    currentReviewState.triggers=(currentReviewState.triggers||[]).map(function(trigger){
      if(String(trigger.id||'')!==String(triggerId||''))return trigger;
      return Object.assign({},trigger,{status:'Erledigt',triggered_notes:meta.detail});
    });
    renderReviewState(currentReviewState);
    showModalFeedback('ed-error',btn,'✓ Demo-Modus: Entscheidung dokumentiert',false);
    setTimeout(function(){cm('m-ed');},700);
  }
}

function normalizeHouseholdValue(value){
  if(value==='Single')return 'Einzelperson';
  if(value==='Couple')return 'Paar';
  if(value==='Family')return 'Familie';
  return value||'Einzelperson';
}
function updateStammdatenHeader(firstName,lastName,household,canton,isDemo){
  var ph=document.querySelector('#page-sd .ph-s');
  var parts=[firstName+' '+lastName];
  if(household)parts.push(household);
  if(canton)parts.push(canton);
  if(isDemo)parts.push('(Demo)');
  if(ph)ph.textContent=parts.join(' · ');
  document.title='5eyes · '+firstName+' '+lastName;
  var activeName=document.querySelector('.client.active .client-n');
  if(activeName)activeName.textContent=firstName+' '+lastName;
}
async function saveClientData(){
  var fn=(document.getElementById('es-firstname')||{value:''}).value.trim();
  var ln=(document.getElementById('es-lastname')||{value:''}).value.trim();
  var dob=(document.getElementById('es-dob')||{value:''}).value||null;
  var can=(document.getElementById('es-canton')||{value:''}).value.trim()||null;
  var hh=(document.getElementById('es-household')||{value:'Einzelperson'}).value||'Einzelperson';
  var lang=(document.getElementById('es-lang')||{value:'DE'}).value||'DE';
  var civil=(document.getElementById('es-civil')||{value:''}).value||null;
  var prof=(document.getElementById('es-profession')||{value:''}).value.trim()||null;
  var btn=document.getElementById('btn-es-save');
  if(!fn||!ln){showModalFeedback('es-error',btn,'Bitte Vor- und Nachname eingeben.',true);return;}
  var cid=getActiveClientId();
  if(btn){btn._origText='Speichern';btn.disabled=true;btn.textContent='Speichern...';}
  var payload={first_name:fn,last_name:ln,date_of_birth:dob,canton:can,household_type:hh,language:lang,civil_status:civil,profession:prof};
  if(cid&&!isDemoClientId(cid)){
    try{
      await API.put('/clients/'+cid,payload);
      showModalFeedback('es-error',btn,'✓ Gespeichert',false);
      updateStammdatenHeader(fn,ln,hh,can,false);
      if(currentPersona){
        currentPersona.first_name=fn;
        currentPersona.last_name=ln;
        currentPersona.name=fn+' '+ln;
        currentPersona.date_of_birth=dob;
        currentPersona.canton=can;
        currentPersona.household_type=hh;
        currentPersona.household=hh;
        currentPersona.language=lang;
        currentPersona.civil_status=civil;
        currentPersona.profession=prof;
        if(can)currentPersona.region=can;
      }
      var clientEntry=liveClients.find(function(c){return c.id===cid;});
      if(clientEntry){
        clientEntry.first_name=fn;
        clientEntry.last_name=ln;
        clientEntry.canton=can;
        clientEntry.household_type=hh;
        clientEntry.language=lang;
        clientEntry.civil_status=civil;
        clientEntry.profession=prof;
      }
      setTimeout(function(){cm('m-es');},1500);
    }catch(e){showModalFeedback('es-error',btn,'Fehler: '+(e.detail||e.message||'?'),true);}
  } else {
    updateStammdatenHeader(fn,ln,hh,can,true);
    if(currentPersona){
      currentPersona.first_name=fn;
      currentPersona.last_name=ln;
      currentPersona.name=fn+' '+ln;
      currentPersona.date_of_birth=dob;
      currentPersona.canton=can;
      currentPersona.household_type=hh;
      currentPersona.household=hh;
      currentPersona.language=lang;
      currentPersona.civil_status=civil;
      currentPersona.profession=prof;
      if(can)currentPersona.region=can;
    }
    showModalFeedback('es-error',btn,'✓ Demo-Modus aktualisiert',false);
    setTimeout(function(){cm('m-es');},1200);
  }
}
function openStammdatenModal(){
  if(currentPersona){
    var p=currentPersona;
    var sv=function(id,v){var el=document.getElementById(id);if(el&&v!=null)el.value=v;};
    sv('es-firstname',p.first_name||(p.name?p.name.split(' ')[0]:''));
    sv('es-lastname', p.last_name||(p.name?p.name.split(' ').slice(1).join(' '):''));
    sv('es-dob',      p.date_of_birth||'');
    sv('es-canton',   p.canton||'');
    sv('es-household',normalizeHouseholdValue(p.household_type||p.household));
    sv('es-lang',     p.language||'DE');
    sv('es-civil',    p.civil_status||'');
    sv('es-profession',p.profession||'');
  }
  var e=document.getElementById('es-error');if(e)e.style.display='none';
  om('m-es');
}

function goalFrequencyKey(value){
  return cashflowFrequencyKey(value||'jaehrlich')||'jaehrlich';
}
function isRecurringGoalType(type){
  return type==='Wiederkehrende_Ausgabe'||type==='Pensionsausgabe';
}
function isWealthGoalType(type){
  return type==='Kapitalerhalt'||type==='Verm\u00f6gensziel';
}
function isReturnGoalType(type){
  return type==='Renditeziel';
}
function isMaxGoalType(type){
  return type==='Maximierung';
}
function goalDisplayFrequency(value){
  var map={
    monatlich:'monatlich',
    quartalsweise:'quartalsweise',
    halbjaehrlich:'halbj\u00e4hrlich',
    jaehrlich:'j\u00e4hrlich',
    einmalig:'einmalig'
  };
  return map[goalFrequencyKey(value)]||String(value||'');
}
function goalAmountLabel(type){
  if(isReturnGoalType(type))return 'Zielrendite p.a. (%) *';
  if(isWealthGoalType(type))return 'Zielverm\u00f6gen (CHF) *';
  if(isRecurringGoalType(type))return 'Betrag pro Periode (CHF) *';
  if(type==='Einmalige_Ausgabe')return 'Zielbetrag (CHF) *';
  if(isMaxGoalType(type))return 'Kein fixer Zielbetrag';
  return 'Zielbetrag *';
}
function goalAmountSummary(goal){
  var type=goal&&goal.goal_type||'';
  if(isReturnGoalType(type)){
    return goal&&goal.target_return_bps!=null ? formatBpsPercent(goal.target_return_bps)+' p.a.' : 'Renditeziel';
  }
  if(isMaxGoalType(type))return 'Maximierung';
  if(isWealthGoalType(type))return formatRappen(goal&&goal.target_wealth_rappen||0);
  return formatRappen(goal&&goal.target_amount_rappen||0);
}
function goalTimingLabel(goal){
  var direct=String(goal&&goal.timing_label||'').trim();
  if(direct){
    return direct
      .replace(/\s*\|\s*/g,' \u00b7 ')
      .replace(/halbjaehrlich/g,'halbj\u00e4hrlich')
      .replace(/jaehrlich/g,'j\u00e4hrlich')
      .replace(/Pruefen/g,'Pr\u00fcfen')
      .replace(/Gefaehrdet/g,'Gef\u00e4hrdet');
  }
  var type=goal&&goal.goal_type||'Einmalige_Ausgabe';
  var start=normalizeCashflowDateValue(goal&&goal.start_date);
  var target=normalizeCashflowDateValue(goal&&goal.target_date);
  var years=parseInt(goal&&goal.horizon_years,10)||0;
  if(isRecurringGoalType(type)){
    var parts=[goalDisplayFrequency(goal&&goal.frequency||'jaehrlich')];
    if(start)parts.push('ab '+start);
    if(Number(goal&&goal.is_ongoing||0))parts.push('laufend');
    else if(target)parts.push('bis '+target);
    else if(years>0)parts.push('Horizont '+years+' J.');
    return parts.join(' \u00b7 ');
  }
  if(type==='Einmalige_Ausgabe'&&(target||start))return 'am '+(target||start);
  if(target)return 'bis '+target;
  if(years>0)return years+' J.';
  return 'offen';
}
function syncGoalModalState(){
  var type=getInputValue('nz-type')||'Einmalige_Ausgabe';
  var amountInput=document.getElementById('nz-amount');
  var amountWrap=amountInput&&amountInput.closest?amountInput.closest('.fg'):null;
  var amountLabel=document.getElementById('nz-amount-label');
  var startWrap=document.getElementById('nz-start-wrap');
  var startLabel=document.getElementById('nz-start-label');
  var targetWrap=document.getElementById('nz-target-wrap');
  var targetLabel=document.getElementById('nz-target-label');
  var frequencyWrap=document.getElementById('nz-frequency-wrap');
  var ongoingWrap=document.getElementById('nz-ongoing-wrap');
  var hint=document.getElementById('nz-date-hint');
  var ongoing=getInputValue('nz-ongoing')==='true';
  if(amountLabel)amountLabel.textContent=goalAmountLabel(type);
  if(amountWrap)amountWrap.style.display=isMaxGoalType(type)?'none':'';
  if(startWrap)startWrap.style.display=isRecurringGoalType(type)?'':'none';
  if(startLabel)startLabel.textContent=isRecurringGoalType(type)?'Beginn *':'Start';
  if(frequencyWrap)frequencyWrap.style.display=isRecurringGoalType(type)?'':'none';
  if(ongoingWrap)ongoingWrap.style.display=isRecurringGoalType(type)?'':'none';
  if(targetWrap){
    if(type==='Einmalige_Ausgabe'||isWealthGoalType(type)||isReturnGoalType(type)||isMaxGoalType(type))targetWrap.style.display='';
    else targetWrap.style.display=ongoing?'none':'';
  }
  if(targetLabel){
    if(type==='Einmalige_Ausgabe')targetLabel.textContent='F\u00e4lligkeit / Zieldatum *';
    else if(isRecurringGoalType(type))targetLabel.textContent='Enddatum (optional)';
    else if(isWealthGoalType(type)||isReturnGoalType(type))targetLabel.textContent='Zieldatum (optional)';
    else if(isMaxGoalType(type))targetLabel.textContent='Review-/Zieldatum (optional)';
    else targetLabel.textContent='Zieldatum';
  }
  if(isRecurringGoalType(type)){
    if(!getInputValue('nz-frequency')||goalFrequencyKey(getInputValue('nz-frequency'))==='einmalig'){
      setSelectValue('nz-frequency',type==='Pensionsausgabe'?'monatlich':'jaehrlich');
    }
    if(hint)hint.textContent='Wiederkehrende Ziele werden mit Beginn, Frequenz und optionalem Enddatum erfasst.';
  }else if(type==='Einmalige_Ausgabe'){
    setSelectValue('nz-frequency','einmalig');
    setSelectValue('nz-ongoing','false');
    if(hint)hint.textContent='Einmalige Entnahmen erhalten ein klares F\u00e4lligkeitsdatum; der Zeithorizont wird daraus abgeleitet.';
  }else if(isWealthGoalType(type)){
    setSelectValue('nz-ongoing','false');
    if(hint)hint.textContent='Verm\u00f6gensziele k\u00f6nnen \u00fcber Datum oder Horizont terminiert werden.';
  }else if(isReturnGoalType(type)){
    setSelectValue('nz-ongoing','false');
    if(hint)hint.textContent='Renditeziele speichern eine Zielrendite p.a. und optional ein Review-Datum.';
  }else if(isMaxGoalType(type)){
    setSelectValue('nz-ongoing','false');
    if(hint)hint.textContent='Maximierung hat keinen fixen Zielbetrag; relevant sind Priorit\u00e4t, Scope und Zeitfenster.';
  }
}
function resetGoalModal(){
  currentGoalEditId=null;
  setInputValue('nz-label','');
  setSelectValue('nz-type','Einmalige_Ausgabe');
  setSelectValue('nz-prio','2');
  setSelectValue('nz-scope','Beratungsverm\u00f6gen');
  setInputValue('nz-amount','');
  setInputValue('nz-horizon','10');
  setInputValue('nz-start-date','');
  setInputValue('nz-target-date','');
  setSelectValue('nz-frequency','jaehrlich');
  setSelectValue('nz-ongoing','false');
  var btn=document.getElementById('btn-nz-save');
  if(btn){btn.textContent='Speichern';btn.disabled=false;}
  var err=document.getElementById('nz-error');
  if(err){err.style.display='none';err.textContent='';}
  syncGoalModalState();
}
function openGoalEditor(goalId){
  var goal=(currentGoals||[]).find(function(item){return String(item.id||'')===String(goalId||'');});
  if(!goal)return;
  currentGoalEditId=goal.id;
  var goalType=goal.goal_type||'Einmalige_Ausgabe';
  var priorityMap={'Hart':'1','Prim\u00e4r':'2','Primaer':'2','Opportunistisch':'3'};
  setInputValue('nz-label',goal.label||'');
  setSelectValue('nz-type',goalType);
  setSelectValue('nz-prio',priorityMap[goal.hardness]||String(goal.rank||2));
  setSelectValue('nz-scope',goal.goal_scope||'Beratungsverm\u00f6gen');
  if(isReturnGoalType(goalType))setInputValue('nz-amount',formatInputPercent(goal.target_return_bps));
  else if(isWealthGoalType(goalType))setInputValue('nz-amount',formatInputCHF(goal.target_wealth_rappen));
  else if(isMaxGoalType(goalType))setInputValue('nz-amount','');
  else setInputValue('nz-amount',formatInputCHF(goal.target_amount_rappen));
  setInputValue('nz-horizon',goal.horizon_years==null?'10':goal.horizon_years);
  setInputValue('nz-start-date',normalizeCashflowDateValue(goal.start_date));
  setInputValue('nz-target-date',normalizeCashflowDateValue(goal.target_date));
  setSelectValue('nz-frequency',goalFrequencyKey(goal.frequency||'jaehrlich'));
  setSelectValue('nz-ongoing',Number(goal.is_ongoing||0)?'true':'false');
  var btn=document.getElementById('btn-nz-save');
  if(btn){btn.textContent='Aktualisieren';btn.disabled=false;}
  var err=document.getElementById('nz-error');
  if(err){err.style.display='none';err.textContent='';}
  syncGoalModalState();
  var modal=document.getElementById('m-nz');
  if(modal)modal.classList.add('open');
}
function renderGoalList(items,isDemo){
  var zl=document.getElementById('zl');
  if(!zl)return;
  if(!Array.isArray(items)||!items.length){
    zl.innerHTML='';
    return;
  }
  var pc={'Hart':'p1','Prim\u00e4r':'p2','Primaer':'p2','Opportunistisch':'p3'};
  zl.innerHTML=items.map(function(goal,index){
    var pct=goal.achievement_score!=null?Number(goal.achievement_score):50;
    var tone=pct>=70?'fg':pct>=45?'fa':'fr';
    var tagTone=pct>=70?'tg':pct>=45?'ta':'tr2';
    var tagLabel=pct>=70?'On Track':pct>=45?'Pr\u00fcfen':'Gef\u00e4hrdet';
    var meta=[goalAmountSummary(goal),goalTimingLabel(goal)];
    if(isDemo)meta.push('Demo');
    return '<div class="goal" draggable="true" data-goalid="'+escapeHtml(goal.id||'')+'">'+
      '<div class="pd '+(pc[goal.hardness]||'p2')+'">'+(index+1)+'</div>'+
      '<div class="gi"><div class="gn">'+escapeHtml(goal.label||'Ziel')+'</div><div class="gd">'+escapeHtml(meta.filter(Boolean).join(' \u00b7 '))+'</div></div>'+
      '<span class="tag '+tagTone+'">'+tagLabel+'</span>'+
      '<div class="gbw"><div class="gp">'+Math.round(pct)+' %</div><div class="gb"><div class="gf '+tone+'" style="width:'+Math.max(0,Math.min(100,Math.round(pct)))+'%"></div></div></div>'+
      '<div><button class="btn-ico e" onclick="openGoalEditor(\''+escapeHtml(goal.id||'')+'\')">\u270e</button><button class="btn-ico" onclick="dg(this)">\u2715</button></div></div>';
  }).join('');
  setupDrag();
}
function buildDemoGoalRecord(goalId,payload,existingGoal){
  return Object.assign({},existingGoal||{},{
    id:goalId,
    goal_family:payload.goal_family,
    goal_type:payload.goal_type,
    label:payload.label,
    rank:payload.rank,
    goal_scope:payload.goal_scope,
    value_mode:payload.value_mode,
    target_amount_rappen:payload.target_amount_rappen,
    target_wealth_rappen:payload.target_wealth_rappen,
    target_return_bps:payload.target_return_bps,
    start_date:payload.start_date,
    horizon_years:payload.horizon_years,
    target_date:payload.target_date,
    is_ongoing:payload.is_ongoing?1:0,
    frequency:payload.frequency,
    hardness:payload.hardness,
    achievement_score:existingGoal&&existingGoal.achievement_score!=null?existingGoal.achievement_score:50
  });
}
async function saveGoal(){
  var label=getInputValue('nz-label').trim();
  var type=getInputValue('nz-type')||'Einmalige_Ausgabe';
  var prio=getInputValue('nz-prio')||'2';
  var scope=getInputValue('nz-scope')||'Beratungsverm\u00f6gen';
  var amountRaw=getInputValue('nz-amount').trim();
  var horizonRaw=parseInt(getInputValue('nz-horizon'),10);
  var horizon=isFinite(horizonRaw)&&horizonRaw>0?horizonRaw:null;
  var startDate=normalizeCashflowDateValue(getInputValue('nz-start-date'));
  var targetDate=normalizeCashflowDateValue(getInputValue('nz-target-date'));
  var frequency=goalFrequencyKey(getInputValue('nz-frequency')||'jaehrlich');
  var isOngoing=getInputValue('nz-ongoing')==='true';
  var btn=document.getElementById('btn-nz-save');
  var isEdit=!!currentGoalEditId;
  if(!label){showModalFeedback('nz-error',btn,'Bitte Bezeichnung eingeben.',true);return;}
  if(!isMaxGoalType(type)){
    if(!amountRaw){showModalFeedback('nz-error',btn,isReturnGoalType(type)?'Bitte Zielrendite eingeben.':'Bitte g\u00fcltigen Betrag eingeben.',true);return;}
    if(isReturnGoalType(type)){
      if(parsePercentToBps(amountRaw)==null){showModalFeedback('nz-error',btn,'Bitte g\u00fcltige Zielrendite eingeben.',true);return;}
    }else if(isNaN(parseFloat(amountRaw.replace(',','.')))){
      showModalFeedback('nz-error',btn,'Bitte g\u00fcltigen Betrag eingeben.',true);
      return;
    }
  }
  if(type==='Einmalige_Ausgabe'){
    if(!targetDate&&!startDate){showModalFeedback('nz-error',btn,'Bitte F\u00e4lligkeitsdatum f\u00fcr die einmalige Entnahme eingeben.',true);return;}
    if(!targetDate)targetDate=startDate;
    if(!startDate)startDate=targetDate;
    frequency='einmalig';
    isOngoing=false;
  }else if(isRecurringGoalType(type)){
    if(!startDate){showModalFeedback('nz-error',btn,'Bitte Beginn f\u00fcr das wiederkehrende Ziel eingeben.',true);return;}
    if(isOngoing)targetDate='';
    if(targetDate&&targetDate<startDate){showModalFeedback('nz-error',btn,'Enddatum darf nicht vor dem Beginn liegen.',true);return;}
  }else{
    startDate='';
    frequency='jaehrlich';
    isOngoing=false;
  }
  var mid=getActiveMandateId();
  if(btn){btn._origText=isEdit?'Aktualisieren':'Speichern';btn.disabled=true;btn.textContent=isEdit?'Aktualisieren...':'Speichern...';}
  var hardnessMap={'1':'Hart','2':'Prim\u00e4r','3':'Opportunistisch'};
  var familyMap={
    'Einmalige_Ausgabe':'Cashflow',
    'Wiederkehrende_Ausgabe':'Cashflow',
    'Pensionsausgabe':'Cashflow',
    'Kapitalerhalt':'Verm\u00f6gen',
    'Verm\u00f6gensziel':'Verm\u00f6gen',
    'Renditeziel':'Rendite',
    'Maximierung':'Maximierung'
  };
  var payload={
    goal_family:familyMap[type]||'Cashflow',
    goal_type:type,
    label:label,
    rank:parseInt(prio,10)||2,
    goal_scope:scope,
    value_mode:'nominal',
    target_amount_rappen:null,
    target_wealth_rappen:null,
    target_return_bps:null,
    start_date:startDate||null,
    horizon_years:horizon,
    target_date:targetDate||null,
    is_ongoing:isRecurringGoalType(type)?isOngoing:false,
    frequency:isRecurringGoalType(type)?frequency:null,
    hardness:hardnessMap[prio]||'Prim\u00e4r'
  };
  if(isReturnGoalType(type))payload.target_return_bps=parsePercentToBps(amountRaw);
  else if(isWealthGoalType(type))payload.target_wealth_rappen=parseCHF(amountRaw);
  else if(!isMaxGoalType(type))payload.target_amount_rappen=parseCHF(amountRaw);
  if(mid&&!isDemoMandateId(mid)){
    try{
      if(isEdit)await API.put('/mandates/'+mid+'/goals/'+currentGoalEditId,payload);
      else await API.post('/mandates/'+mid+'/goals',payload);
      showModalFeedback('nz-error',btn,isEdit?'\u2713 Ziel aktualisiert':'\u2713 Ziel gespeichert',false);
      currentGoalEditId=null;
      cm('m-nz');
      await refreshGoalsUI(mid);
      markStrategyDirty(isEdit?'Ziel aktualisiert: Strategie neu berechnen.':'Ziel gespeichert: Strategie neu berechnen.');
    }catch(e){
      showModalFeedback('nz-error',btn,'Fehler: '+(e.detail||e.message||'?'),true);
    }
  } else {
    var localId=isEdit?currentGoalEditId:('demo-goal-'+Date.now());
    var existing=(currentGoals||[]).find(function(goal){return String(goal.id||'')===String(localId);})||null;
    var localGoal=buildDemoGoalRecord(localId,payload,existing);
    currentGoals=(currentGoals||[]).filter(function(goal){return String(goal.id||'')!==String(localId);});
    currentGoals.push(localGoal);
    currentGoals.sort(function(a,b){return Number(a.rank||99)-Number(b.rank||99);});
    renderGoalList(currentGoals,true);
    showModalFeedback('nz-error',btn,'\u2713 Demo-Modus: Ziel aktualisiert',false);
    currentGoalEditId=null;
    setTimeout(function(){cm('m-nz');},600);
  }
}
async function refreshGoalsUI(mid){
  if(!mid||isDemoMandateId(mid)){
    renderGoalList(currentGoals,true);
    return;
  }
  try{
    var data=await API.get('/mandates/'+mid+'/goals');
    var items=Array.isArray(data)?data:(data.items||[]);
    currentGoals=items.slice();
    renderGoalList(currentGoals,false);
  }catch(e){
    console.warn('refreshGoalsUI:',e);
  }
}
var _cmGoalTiming=cm;
cm=function(id){
  if(id==='m-nz')currentGoalEditId=null;
  return _cmGoalTiming(id);
};
function dg(btn){
  var g=btn.closest('.goal'),gId=g?g.dataset.goalid:null;
  var mid=getActiveMandateId();
  var isDemo=isDemoClientId(gId)||isDemoMandateId(mid);
  if(!confirm(isDemo?'Ziel entfernen (Demo)?':'Ziel wirklich l\u00f6schen?'))return;
  if(!isDemo){
    if(!mid){console.error('dg DELETE skipped: no active mandate id');return;}
    API.del('/mandates/'+mid+'/goals/'+gId)
      .then(function(){
        currentGoals=(currentGoals||[]).filter(function(goal){return String(goal.id||'')!==String(gId||'');});
        refreshGoalsUI(mid);
        markStrategyDirty('Ziel gel\u00f6scht: Strategie neu berechnen.');
      })
      .catch(function(e){console.error('dg DELETE failed:',e.status,e.message);});
  } else {
    currentGoals=(currentGoals||[]).filter(function(goal){return String(goal.id||'')!==String(gId||'');});
    renderGoalList(currentGoals,true);
  }
}
function strategyGoalTargetText(goal){
  var type=goal&&goal.goal_type||'';
  if(isReturnGoalType(type)){
    return goal&&goal.target_return_bps!=null ? formatBpsPercent(goal.target_return_bps)+' p.a.' : 'Renditeziel';
  }
  if(isMaxGoalType(type))return 'Maximierung';
  if(isWealthGoalType(type)&&goal&&goal.target_wealth_rappen!=null){
    return formatRappen(goal.target_wealth_rappen);
  }
  return formatRappen(goal&&goal.target_amount_rappen||0);
}
var _renderStrategySummaryGoalTiming=renderStrategySummary;
renderStrategySummary=function(){
  _renderStrategySummaryGoalTiming();
  var allocation=strategyState.allocation;
  var goals=document.getElementById('sr-goal-priority-list');
  if(!goals||!allocation)return;
  goals.innerHTML=(allocation.goal_analysis||[]).slice(0,3).map(function(goal){
    var score=Number(goal.achievement_score||0);
    var tone=score>=70?'var(--pos)':(score>=45?'var(--warn)':'var(--neg)');
    var pathInfo=goal.path_success_rate_pct!=null?(' / Pfad '+String(goal.path_success_rate_pct)+'%'):'';
    var projectedInfo=goal.projected_value_p50_rappen!=null?(' / P50 '+formatRappen(goal.projected_value_p50_rappen)):'';
    return '<div style="display:flex;justify-content:space-between;align-items:flex-start;gap:12px;padding:8px;background:var(--bg);border-radius:var(--r);border:1px solid var(--b1)">'+
      '<div><div><span style="font-size:9px;font-weight:600;color:var(--n5);margin-right:6px">RANG '+escapeHtml(goal.rank)+'</span><span style="font-size:11px;color:var(--n8)">'+escapeHtml(goal.label||'Ziel')+'</span></div><div style="font-size:10px;color:var(--n6);margin-top:4px">'+escapeHtml(goalTimingLabel(goal)+pathInfo)+'</div></div>'+
      '<div style="text-align:right"><div style="font-size:10px;font-weight:600;color:var(--n7)">'+escapeHtml(strategyGoalTargetText(goal))+'</div><div style="font-size:10px;color:'+tone+';margin-top:4px">'+escapeHtml(String(score))+'%'+projectedInfo+'</div></div></div>';
  }).join('');
};
document.addEventListener('DOMContentLoaded',function(){
  syncGoalModalState();
});
