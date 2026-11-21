# Upgrade-Hinweise für Betreiber

Hier steht, was nach dem Einspielen einer neuen Version einmalig zu tun ist.
Neueste Einträge oben.

## P5c – Zielstatus nur aus der Zielanalyse (M-3)

**Was passiert nach dem Deploy:**
Alle bereits publizierten Beratungsentscheide (Siegel) sind gesperrt. Kunden-PDFs
und andere Kanäle eines solchen Entscheids liefern den Grund
`CCX_GOAL_METRIC_MISMATCH`.

**Warum:**
Die Kennzahl der Zielerreichung hat zwei neue Versionen:
- Die Zielrevision heisst jetzt `goal-rev/2`. Sie zählt alle wirtschaftlichen
  Zielfelder des Optimierers, neu auch `pension_pillar` und `lifecycle_decision`.
- Die Status-Regel heisst jetzt `ares-goal-status/2` und steht in der Kennzahl.
  Der Zielstatus ist die vorsichtigste Einstufung.

Der Hash der Kennzahl ändert sich deshalb für jedes Mandat. Das ist gewollt
(fail-closed): Ein Siegel mit der alten Kennzahl wird nie still weiter ausgeliefert.

**Was zu tun ist:**
Für **jedes publizierte Mandat** einmal:
1. «Anlagestrategie berechnen»
2. Empfehlung finalisieren
3. Asset Allokation › Publizieren

Erst danach sind die Kanäle des Mandats wieder lieferbar. Diese Schritte vor dem
Deploy einplanen.

**Weitere Änderungen dieser Version, die Betreiber kennen sollten:**
- Der Entwickler-Schalter für automatisches Neurechnen (localStorage
  `auto_recompute`) ist entfernt. Eine neue Strategie entsteht nur durch den Klick
  «Anlagestrategie berechnen» oder bei einem Mandat, das noch nie berechnet wurde.
- Der Review-Trigger «Zielerreichung gefährdet» löst auch aus, wenn ein Ziel laut
  Zielanalyse nicht bewertbar ist (Unwissen ist keine Entwarnung). Bei Mandaten mit
  einer alten Berechnung ohne bewertbare Zielanalyse erscheint er deshalb neu.
  «Anlagestrategie berechnen» behebt das, wenn die Ursache eine alte Berechnung
  ist. Ziele «ausserhalb Horizont» (Zieldatum nach dem Simulationshorizont) und
  Ziele, die auch nach der Neuberechnung «nicht beurteilbar» bleiben (z. B. zu
  kleine Stichprobe oder unzertifizierte Zielmetrik), halten den Trigger bewusst
  offen: Die App warnt hier lieber zu viel als zu wenig. Dann Zieldatum, Horizont
  oder Zielangaben prüfen. Der Trigger sperrt keine Funktion; er zählt nur im
  Cockpit und im Kalender.
