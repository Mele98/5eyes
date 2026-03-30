# Market Data Provider Strategy

## Zielbild

5Eyes trennt den Datenstack in Rollen statt in einen einzigen "Preisprovider". Das ist wichtig, weil Preisabruf, Identifier-Mapping, Fondsreferenzdaten und Makrodaten unterschiedliche Qualitaets- und Betriebsanforderungen haben.

## Aktiver Runtime-Stand

| Rolle | Aktiver Pfad | Zweck |
| --- | --- | --- |
| Marktpreise | `yfinance` mit `stooq`-Fallback | Bewertung, Drift, Rebalancing |
| Referenzdaten | `local_catalog` | Kuratierte Produktnamen, Proxies, synthetische Par-Werte |
| Identifier-Mapping | `product_symbol_or_isin` + `local_catalog` | Direktes Symbol-/ISIN-Mapping |
| Makroannahmen | `manual_cma` | Versionierte Capital Market Assumptions in V1 |

## Empfohlenes Zielbild

| Rolle | Bevorzugter Provider | Fallback / Upgrade | Warum |
| --- | --- | --- | --- |
| Marktpreise Multi-Asset | `twelvedata` | `eodhd` | Einfache REST/WebSocket-Automatisierung, breite Abdeckung ueber Aktien, ETFs, Mutual Funds, FX und Krypto |
| Fonds-/Referenzdaten | `eodhd` | `six` | Fundamentals, Corporate Actions, Instrumentensuche, Exchange-Metadaten |
| Identifier-Mapping | `openfigi` | `eodhd` | Sauberes ISIN/FIGI/Ticker-Mapping fuer produktive Master-Data-Pfade |
| Makrodaten global | `fred` | `ecb` | Offizielle Zeitreihen, vintagierbar, sehr gut automatisierbar |
| Makrodaten Schweiz | `snb` | `fred` | Offizieller Schweizer Kontext fuer Zinsen, FX und Konjunktur |
| Institutioneller Schweiz-/Bank-Feed | `six` | - | Premium-Schicht fuer produktive Bank-/WM-Setups mit hoher Schweiz-Relevanz |

## Integrationsreihenfolge

1. `openfigi` fuer Identifier-Mapping anbinden.
2. `eodhd` fuer Referenzdaten, Corporate Actions und Such-/Coverage-Pfade anbinden.
3. `twelvedata` fuer produktionsnahen Preisabruf anbinden.
4. `fred`, `ecb` und `snb` fuer Makroserien und Simulationen anbinden.
5. `six` nur dann dazunehmen, wenn institutionelle Schweiz-/Lizenzqualitaet wirklich benoetigt wird.

## Wichtige Designregeln

- Kundendaten bleiben strikt intern; externe Provider liefern nur Markt-, Referenz- und Makrodaten.
- Lokale Overrides bleiben erhalten. Ein kuratierter Produktkatalog soll externe Feeds uebersteuern koennen.
- Mapping und Referenzdaten werden getrennt von Preisdaten gepflegt.
- Makrodaten fliessen nicht direkt als "Live-Preise" in Rebalancing ein, sondern in Annahmen, Simulationen und Reporting-Kontext.

## Nicht als Backend-Quelle empfohlen

`GOOGLEFINANCE` ist fuer schnelle Sheets-Prototypen brauchbar, aber nicht fuer ein produktives WM-Backend:

- nicht fuer professionelle Finanznutzung gedacht
- unterstuetzt die meisten internationalen Boersen nicht
- historische Daten sind nicht via Sheets API oder Apps Script abrufbar

## Naechste Umsetzungsschritte im Code

1. OpenFIGI-Mapping in den Produktstammdatenpfad ziehen.
2. Referenzdaten-Sync fuer `products` und Corporate Actions bauen.
3. Preisabruf auf konfigurierbare Provider-Clients abstrahieren.
4. Makro-Connectoren fuer FRED / ECB / SNB in die Simulations- und CMA-Schicht einfuehren.
