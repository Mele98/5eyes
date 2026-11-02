# Tax-Plugin-SDK — Architektur und Externe Schnittstelle

**Status:** stabilisiert mit U-32 (2026-06-06)
**Version:** TAX_SDK_VERSION = `2.0.0` (Breaking, siehe Changelog §11)
**Conformance-Vertrag:** `1.0.0`

## 1. Motivation

Ares wird perspektivisch von Beratern in mehreren Laendern eingesetzt.
Jedes Land hat ein eigenes Steuerregime mit Sonderregeln (CH-Kantone,
DE-Splittingtarif, FR-IFI, US-LTCG, SG/HK-Capital-Gains-frei).

Statt fuer jedes Land im Core-Code eine `if country == 'XX'`-Verzweigung
zu bauen, ist Tax als **Plugin-System** designed:

- Das Core kennt nur das `TaxRegime`-Protocol.
- Jede Jurisdiction implementiert das Protocol als eigene Klasse.
- Klassen registrieren sich beim Import via `@register_regime(...)`.
- Externe Dritt-Anbieter koennen ihr Land als **eigenes pip-Paket**
  liefern und via Python Entry-Points einbinden — **ohne** Ares-Code
  zu modifizieren.

## 2. SDK-Oberflaeche

Alles was ein externer Implementierer braucht, kommt aus
`services.tax.sdk`:

```python
from services.tax.sdk import (
    # Protocol + Datentypen
    TaxRegime, TaxContext, TaxResult,
    # Registry
    register_regime, resolve_regime_class,
    # Conformance-Tests
    ConformanceContract, ConformanceReport, ConformanceRequirement,
    # Discovery
    EXTERNAL_REGIME_ENTRY_POINT_GROUP,
    discover_external_regimes,
    # Versionen
    TAX_SDK_VERSION, TAX_SDK_CONFORMANCE_CONTRACT_VERSION,
)
```

Die Symbole sind in `SDK_PUBLIC_API` aufgelistet. Drift-Tests pinnen
sie — ein Removal erfordert Major-Version-Bump und Migration-Doc.

## 3. Quick-Start: Neues Land hinzufuegen

### 3.1 In-Tree (Core-Beitrag)

1. Datei `services/tax/regimes/<country_code>.py`:
   ```python
   from services.tax.sdk import register_regime, TaxContext, TaxResult

   @register_regime("VN")
   class VNTaxRegime:
       id = "VN"
       country_code = "VN"
       region_code = None
       display_name = "Vietnam"
       local_currency = "VND"
       supports_wealth_tax = False
       supports_capital_gains_tax = True
       supports_inheritance_tax = False

       def annual_wealth_tax(self, ctx: TaxContext) -> TaxResult:
           return TaxResult(0.0, 0.0, self.id, "VN-2026-v1")
       # ... weitere Methoden gemaess Protocol
   ```
2. Import in `services/tax/regimes/__init__.py` ergaenzen.
3. Conformance-Test in `tests/tax/regimes/test_vn.py`:
   ```python
   from services.tax.sdk import ConformanceContract
   from services.tax.regimes.vn import VNTaxRegime

   def test_vn_conformance():
       report = ConformanceContract().run(VNTaxRegime())
       assert report.passed, report.format_failures()
   ```

### 3.2 Out-of-Tree (Drittanbieter-Paket)

Drittanbieter (z.B. lokales Steuerberatungsbuero in Vietnam) liefert
sein Regime als pip-Paket:

```toml
# pyproject.toml des Drittanbieters
[project]
name = "ares-tax-vietnam"
version = "2026.1.0"
dependencies = ["ares-tax-sdk>=2.0,<3.0"]

[project.entry-points."ares.tax_regime"]
vn = "tax_vietnam.regime"
```

```python
# tax_vietnam/regime.py
from services.tax.sdk import register_regime, TaxContext, TaxResult

# Pflicht ab SDK 2.0.0: SDK-Version, gegen die das Plugin gebaut wurde.
# Bewusst eine eigene Literal-Konstante, KEIN Re-Export von TAX_SDK_VERSION.
TAX_SDK_TARGET_VERSION = "2.0.0"

@register_regime("VN")
class VNTaxRegime:
    ...
```

Auf dem Ares-Host:
```
pip install ares-tax-vietnam
# Ares erkennt das Plugin beim naechsten Boot automatisch.
```

## 4. Conformance-Vertrag

Eine Regime-Implementierung muss alle MUSS-Requirements (`severity =
mandatory`) erfuellen, sonst wird sie nicht akzeptiert.

### Aktuelle Pflicht-Requirements (Vertrags-Version `1.0.0`)

| ID                     | Anforderung                                            |
|------------------------|--------------------------------------------------------|
| `R001-id`              | `regime.id` ist nicht-leerer String                    |
| `R002-country`         | `country_code` ist ISO 3166-1 alpha-2 (UPPERCASE)      |
| `R003-name`            | `display_name` ist gesetzt                             |
| `R004-currency`        | `local_currency` ist ISO 4217 (UPPERCASE)              |
| `R005-wealth-nonneg`   | `annual_wealth_tax` liefert nicht-negativen Betrag     |
| `R006-capgains-result` | `capital_gains_tax` liefert `TaxResult`                |
| `R007-dividend-result` | `dividend_tax` liefert `TaxResult`                     |
| `R008-overrides-immutable` | `with_overrides` mutiert das Original NICHT        |
| `R009-validate-tuple`  | `validate_parameters` liefert `tuple[str, ...]`        |

### SOLL-Requirements (Warnungen, keine Fail)

| ID                  | Anforderung                                       |
|---------------------|---------------------------------------------------|
| `R010-tariff-version` | `TaxResult.tariff_version` ist gesetzt          |

Drittanbieter-CI:
```python
def test_my_regime():
    from services.tax.sdk import ConformanceContract
    report = ConformanceContract().run(MyRegime())
    assert report.passed, report.format_failures()
```

## 5. Entry-Point-Discovery

> **Breaking (2026-10, Welle W2-d):** Die Entry-Point-Gruppe heisst
> `ares.tax_regime`. Die fruehere Gruppe wird nicht mehr gelesen, es
> gibt keinen Alias. Dritt-Plugins muessen ihre `pyproject.toml` auf den
> neuen Gruppennamen umstellen.

Beim Ares-Boot (`main.py:lifespan()`) ruft Ares
`discover_external_regimes()` auf. Diese Funktion:

1. Sucht alle Entry-Points unter Group `ares.tax_regime`.
2. Laedt jedes Plugin (`ep.load()` triggert dessen
   `@register_regime`-Decorators).
3. Returnt einen `DiscoveryResult` mit `loaded_plugins`,
   `failed_plugins`, `skipped_plugins`.
4. **Ohne Erwartungs-Manifest bricht der Boot NICHT ab** wenn ein
   Plugin kaputt oder SDK-inkompatibel ist — der Fehler wird geloggt +
   im Result sichtbar. Mit Manifest siehe §5.2 (harter Fehler).

```python
from services.tax.sdk import discover_external_regimes

result = discover_external_regimes(
    skip_plugins=["alpha-version-not-ready"],
)
if not result.succeeded:
    for name, msg in result.failed_plugins:
        ops_alert(f"Tax-Plugin '{name}' broken: {msg}")
```

### 5.1 SDK-Kompatibilitaet (ab 2.0.0, fail-closed)

Der Boot-Pfad (`services/tax/plugin_inventory.py`,
`load_external_tax_plugins`) prueft jedes geladene Plugin-Objekt (Modul
oder Klasse des Entry-Points) auf `TAX_SDK_TARGET_VERSION`:

- fehlt, kein Semver, anderer Major als der Host oder neuer als der Host
  -> Plugin wird abgelehnt (`failed_plugins`), alle Registrierungen, die
  sein Import vorgenommen hat, werden zurueckgerollt;
- Plugins mit Major < 2 werden damit immer abgelehnt.

### 5.2 Erwarteter Plugin-Bestand (optional)

Setting `tax_plugin_expected_manifest` (Env `TAX_PLUGIN_EXPECTED_MANIFEST`)
zeigt auf ein JSON-Manifest **ausserhalb des Repos**:

```json
{"schema_version": 1,
 "plugins": [{"name": "vn", "version": "2026.1.0"}, {"name": "sg"}]}
```

Ist es gesetzt, ist jede Abweichung ein harter Fehler
(`TaxPluginInventoryError`, Boot stoppt): Manifest unlesbar/ungueltig,
erwartetes Plugin fehlend, doppelt installiert, abweichende
Distributions-Version, nicht im Manifest stehendes Plugin, Ladefehler
oder SDK-inkompatibel. Die Bestandspruefung laeuft **vor** jeder
Code-Ausfuehrung eines Plugins.

Ohne Manifest ist der Nullfall (0 Plugins) erlaubt, wird aber als
Warnung geloggt — ein misslungener Cutover ist dann nicht von "keine
Plugins" unterscheidbar. Fuer Deployments mit externen Plugins ist das
Manifest deshalb Pflicht.

Paket-Signaturen werden derzeit **nicht** geprueft (keine
Signatur-Infrastruktur im Repo; offener Owner-Punkt).

## 6. Sicherheit

Plugin-Loading bedeutet **Code-Ausfuehrung auf dem Host**. Daher:

- Nur Pakete aus **vertrauenswuerdiger Quelle** installieren (privater
  Index, signierte Pakete, intern auditiert).
- Fuer Multi-Tenant-Hosting sollten Plugins **per Tenant deaktivierbar**
  sein (Config-Flag `disabled_tax_plugins`).
- Sandbox-Ausfuehrung (z.B. `RestrictedPython`) ist NICHT vorgesehen
  — das Plugin laeuft im gleichen Prozess wie Ares selbst.

## 7. Versionierung

`TAX_SDK_VERSION` folgt **Semver**:

| Aenderung                                          | Bump      |
|----------------------------------------------------|-----------|
| Neue **optionale** Protocol-Methode (Default-Impl) | Minor     |
| Neue Pflicht-Methode oder Removal                  | **Major** |
| Bugfix, Doku, Logging                              | Patch     |
| Neue Conformance-Requirement (mandatory)           | **Major** Vertrag |
| Neue Conformance-Requirement (recommended)         | Minor Vertrag |

Bei Major-Bump:
- Migration-Section in dieser Datei ergaenzen
- 6-Monats-Deprecation-Window fuer alte Version
- Drittanbieter via Mail/Newsletter informieren

## 8. Beziehung zu Roadmap

- **U-32** (2026-06-06): SDK-Stabilisierung — dieses Dokument.
- **U-33** (geplant): Erste Drittanbieter-Sandbox-Sample-Repo.
- **U-34** (geplant): Conformance-Badge fuer Drittanbieter-READMEs.

## 9. Nicht-Ziele

Was das Tax-SDK **nicht** macht:

- Es bietet KEINE Tarif-Daten-Updates fuer externe Plugins — der
  Drittanbieter ist fuer seine eigenen Tarif-Versionen verantwortlich.
- Es macht KEINE Tax-Optimierungs-Vorschlaege — das ist Aufgabe des
  separaten `optimizer`-Moduls.
- Es ersetzt **nicht** lokale Steuerberatung — die Plugins liefern
  Modell-Schaetzungen fuer das Planungs-Tool, keine rechtsverbindliche
  Steuerberechnung.

## 10. Referenzen

- Protocol: `services/tax/base.py` — `TaxRegime`, `TaxContext`, `TaxResult`
- Registry: `services/tax/registry.py` — `register_regime`,
  `resolve_regime_class`
- Discovery: `services/tax/discovery.py` — `discover_external_regimes`
- Conformance: `services/tax/conformance.py` — `ConformanceContract`
- SDK-Bundle: `services/tax/sdk.py` — alles Public-API

## 11. Changelog

### 2.0.0 (2026-10-31, W2-804-01) — Breaking

- Entry-Point-Gruppe ist `ares.tax_regime`. Die fruehere Gruppe wird
  nicht mehr gelesen; es gibt **keinen** Alias und kein
  Deprecation-Fenster fuer die alte Gruppe.
- Plugins muessen `TAX_SDK_TARGET_VERSION` (Major 2) deklarieren;
  Plugins ohne Deklaration oder mit Major < 2 werden fail-closed
  abgelehnt.
- Neu: optionales Erwartungs-Manifest (§5.2).
- Keine Aenderung an Protocol, Registry-Semantik, Conformance-Vertrag
  (`1.0.0`) oder an Steuerberechnungen.

Migration fuer Drittanbieter:
1. `pyproject.toml`: `[project.entry-points."ares.tax_regime"]`.
2. Im Plugin-Modul bzw. in der Entry-Point-Klasse
   `TAX_SDK_TARGET_VERSION = "2.0.0"` setzen.
3. Abhaengigkeit auf `>=2.0,<3.0` anheben.
4. Betreiber: Plugin im Erwartungs-Manifest eintragen.

### 1.1.0 / 1.0.0

- 1.0.0: SDK-Stabilisierung (U-32). 1.1.0: Zwischenstand vor dem
  Gruppenwechsel (Gruppenwechsel faelschlich als Minor deklariert,
  durch 2.0.0 ersetzt).
