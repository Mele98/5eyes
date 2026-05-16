# Spec — Portfolio Phase 1: Nur ETFs & Fonds

## Meta
- Titel: Portfolio Phase 1 — Produkttyp-Kennzeichnung, nur ETFs & Fonds
- Datum: 2026-04-16
- Owner: Emanuele
- Branch-Vorschlag: `codex/portfolio-etf-phase1`
- Referenz-Bild: `C:\Users\Emanuele\Desktop\Consulting Firma\Advisory-Methodik\Optimierungen\Advisory-Methodik\Portfolioübersicht.jpg`

---

## Warum diese Spec existiert — Fachlicher Kontext

5eyes ist in Phase 1 bewusst schlank gehalten. Das System empfiehlt Anlageklassen-Allokationen,
der Berater ordnet dann konkrete Produkte zu.

**In Phase 1 gilt:** Nur ETFs und Fonds (kollektive Kapitalanlagen). Keine Einzeltitel
(Einzelaktien, Einzelobligationen). Gründe:
- Vereinfacht Compliance (keine Eignungsprüfung pro Einzeltitel nötig)
- ETF/Fonds bieten bereits Diversifikation auf Anlageklassen-Ebene
- Passend zur Beratungsphilosophie (holistische Allokation, nicht Titelselektion)
- Reduziert System-Komplexität massiv in Phase 1

**Phase 2 (zukünftig):** Das Feld `product_type` ist von Beginn an in der DB. Phase 2 aktiviert
Einzeltitel durch ein Admin-Setting — keine Migration nötig.

**Wichtiger Hinweis:** Das `Product`-Modell (`models/review.py`) hat BEREITS ein `product_type`-Feld!
Es ist `Column(String, nullable=False)`. Das bedeutet:
- Keine neue DB-Spalte nötig
- Nur UI-Änderungen nötig
- In der bestehenden Admin-Oberfläche müssen die erlaubten `product_type`-Werte klar definiert werden

---

## Scope

### Was sich ändert
1. `5eyes_v2.html` — Portfolio-Tab Header-Text ändern
2. `5eyes_v2.html` — Modal `m-ap`: bestehender Info-Text bleibt, **kein** "Phase 1"-Badge
3. `5eyes_v2.html` — Checkbox `aa-product-funds-only` auf `checked` by default

### Was NICHT ändert
- `models/review.py` → `product_type` existiert bereits, keine Änderung
- Die bestehende Portfolio-Logik, Drift-Berechnung, etc.
- Kein technischer Filter (Phase 1 ist Advisory, kein Hard-Block)

---

## Betroffene Dateien

| Datei | Art |
|---|---|
| `5eyes-electron/frontend/5eyes_v2.html` | ÄNDERN |

---

## Frontend — Schritt 1: Portfolio-Tab Header anpassen

### Grep:
```
grep -n "Portfolio.*Einzeltitel\|page-po.*ph-t" 5eyes-electron/frontend/5eyes_v2.html
```

### Alten Header suchen:
```
Portfolio &amp; Einzeltitel
```
**Ersetzen durch:**
```
Portfolio — ETFs &amp; Fonds
```

### Sub-Header: unverändert lassen
```
Produkt / Anlageklasse / Marktwert / Gewicht / Handlung
```
Kein "Phase 1"-Label im Sub-Header. Die Einschränkung auf ETFs/Fonds ist eine interne
Entscheidung, kein sichtbares UI-Element. Der Berater sieht einfach das saubere Portfolio-Tab.

---

## Frontend — Schritt 2: Modal `m-ap` — KEINE Änderung

Das Modal `m-ap` bleibt **exakt wie es ist**. Kein "Phase 1"-Badge, kein Hinweis.
Der Berater weiss intern, dass er ETFs/Fonds einträgt — das muss nicht im UI stehen.

---

## Frontend — Schritt 3: "Nur Fonds/ETFs" Checkbox in Allokations-Präferenzen

### Grep:
```
grep -n "aa-product-funds-only\|Nur Fonds" 5eyes-electron/frontend/5eyes_v2.html
```

Das Feld `aa-product-funds-only` existiert bereits in der Asset-Allocation-Seite.
Es soll in Phase 1 **standardmässig angehakt** sein (checked by default).

### Suche die entsprechende Checkbox:
```
id="aa-product-funds-only"
```

### Änderung: `checked` Attribut hinzufügen:
**Alt:**
```html
<input type="checkbox" id="aa-product-funds-only">
```
**Neu:**
```html
<input type="checkbox" id="aa-product-funds-only" checked>
```

**Hinweis:** Das ist ein Advisory-Default, kein Hard-Lock. Der Berater kann es abwählen.

---

## Implementierungs-Checkliste für Codex

1. Portfolio-Tab Header: "Portfolio & Einzeltitel" → "Portfolio — ETFs & Fonds"
2. Sub-Header: unverändert lassen
3. Modal `m-ap`: keine Änderung
4. Checkbox `aa-product-funds-only`: Default auf `checked` setzen
5. `node --check 5eyes-electron/frontend/5eyes_v2.html` → 0 Fehler

---

## Akzeptanzkriterien

1. Portfolio-Tab zeigt Header "Portfolio — ETFs & Fonds"
2. Modal `m-ap` bleibt unverändert — kein Phase-1-Label
3. In Asset Allocation → Präferenzen ist "Nur Fonds/ETFs" standardmässig aktiv
4. Kein Breaking Change an bestehender Portfolio-Logik
5. `node --check` → 0 Fehler

---

## Zukünftige Phase 2 (NICHT implementieren jetzt)

Wenn Einzeltitel gewünscht werden:
- `product_type` in `products`-Tabelle ist bereits vorhanden
- Admin-Setting `allow_single_titles = true` → Checkbox `aa-product-funds-only` wird nicht mehr gesetzt
- Produktsuche filtert dann nach `product_type IN ('ETF','Fonds')` nur wenn Setting aktiv
- Keine DB-Migration nötig
