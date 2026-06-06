# Service-Worker / Offline-Mode (Sub-App)

Foundation-Doku fuer einen Service-Worker in der Reporting Sub-App,
um Offline-Anzeige eines bereits geladenen Beratungsreports zu
ermoeglichen.

**Stand:** 2026-06-06
**Roadmap-Punkt:** #88 (FE, ~4h Foundation, eigentliche Implementierung
ist Folge-Sprint)
**Komplementaer zu:** [DESIGN_SYSTEM.md](../5eyes-electron/frontend/reporting/DESIGN_SYSTEM.md)

---

## Anwendungsfall

Berater zeigt dem Kunden waehrend des Beratungsgesprachs einen
Beratungsreport. Internet faellt aus (Hotel-WiFi, Firmen-Netz-Stress).
Mit Service-Worker bleibt der bereits geladene Report sichtbar +
navigierbar.

**Berater-relevant:** das ist ein Use-Case fuer Mobile-Beratung oder
Bank-Filiale ohne stabiles WLAN. Nicht fuer Hauptapp (Electron hat
Internet immer im LAN zum Backend).

## Architektur-Entscheidung

Sub-App ist Vite/React. Vite hat `vite-plugin-pwa` als Standard-
Workflow fuer Service-Worker. Strategie:

- **Cache-Strategy Network-First mit Cache-Fallback** fuer die
  Aggregator-API (`GET /mandates/{id}/advisory-report`)
- **Cache-Strategy Cache-First** fuer statische Sub-App-Assets
  (CSS, JS, Fonts)
- **TTL** 1 Stunde fuer Aggregator-Cache (Berater-Sitzung-Dauer)

## Foundation in U-88

Heute legen wir die **Foundation** fest, ohne den Service-Worker
selbst zu registrieren (das wuerde gepackte Electron-App brechen
ohne Test-Pattern).

### Vite-Plugin (opt-in, NICHT in package.json heute)

```powershell
cd 5eyes-electron\frontend\reporting
npm install vite-plugin-pwa --save-dev
```

### vite.config.ts Extension (Konzept)

```ts
import { VitePWA } from 'vite-plugin-pwa';

export default defineConfig({
  plugins: [
    react(),
    VitePWA({
      registerType: 'autoUpdate',
      strategies: 'generateSW',
      workbox: {
        runtimeCaching: [
          {
            urlPattern: /\/mandates\/.*\/advisory-report/,
            handler: 'NetworkFirst',
            options: {
              cacheName: 'advisory-report-cache',
              expiration: { maxEntries: 50, maxAgeSeconds: 3600 },
            },
          },
        ],
      },
    }),
  ],
});
```

### Sub-App-Status-Indicator (Konzept)

```tsx
function OfflineStatus() {
  const [online, setOnline] = useState(navigator.onLine);
  useEffect(() => {
    window.addEventListener('online', () => setOnline(true));
    window.addEventListener('offline', () => setOnline(false));
  }, []);
  if (online) return null;
  return (
    <div role="status" aria-live="polite" className="...">
      Offline — Sie sehen den zuletzt geladenen Bericht.
    </div>
  );
}
```

## Sicherheits-Aspekte

- **Bearer-Token nicht im Service-Worker-Cache** — Token bleibt
  in `sessionStorage`, der Service-Worker cacht nur die Response
  (die enthaelt KEINE Auth-Daten)
- **Cache-Invalidation bei Logout** — bei `consumeHandoffFromUrlFragment`
  muss `caches.delete('advisory-report-cache')` aufgerufen werden
- **Kein Cross-Origin-Caching** — nur eigene Backend-Responses

## Bewusst NICHT in Scope (U-88)

- `vite-plugin-pwa` als Dev-Dependency (KEIN package.json-Eintrag)
- Service-Worker-Registration in `main.tsx` (Electron-Test-Pattern
  fehlt)
- Cache-Invalidation-Hook im Token-Handoff
- Background-Sync fuer Beratungsprotokoll-Drafts (Folge-Sprint)
- Push-Notifications (ADR-003: kein Markt-Timing-Alarm)

## Folge-Sprints

1. **Echtes Wiring** sobald Electron-Test-Pattern fuer SW existiert
2. **Cache-Invalidation-Hook** in `consumeHandoffFromUrlFragment`
3. **Background-Sync** fuer NotesDrawer-Drafts (siehe U-23/U-24)
4. **Offline-Indicator-UI** in Sidebar

## Weiterfuehrendes

- [vite-plugin-pwa docs](https://vite-pwa-org.netlify.app)
- [MDN Service Worker API](https://developer.mozilla.org/docs/Web/API/Service_Worker_API)
- ADR-003 — Anlagephilosophie (kein Markt-Timing -> kein Push)
- `5eyes-electron/frontend/reporting/src/api/handoff.ts` — Token-Handoff-Logik
