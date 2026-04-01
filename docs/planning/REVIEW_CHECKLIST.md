# Claude Review Checklist

Claude soll Review nicht als allgemeine Meinung schreiben, sondern entlang dieser Punkte:

## 1. Fachlogik

- Entspricht die Implementierung der dokumentierten Fachquelle?
- Wurden offene Punkte als `OWNER-DECISION` behandelt oder still entschieden?
- Gibt es eine UI-Luege zwischen sichtbarem Zustand und Backend-Wahrheit?

## 2. Datenfluss

- Sind Gesamtvermoegen, Beratungsvermoegen, Cashflows und Ziele konsistent verbunden?
- Werden Demo-, Offline- und Live-Pfade sauber getrennt?
- Sind API-Request und API-Response wirklich vertragskonform?

## 3. Runtime-Risiken

- Gibt es Race Conditions?
- Gibt es doppelte alte Funktionen oder Legacy-Overrides?
- Koennen Buttons doppelt feuern oder in leere Endpunkte laufen?

## 4. UX / Beratungskontext

- Ist fuer den Kunden klar, was berechnet, gespeichert oder nur angezeigt wird?
- Sind Error-States ehrlich?
- Ist der Flow im Kundengespraech ruhig, nachvollziehbar und ohne technische Irritation?

## 5. Testabdeckung

- Unit Tests fuer Kernlogik
- API-/Contract-Tests fuer Schnittstellen
- GUI-/Smoke-Test fuer den sichtbaren Flow
- Edge Cases fuer fehlende Daten, 422/500 und Demo-Modus

## 6. Review-Ausgabe

Claude soll Findings nach Prioritaet liefern:

1. blocker
2. fachlich falsch
3. technisches Risiko
4. fehlende Tests

Wenn keine Findings vorliegen, soll Claude das explizit sagen.
