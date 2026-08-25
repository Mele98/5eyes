# 5eyes Reporting Sub-App — Design System

**Sprint U-46 (2026-06-04)** · Living-Documentation für Berater, Designer und Entwickler.

Diese Doku spiegelt den Stand von `tailwind.config.ts` + `src/styles/globals.css` wider. Sie ist Single-Source-of-Truth für Token-Namen, Werte und Verwendung. **Code ist die Wahrheit** — bei Drift zwischen Doku und Config muss diese Datei mit gerade angepasst werden.

---

## Designprinzipien

| Prinzip | Bedeutung |
|--------|-----------|
| **Swiss Private Banking** | Institutionell, präzise, leise. Kein Fintech-Look. |
| **Editorial** | Viel Weissraum. Typografie führt das Auge. |
| **Branding-Disziplin** | Keine Dritt-Marken (UBS, Swiss Life, 3eyes, etc.). Keine Verkaufsargumente. |
| **FINMA-bewusst** | Keine Garantieversprechen. Keine Emotionalisierung. |
| **Print-tauglich** | Jede Sektion muss als PDF identisch wirken. |

---

## Farb-Tokens

### Canvas (Hintergrund-Hierarchie)

| Token | Hex | Verwendung |
|-------|-----|-----------|
| `bg-canvas` (DEFAULT) | `#FAFAF6` | Body, Cover, Section-Background |
| `bg-canvas-subtle` | `#F4F3EE` | Erkenntnisse-Pill-Background, eingerückte Blocks |
| `bg-canvas-panel` | `#FFFFFF` | Cards, Charts auf Canvas |

**Regel:** Niemals pures `#FFF` als Body. Cover bleibt offwhite. Karten auf Canvas heben sich durch panel-Weiss leicht ab.

### Ink (Text-Hierarchie)

| Token | Hex | Verwendung |
|-------|-----|-----------|
| `text-ink` (DEFAULT) | `#0F1C2E` | Body-Text, Headlines, KPI-Zahlen |
| `text-ink-muted` | `#3B475A` | Sekundärtext, Sub-Labels |
| `text-ink-subtle` | `#6F7A8A` | Hilfs-Labels, Micro-Captions |

### Accent (Petrol/Teal)

| Token | Hex | Verwendung |
|-------|-----|-----------|
| `text-accent` / `border-accent` | `#2C5F5F` | Sektion-Kicker, KPI-Pull-Border, Active-Sidebar |
| `bg-accent-subtle` | `#7FA5A5` | Hover-Backgrounds |

### Rule (Trennlinien)

| Token | Hex | Verwendung |
|-------|-----|-----------|
| `border-rule` | `#E5E4DE` | Standard-Trennlinien |
| `border-rule-strong` | `#C8C6BD` | Hover-Borders, Strong-Separators |

### Status / Ampel

| Token | Hex | Verwendung |
|-------|-----|-----------|
| `text-status-gruen` | `#4E6F58` | Status-Pill GREEN (matt, nicht signal) |
| `text-status-gelb` | `#B59243` | Status-Pill YELLOW |
| `text-status-rot` | `#9E4747` | Status-Pill RED |
| `text-status-neutral` | `#7A8395` | Status-Pill "nicht beurteilbar" |

**WICHTIG:** Niemals knallige Signal-Farben (`#FF0000`, `#00FF00`). Matte Töne respektieren das Editorial.

### Gold (sehr sparsam)

| Token | Hex | Verwendung |
|-------|-----|-----------|
| `text-gold` | `#B39455` | Verdict-GREEN-Pill, Highlights |
| `text-gold-subtle` | `#D9C79A` | Backgrounds wenn gold benötigt |

**Regel:** Max 1 Gold-Akzent pro Sektion. Mehr als 2 Gold-Element pro Seite verletzt das Editorial.

---

## Typografie-Tokens

### Schrift-Familien

| Token | Stack | Verwendung |
|-------|-------|-----------|
| `font-serif` | Cormorant Garamond → Source Serif Pro → Georgia | Headlines, Display, H1-H3 |
| `font-sans` | Inter → Source Sans Pro → System | Body, UI, Forms |
| `font-mono` | JetBrains Mono → Consolas | Tabular-Numbers (CHF, %, BPs) |

**U-15 (PR #138):** TTF-Embedding von Cormorant Garamond + Inter in ReportLab + Sub-App.

### Schriftgrößen-Hierarchie

| Token | Größe | Line-Height | Verwendung |
|-------|-------|-------------|------------|
| `text-display` | 3.5rem | 1.05 | Cover-Titel, KPI-Mega-Zahl |
| `text-h1` | 2.25rem | 1.15 | Section-Headlines |
| `text-h2` | 1.5rem | 1.25 | Sub-Section-Headlines |
| `text-h3` | 1.125rem | 1.35 | Block-Titel, KPI-Captions |
| `text-body` | 0.9375rem | 1.55 | Body-Text (15px) |
| `text-caption` | 0.8125rem | 1.4 | Tabellen-Zellen, Sub-Labels (13px) |
| `text-micro` | 0.6875rem | 1.3 | Kicker, Uppercase-Labels (11px) |

**Regel:** Keine weiteren Schriftgrößen einführen ohne Spec-Update. Sieben Stufen reichen.

---

## Spacing-Tokens

| Token | Wert | Verwendung |
|-------|------|------------|
| `px-page-x` | 4rem | Horizontale Seitenränder |
| `py-page-y` | 5rem | Vertikale Seitenränder |
| `mt-section` / `space-y-section` | 4rem | Zwischen Sektionen |
| `mt-block` / `space-y-block` | 2rem | Zwischen Content-Blocks |

**Editorial-Prinzip:** Lieber zu viel Whitespace als zu wenig. Crowded > Sparsam ist verboten.

---

## Layout-Tokens

| Token | Wert | Verwendung |
|-------|------|------------|
| `max-w-editorial` | 64rem | Hauptcontent-Breite (Print-äquivalent) |
| `lg:grid-cols-[17rem_minmax(0,1fr)]` | — | Sidebar(17rem) + Content (Sub-App) |

---

## Component-Klassen (`globals.css`)

### `.section-title`
`font-serif text-h2 text-ink mt-section mb-block` — Standard-Sektion-Header.

### `.status-pill` (+ Modifier)
- `.status-pill-gruen` — Status erreicht / OK
- `.status-pill-gelb` — Warnung / Knapp
- `.status-pill-rot` — Kritisch
- `.status-pill-neutral` — Daten ausstehend / nicht beurteilbar

Beispiel:
```tsx
<span className="status-pill status-pill-gruen">Erreichbar</span>
```

---

## Print-Disziplin (`@media print`)

| Regel | Effekt |
|-------|--------|
| `body { @apply bg-white }` | Pures Weiss im Druck (Tinten-Schonung) |
| `.no-print { display: none !important }` | UI-Only-Elemente verstecken |
| Sprint U-52: Animation-Kill | `animation-duration: 0s` + `[data-testid] { opacity:1, transform:none }` |
| Sprint U-47: A4-Layout | `@page { size: A4; margin: 20mm }` |

**Pflicht:** Jeder Interactive-UI-Bestandteil (Buttons, Tabs, Drawer, Search-Bar) braucht `.no-print` Klasse.

---

## A11y-Tokens

| Pattern | Verwendung |
|---------|-----------|
| `aria-sort` | U-48: Goals-Table-Headers (`ascending`/`descending`/`none`) |
| `data-testid` | E2E-Anker, niemals Style-relevant |
| `prefers-reduced-motion: reduce` | U-52: Animation-Kill für a11y-User |
| `kbd` mit `border-rule` | U-51: Tastatur-Shortcuts-Help-Overlay |

---

## Verwendungs-Patterns

### Editorial Section-Header
```tsx
<section>
  <p className="text-micro uppercase tracking-widest text-accent">
    Sektion 11
  </p>
  <h1 className="mt-block font-serif text-h1 text-ink">
    Zielbasierte Optimierung
  </h1>
  <p className="mt-2 text-body text-ink-muted">
    Untertitel mit Erklärung.
  </p>
</section>
```

### KPI-Box (z.B. Achievement-Score)
```tsx
<section className="border-l-4 border-accent bg-canvas-subtle px-6 py-5">
  <p className="text-micro uppercase tracking-widest text-ink-subtle">
    Gewichteter Zielerreichungs-Score
  </p>
  <p className="mt-2 font-serif text-display text-ink">85 %</p>
</section>
```

### Tabular-Numbers (CHF / %)
```tsx
<span className="font-mono text-body text-ink">CHF 1'234'567.00</span>
```

---

## Branding-Verbote

| Verbot | Grund |
|--------|-------|
| 3rd-Party-Marken in Texten/PDF | Branding-Disziplin |
| Knallige Signal-Farben (`#FF0000`, `#00FF00`) | Editorial-Stil |
| Comic-/Sans-Serif-Marketing-Fonts | Institutional-Look |
| Stock-Bilder, Menschen, Skyline | Cover-Spec |
| Verkaufsargumente ("besser als…") | FINMA-bewusst |
| Garantieversprechen | FINMA-Pflicht |
| Emojis im Code/PDF | Editorial |

---

## Update-Workflow

Bei Token-Änderung (z.B. neue Farbe, neuer Spacing-Wert):

1. **Spec-Diskussion** mit Berater + UX-Spec dokumentieren
2. **Token in `tailwind.config.ts`** ergänzen
3. **Diese Doku** mit gleichen Sprint-Stempel aktualisieren
4. **Snapshot-Tests** in `src/pages/sections.test.tsx` ggf. anpassen
5. **PDF-Bytes-Smoke** für Server-PDF verifizieren

---

## Verwandte Specs

- `5eyes-electron/frontend/reporting/src/styles/globals.css` — Component-Klassen + Print-CSS
- `5eyes-electron/frontend/reporting/tailwind.config.ts` — Token-Definitionen
- `5eyes-backend/services/pdf/fonts.py` (U-15) — Server-PDF TTF-Registration
- Memory `feedback_5eyes_branding.md` — Branding-Disziplin

---

## Sprint-Audit-Trail

| Sprint | Effekt |
|--------|--------|
| U-FE-1 bis U-FE-5 (2026-05-27) | Editorial Sub-App-Bausteine |
| U-47 (PR #119, 2026-06-01) | Print-CSS A4 + Audit-Tests |
| U-52 (PR #130, 2026-06-01) | Cover-Animation print-aware + reduced-motion |
| U-14 (PR #113, 2026-05-31) | recharts entfernt (SVG-Vanilla genügt) |
| U-15 (PR #138, 2026-06-02) | TTF-Embedding (Cormorant + Inter) |
| U-48 (PR #145, 2026-06-04) | Goals-Tabelle sortierbar |
| U-49 (PR #146, 2026-06-04) | Positionen Such-Filter |
| U-51 (PR #147, 2026-06-04) | Tastatur-Shortcuts j/k/g/G/?/Esc |
| **U-46 (this PR)** | **Design-System-Doku** |

---

*Diese Doku ist niemals fertig. Wenn ein Token sich ändert ohne dass diese Datei mitgeht: das nächste Token bekommt deinen Namen.*
