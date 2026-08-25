# Tax Plugin Integration Interface

Stand: 2026-06-19

## Zweck

Diese Schnittstelle beschreibt, wie der Optimizer spaeter Nach-Steuer-Renditen
abrufen kann, ohne Steuerlogik in `services/optimizer/*` oder
`services/portfolio_engine.py` zu verdrahten. Die aktuelle PR liefert nur die
Architektur, Referenz-Implementierung und einen duennen Adapter. Die eigentliche
Objective-Integration bleibt Sprint #90.

## Plugin-Kern

Laender implementieren `services.tax.base.TaxJurisdiction` und registrieren sich
ueber `services.tax.registry.register_jurisdiction`. Die Registry wird nach
ISO-Landcode abgefragt:

```python
from services.tax.registry import get_jurisdiction

jurisdiction = get_jurisdiction("CH")
result = jurisdiction.estimate(profile)
```

`TaxProfileInput` und `TaxEstimateResult` liegen in `schemas.tax`. Alle Betraege
sind Rappen/Cents der lokalen Waehrung, Saetze sind Basispunkte.

## Adapter fuer #90

Der spaetere Optimizer-Andockpunkt ist bewusst eine reine Funktion:

```python
from services.tax.after_tax import get_after_tax_return

estimate = get_after_tax_return(
    profile,
    gross_return_bps=500,
    return_base_rappen=10_000_000,
)
```

Rueckgabe:

- `gross_return_bps`
- `estimated_tax_drag_bps`
- `after_tax_return_bps`
- `gross_gain_rappen`
- `tax_rappen`
- `assumptions`

## Aktuelle fachliche Grenze

Der Adapter beruecksichtigt aktuell realisierte Kapitalgewinne. Dividenden,
Zinsen, Quellensteuern und Produktmantel-Effekte benoetigen eine spaetere
Return-Decomposition des Optimizers. Bis dahin gilt: bei Unsicherheit wird
konservativ gerechnet und die Annahme in `assumptions[]` offengelegt.

## Nicht-Ziele dieser PR

- Keine Aenderung an `services/optimizer/*`
- Keine Aenderung an `services/portfolio_engine.py`
- Keine Steuer-Objective
- Keine aktive Portfolio-Ueberwachung

## Erweiterung fuer weitere Laender

Neue Laender fuegen ein Modul unter `services/tax/jurisdictions/` hinzu,
implementieren `TaxJurisdiction`, registrieren sich per Decorator und liefern
eigene Parameterdaten. Der Kern und der Adapter bleiben unveraendert.

