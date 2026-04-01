# Claude Spec: Produkt-Marktprofil – persistenter Lookup-Override

## Meta

- Titel: Produkt-Marktprofil: persistenter Lookup-Override
- Datum: 2026-04-01
- Owner: Emanuele
- Issue / Link: —
- Branch-Vorschlag: `codex/product-market-override`

---

## Ziel

Jedes Produkt im Anlageuniversum soll einen persistenten `lookup_mode_override` und `lookup_symbol_override` in der Datenbank haben können. Wenn gesetzt, überschreiben diese Felder den automatisch abgeleiteten Lookup vollständig — unabhängig davon, ob ein Katalog-Eintrag oder ein `product.symbol` vorhanden ist. Advisors können über den Admin-Bereich pro Produkt steuern, ob es direkt, via Proxy oder synthetisch bewertet wird, ohne Python-Code anfassen zu müssen.

---

## Problem

`resolve_market_profile` in `services/product_market_data.py` kennt heute zwei Quellen:
1. `product.symbol` + `product.exchange_code` → immer Modus `"direct"`
2. `DEFAULT_PRODUCT_MARKET_CATALOG` (hardcodiertes Python-Dict, Key = `product_name`) → Proxy / synthetic_par

**Konkrete Lücken:**
- Neue Produkte, die nicht im Katalog stehen, landen immer auf `"direct"` oder `"unmapped"` — kein Proxy möglich ohne Code-Änderung.
- Der Katalog ist nach `product_name` indexiert: minimale Schreibweise-Abweichung = kein Match = kein Lookup.
- `overwrite_symbol` in `/products/openfigi/auto-apply` und `/products/eodhd/auto-apply` schreibt nur `product.symbol` — es gibt keine Möglichkeit, `lookup_mode = "proxy"` dauerhaft für ein Produkt zu persistieren.
- Das Frontend-Admin-Panel hat `admin-overwrite-symbol`-Checkbox und die Flag wird bereits übergeben (HTML Zeile 3715), aber das Backend bietet keinen Endpunkt, der `lookup_mode` und einen vom Symbol unabhängigen Override-Lookup speichert.

---

## Scope

- `Product`-Modell: zwei neue Felder `lookup_mode_override TEXT` und `lookup_symbol_override TEXT`
- `database.py` `ensure_runtime_columns()`: beide Felder in Tabelle `products`
- `services/product_market_data.py` `resolve_market_profile()`: Override-Zweig vor Katalog und `product.symbol`-Zweig
- `routers/review.py`: neuer Endpunkt `PUT /products/{product_id}/market-override` (Admin required)
- `routers/review.py`: `_collect_product_market_data_status()` — `lookup_mode_override_count` ergänzen
- Frontend-Admin: Inline-Formular pro Produkt (lookup_mode Dropdown + lookup_symbol Textfeld + Save)
- Unit-Tests für `resolve_market_profile` mit allen Override-Kombinationen

## Nicht-Scope

- Keine Änderung an `DEFAULT_PRODUCT_MARKET_CATALOG` (bleibt Fallback)
- Kein neues OpenFIGI- oder EODHD-Mapping (separate Features)
- Kein `lookup_symbols`-Dict per Provider im Override (einheitliches Symbol, Exchange-Suffix via bestehende `provider_lookup_symbol`-Logik)
- Kein Datenbank-Migrationsskript (bestehender `ensure_runtime_columns()`-Mechanismus reicht)

---

## Fachlogik

- **Quelle:** Code-Analyse `services/product_market_data.py`, `routers/review.py`, HANDOFF-Frage zu `ticker_symbol`-Override
- **Verbindliche Regeln:**
  1. Wenn `product.lookup_mode_override` nicht leer → dieser Modus gilt, Katalog und `product.symbol`-Zweig werden übersprungen
  2. Wenn `product.lookup_symbol_override` nicht leer → dieses Symbol gilt als `lookup_symbol`
  3. Gültige Werte für `lookup_mode_override`: `"direct"`, `"proxy"`, `"synthetic_par"`
  4. `lookup_mode_override = "synthetic_par"` → `lookup_symbol_override` wird ignoriert; `synthetic_price_rappen = 100` (konsistent mit Katalog)
  5. Beide Felder können unabhängig gesetzt sein: nur `lookup_mode_override` ohne Symbol → Modus wird erzwungen, Symbol-Ableitung wie bisher; nur `lookup_symbol_override` ohne Modus → Symbol wird überschrieben, Modus bleibt abgeleitet
  6. Override hat Vorrang vor Katalog und vor `product.symbol`-Lookup
  7. `provider_lookup_symbol`-Logik (Exchange-Suffix) wird auf `lookup_symbol_override` angewendet, sofern das Symbol keinen expliziten Suffix hat (`.`, `:`, `/`)
- **Inferenz:**
  - `build_live_rebalancing_payload`, `price_updater.fetch_latest_price` und `_collect_product_market_data_status` rufen alle `resolve_market_profile` auf — sie profitieren automatisch vom Override ohne Änderung
- **Owner-Decisions:**
  - OWNER-DECISION: Soll `lookup_symbol_override` den Exchange-Suffix auto-ergänzen? Empfehlung: Ja (bestehende Logik), wenn Symbol keinen Punkt/Doppelpunkt enthält.
  - OWNER-DECISION: Soll `GET /products/{id}` den Override für Berater (non-admin) zurückgeben? Empfehlung: Ja, readonly.
  - OWNER-DECISION: `lookup_mode_override_count` im Status-Dashboard? Empfehlung: Ja.

---

## Betroffene Module / Dateien

- **Backend:**
  - `5eyes-backend/models/review.py` — `Product`-Klasse: zwei neue `Column(String)`: `lookup_mode_override`, `lookup_symbol_override`
  - `5eyes-backend/database.py` — `ensure_runtime_columns()`: beide Felder in Block `'products': [...]` ergänzen (wie `figi`, `composite_figi` — Zeile 171–174)
  - `5eyes-backend/services/product_market_data.py` — `resolve_market_profile()` (Zeile 324): Override-Zweig als erstes `if` vor dem bestehenden `if raw_symbol or raw_isin:` Block
  - `5eyes-backend/schemas/review.py` — `ProductResponse` (Zeile 169): zwei neue optionale Felder `lookup_mode_override: Optional[str] = None`, `lookup_symbol_override: Optional[str] = None`; neue Klassen `ProductMarketOverrideRequest` und `ProductMarketOverrideResponse`
  - `5eyes-backend/routers/review.py` — neuer Endpunkt `PUT /products/{product_id}/market-override` (Admin required, analog zu bestehenden `products_router`-Endpunkten); `_collect_product_market_data_status()` (Zeile 117): `lookup_mode_override_count` ergänzen
- **Frontend:**
  - `5eyes-electron/frontend/5eyes_v2.html` — Admin-Modal Sektion "Marktdaten & Produktstamm" (HTML um Zeile 7684): neuen Sub-Bereich nach dem bestehenden Button-Grid (Zeile 7699–7705) einfügen; neue JS-Funktion `adminSetProductOverride()` analog zu `adminRunOpenfigiAutoApply()`; Feedback via bestehendem `showAdminResult()`
- **Datenmodell:**
  - Neue Spalten `products.lookup_mode_override TEXT` und `products.lookup_symbol_override TEXT` via `ensure_runtime_columns()`
- **Tests:**
  - `5eyes-backend/tests/test_product_market_data.py` (neu erstellen oder erweitern)

---

## API / Schnittstellen

### Neuer Endpunkt: `PUT /products/{product_id}/market-override`

```
Authorization: Bearer <admin-token>
Content-Type: application/json

Request Body:
{
  "lookup_mode_override": "proxy" | "direct" | "synthetic_par" | null,
  "lookup_symbol_override": "GLD" | null
}

Response 200:
{
  "id": "<product_id>",
  "product_name": "ZKB Gold ETF",
  "lookup_mode_override": "proxy",
  "lookup_symbol_override": "GLD",
  "resolved_market_profile": {
    "lookup_mode": "proxy",
    "lookup_symbol": "GLD",
    "pricing_note": "...",
    ...
  }
}

Response 404: Produkt nicht gefunden oder gelöscht
Response 422: lookup_mode_override hat ungültigen Wert (nicht in {direct, proxy, synthetic_par, null})
Response 403: Nicht-Admin
```

**Löschen des Override:** beide Felder als `null` übergeben → Felder werden auf `NULL` gesetzt, `resolve_market_profile` fällt auf alten Pfad zurück.

### Geänderter Endpunkt: `GET /products/market-data/status`

Neues Feld in der Antwort:
```json
"lookup_mode_override_count": 3
```

---

## UI / UX

### Admin-Modal — Einbaupunkt

Das Override-Formular kommt als neuer `<div>` **nach** dem bestehenden Button-Grid `<div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;">` (HTML ~Zeile 7698) und **vor** dem `<div id="admin-result" ...>` (Zeile 7707), innerhalb der "Marktdaten & Produktstamm"-Sektion.

**Neues HTML-Fragment (nach dem Button-Grid einfügen):**
```html
<div style="border-top:1px solid var(--b1);padding-top:10px;display:grid;gap:8px;">
  <div style="font-size:9px;text-transform:uppercase;letter-spacing:0.07em;color:var(--n4)">Produkt Lookup-Override</div>
  <div style="display:grid;grid-template-columns:1fr 1fr 120px;gap:8px;align-items:end;">
    <div>
      <label style="font-size:9px;color:var(--n4);display:block;margin-bottom:2px">Produkt-ID oder Name</label>
      <input class="fi" id="admin-override-product" placeholder="Produkt-ID oder exakter Name" style="font-size:11px">
    </div>
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:6px;">
      <div>
        <label style="font-size:9px;color:var(--n4);display:block;margin-bottom:2px">Modus</label>
        <select class="fsel" id="admin-override-mode" style="font-size:11px">
          <option value="">— Standard</option>
          <option value="direct">direct</option>
          <option value="proxy">proxy</option>
          <option value="synthetic_par">synthetic_par</option>
        </select>
      </div>
      <div>
        <label style="font-size:9px;color:var(--n4);display:block;margin-bottom:2px">Symbol</label>
        <input class="fi" id="admin-override-symbol" placeholder="z.B. GLD" style="font-size:11px">
      </div>
    </div>
    <button class="btn-p" style="background:var(--bg2);color:var(--n6)" onclick="adminSetProductOverride()" id="btn-admin-override-save">Override speichern</button>
  </div>
  <div id="admin-override-error" style="display:none;color:var(--neg);font-size:10px"></div>
</div>
```

**Neue JS-Funktion `adminSetProductOverride()` (analog zu `adminRunOpenfigiAutoApply`):**

```javascript
async function adminSetProductOverride() {
  var btn = document.getElementById('btn-admin-override-save');
  var errEl = document.getElementById('admin-override-error');
  var productRef = (document.getElementById('admin-override-product') || {}).value || '';
  var mode = (document.getElementById('admin-override-mode') || {}).value || '';
  var symbol = ((document.getElementById('admin-override-symbol') || {}).value || '').trim();
  if (errEl) errEl.style.display = 'none';
  if (!productRef.trim()) {
    if (errEl) { errEl.textContent = 'Produkt-ID oder Name ist Pflicht.'; errEl.style.display = 'block'; }
    return;
  }
  if (btn) { btn.disabled = true; btn.textContent = 'Speichert…'; }
  try {
    // Produkt-ID ermitteln: zuerst direkte ID versuchen, sonst nach Name suchen
    var products = await API.get('/products');
    var match = products.find(function(p) {
      return p.id === productRef.trim() || p.product_name === productRef.trim();
    });
    if (!match) {
      if (errEl) { errEl.textContent = 'Produkt nicht gefunden: ' + productRef; errEl.style.display = 'block'; }
      return;
    }
    var payload = await API.put('/products/' + match.id + '/market-override', {
      lookup_mode_override: mode || null,
      lookup_symbol_override: symbol || null
    });
    showAdminResult(
      'Override gesetzt: ' + match.product_name + '\n' +
      'Modus: ' + (payload.lookup_mode_override || '— Standard') + '\n' +
      'Symbol: ' + (payload.lookup_symbol_override || '— Standard') + '\n' +
      'Effektiv: ' + JSON.stringify(payload.resolved_market_profile, null, 2),
      false
    );
    await adminRefreshMarketStatus(false);
  } catch(e) {
    var msg = parseApiError(e, 'Override fehlgeschlagen.');
    if (errEl) { errEl.textContent = '✗ ' + msg; errEl.style.display = 'block'; }
    showAdminResult('✗ ' + msg, true);
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = 'Override speichern'; }
  }
}
```

### Demo-/Offline-Verhalten

- Admin-Panel ist nur im Live-Modus zugänglich (bestehender Guard bleibt unverändert)
- Im Demo-Modus ist das Modal nicht erreichbar — kein zusätzlicher Guard nötig

### Fehlerzustände

- Produkt nicht gefunden (client-seitig): "Produkt nicht gefunden: <ID>"
- 422 vom Backend: "Ungültiger Lookup-Modus"
- 404 vom Backend: "Produkt nicht gefunden"
- 403: "Keine Admin-Berechtigung"
- Netzwerkfehler: via `parseApiError()` (bestehende Hilfsfunktion)

---

## Akzeptanzkriterien

1. `resolve_market_profile` gibt bei `lookup_mode_override = "proxy"` und `lookup_symbol_override = "GLD"` exakt `{lookup_mode: "proxy", lookup_symbol: "GLD"}` zurück — unabhängig von `product.symbol`, `product.exchange_code` und Katalog.
2. `PUT /products/{id}/market-override` persistiert die Felder in der DB und gibt das aktualisierte `resolved_market_profile` zurück.
3. `PUT /products/{id}/market-override` mit `{lookup_mode_override: null, lookup_symbol_override: null}` setzt beide Felder auf `NULL`; danach verhält sich `resolve_market_profile` identisch zum Stand vor dem Feature.
4. `lookup_mode_override = "synthetic_par"` ohne Symbol → `{lookup_mode: "synthetic_par", synthetic_price_rappen: 100}`.
5. `GET /products/market-data/status` enthält `lookup_mode_override_count`.
6. Admin-Panel zeigt Inline-Formular, speichert Override, zeigt Badge, löscht Override korrekt.
7. Nicht-Admin erhält 403 auf `PUT /products/{id}/market-override`.

---

## Testfälle

**Unit (`resolve_market_profile` in `test_product_market_data.py`):**

```python
# Produkt-Stub: Objekt mit Attributen (kein DB nötig)
class P:
    def __init__(self, **kw):
        for k, v in kw.items(): setattr(self, k, v)

# 1. Override gewinnt gegen Katalog
p = P(product_name="ZKB Gold ETF", symbol=None, isin=None, exchange_code=None,
      lookup_mode_override="proxy", lookup_symbol_override="GLD")
profile = resolve_market_profile(p)
assert profile["lookup_mode"] == "proxy"
assert profile["lookup_symbol"] == "GLD"

# 2. Override gewinnt gegen product.symbol
p = P(product_name="X", symbol="NESN", isin=None, exchange_code="SW",
      lookup_mode_override="proxy", lookup_symbol_override="EWL")
assert resolve_market_profile(p)["lookup_symbol"] == "EWL"

# 3. synthetic_par ohne Symbol
p = P(product_name="X", symbol=None, isin=None, exchange_code=None,
      lookup_mode_override="synthetic_par", lookup_symbol_override=None)
profile = resolve_market_profile(p)
assert profile["lookup_mode"] == "synthetic_par"
assert profile["synthetic_price_rappen"] == 100

# 4. Nur Symbol-Override (kein Modus-Override)
p = P(product_name="X", symbol=None, isin=None, exchange_code=None,
      lookup_mode_override=None, lookup_symbol_override="GLD")
profile = resolve_market_profile(p)
assert profile["lookup_symbol"] == "GLD"

# 5. Kein Override → verhält sich wie heute
p = P(product_name="ZKB Gold ETF", symbol=None, isin=None, exchange_code=None,
      lookup_mode_override=None, lookup_symbol_override=None)
profile = resolve_market_profile(p)
assert profile["lookup_mode"] == "proxy"        # aus Katalog
assert profile["lookup_symbol"] == "GLD"        # aus Katalog
```

**API:**
- `PUT /products/{id}/market-override` valid → 200 + `resolved_market_profile`
- `PUT /products/{id}/market-override` mit `lookup_mode_override = "invalid"` → 422
- `PUT /products/{id}/market-override` unbekannte ID → 404
- `PUT /products/{id}/market-override` Berater-Token → 403
- `PUT /products/{id}/market-override` mit `{null, null}` → 200, danach `GET` zeigt alten Profil

**GUI / E2E:**
- Admin öffnet Produktliste, setzt Override, speichert → Badge erscheint
- Seite reload: Override ist persistiert
- Override löschen → Badge verschwindet

**Edge Cases:**
- `lookup_symbol_override = "NESN"` + `exchange_code = "SW"` → `provider_lookup_symbol` gibt "NESN.SW" für yfinance
- `lookup_symbol_override = "NESN.SW"` (hat Punkt) → kein weiterer Suffix
- Produkt hat Katalog-Eintrag UND Override → Override gewinnt
- Produkt hat `product.symbol = "CSSPX"` UND `lookup_symbol_override = "EWL"` → "EWL" gewinnt

---

## Risiken

- `ensure_runtime_columns()` läuft bei jedem App-Start — neue Spalten werden sauber ergänzt, keine bestehenden Daten verloren.
- `resolve_market_profile` wird in `build_live_rebalancing_payload` (Simulation), `price_updater.fetch_latest_price` und `_collect_product_market_data_status` aufgerufen — alle drei profitieren automatisch ohne weitere Code-Änderung.
- Frontend Inline-Edit: Loading-Guard nötig, damit `Override speichern` nicht doppelt feuert.
- `DEFAULT_PRODUCT_MARKET_CATALOG`-Einträge bleiben als Fallback erhalten — kein Regressions-Risiko für bestehende Produkte.

---

## Offene Fragen an Owner

1. **OWNER-DECISION:** Soll `lookup_symbol_override` den Exchange-Suffix auto-ergänzen, wenn kein Punkt/Doppelpunkt enthalten? Empfehlung: Ja.
2. **OWNER-DECISION:** Soll `GET /products/{id}` für Nicht-Admin-Berater `lookup_mode_override` und `lookup_symbol_override` zurückgeben (readonly)? Empfehlung: Ja (bereits in `ProductResponse` — kein neuer Endpunkt nötig).
3. **OWNER-DECISION:** Darf `lookup_mode_override = "proxy"` ohne `lookup_symbol_override` gesetzt werden? Empfehlung: Erlaubt — Pricing bleibt `unmapped`, kein 422.

---

## Nebenbefund (Blocker, ausserhalb dieses Features)

**`formatAdminMarketSummary` ist doppelt definiert** in `5eyes_v2.html` (Zeilen 3770 und 3842). Die zweite Definition überschreibt die erste — eine der beiden ist tot und sollte entfernt werden. Dies ist ein pre-existing Bug, kein Teil dieser Spec, aber Codex soll ihn **nicht stillschweigend entfernen** — das ist eine OWNER-DECISION welche Variante korrekt ist.

---

## Neue Klassen in `schemas/review.py`

```python
class ProductMarketOverrideRequest(BaseModel):
    lookup_mode_override: Optional[Literal["direct", "proxy", "synthetic_par"]] = None
    lookup_symbol_override: Optional[str] = None

class ProductMarketOverrideResponse(BaseModel):
    id: str
    product_name: str
    lookup_mode_override: Optional[str]
    lookup_symbol_override: Optional[str]
    resolved_market_profile: dict
```

## Neuer Endpunkt in `routers/review.py`

```python
@products_router.put("/{product_id}/market-override", response_model=ProductMarketOverrideResponse)
def set_product_market_override(
    product_id: str,
    body: ProductMarketOverrideRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    product = db.query(Product).filter(
        Product.id == product_id,
        Product.deleted_at.is_(None),
    ).first()
    if not product:
        raise HTTPException(status_code=404, detail="Produkt nicht gefunden")
    product.lookup_mode_override = body.lookup_mode_override or None
    product.lookup_symbol_override = body.lookup_symbol_override.strip() if body.lookup_symbol_override else None
    product.updated_at = _now()  # bestehende _now()-Hilfsfunktion verwenden
    db.commit()
    db.refresh(product)
    return ProductMarketOverrideResponse(
        id=product.id,
        product_name=product.product_name,
        lookup_mode_override=product.lookup_mode_override,
        lookup_symbol_override=product.lookup_symbol_override,
        resolved_market_profile=resolve_market_profile(product),
    )
```

## Override-Logik in `services/product_market_data.py`

`resolve_market_profile` (Zeile 324) erhält einen neuen ersten Block:

```python
def resolve_market_profile(product: Any) -> dict[str, Any]:
    product_name = str(getattr(product, "product_name", "") or "").strip()
    raw_symbol = str(getattr(product, "symbol", "") or "").strip() or None
    raw_isin = str(getattr(product, "isin", "") or "").strip() or None
    raw_currency = str(getattr(product, "currency", "") or "").strip() or None
    raw_exchange_code = normalize_exchange_code(getattr(product, "exchange_code", None))

    # ── Persistenter Override (höchste Priorität) ──────────────────────────────
    mode_override = str(getattr(product, "lookup_mode_override", "") or "").strip() or None
    symbol_override = str(getattr(product, "lookup_symbol_override", "") or "").strip() or None

    if mode_override or symbol_override:
        if mode_override == "synthetic_par":
            return {
                "product_name": product_name,
                "symbol": symbol_override or raw_symbol,
                "isin": raw_isin,
                "currency": raw_currency,
                "exchange_code": raw_exchange_code,
                "lookup_mode": "synthetic_par",
                "lookup_symbol": None,
                "lookup_symbols": {},
                "synthetic_price_rappen": 100,
                "identifier_basis": "override",
                "pricing_note": "Synthetischer Par-Wert (manueller Override).",
            }
        effective_symbol = symbol_override or raw_symbol
        effective_mode = mode_override or ("direct" if effective_symbol else "unmapped")
        lookup_symbols = {
            "yfinance": provider_lookup_symbol(effective_symbol, raw_exchange_code, "yfinance") if effective_symbol else None,
            "stooq": provider_lookup_symbol(effective_symbol, raw_exchange_code, "stooq") if effective_symbol else None,
            "twelvedata": provider_lookup_symbol(effective_symbol, raw_exchange_code, "twelvedata") if effective_symbol else None,
        }
        return {
            "product_name": product_name,
            "symbol": effective_symbol,
            "isin": raw_isin,
            "currency": raw_currency,
            "exchange_code": raw_exchange_code,
            "lookup_mode": effective_mode,
            "lookup_symbol": effective_symbol,
            "lookup_symbols": lookup_symbols,
            "synthetic_price_rappen": None,
            "identifier_basis": "override",
            "pricing_note": f"Manueller Override: Modus={effective_mode}, Symbol={effective_symbol or '—'}",
        }
    # ── bestehende Logik (unverändert) ─────────────────────────────────────────
    catalog = default_market_entry(product_name)
    # ... (Rest unverändert)
```
