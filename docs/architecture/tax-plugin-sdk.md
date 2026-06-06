# Tax-Plugin-SDK — Architektur und Externe Schnittstelle

**Status:** stabilisiert mit U-32 (2026-06-06)
**Version:** TAX_SDK_VERSION = `1.0.0`
**Conformance-Vertrag:** `1.0.0`

## 1. Motivation

5eyes wird perspektivisch von Beratern in mehreren Laendern eingesetzt.
Jedes Land hat ein eigenes Steuerregime mit Sonderregeln (CH-Kantone,
DE-Splittingtarif, FR-IFI, US-LTCG, SG/HK-Capital-Gains-frei).

Statt fuer jedes Land im Core-Code eine `if country == 'XX'`-Verzweigung
zu bauen, ist Tax als **Plugin-System** designed:

- Das Core kennt nur das `TaxRegime`-Protocol.
- Jede Jurisdiction implementiert das Protocol als eigene Klasse.
- Klassen registrieren sich beim Import via `@register_regime(...)`.
- Externe Dritt-Anbieter koennen ihr Land als **eigenes pip-Paket**
  liefern und via Python Entry-Points einbinden — **ohne** 5eyes-Code
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
name = "5eyes-tax-vietnam"
version = "1.0.0"
dependencies = ["5eyes-tax-sdk>=1.0,<2.0"]

[project.entry-points."5eyes.tax_regime"]
vn = "tax_vietnam.regime"
```

```python
# tax_vietnam/regime.py
from services.tax.sdk import register_regime, TaxContext, TaxResult

@register_regime("VN")
class VNTaxRegime:
    ...
```

Auf dem 5eyes-Host:
```
pip install 5eyes-tax-vietnam
# 5eyes erkennt das Plugin beim naechsten Boot automatisch.
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

Beim 5eyes-Boot (`main.py:lifespan()`) ruft 5eyes
`discover_external_regimes()` auf. Diese Funktion:

1. Sucht alle Entry-Points unter Group `5eyes.tax_regime`.
2. Laedt jedes Plugin (`ep.load()` triggert dessen
   `@register_regime`-Decorators).
3. Returnt einen `DiscoveryResult` mit `loaded_plugins`,
   `failed_plugins`, `skipped_plugins`.
4. **Boot bricht NICHT ab** wenn ein Plugin kaputt ist — der Fehler
   wird geloggt + im Result sichtbar.

```python
from services.tax.sdk import discover_external_regimes

result = discover_external_regimes(
    skip_plugins=["alpha-version-not-ready"],
)
if not result.succeeded:
    for name, msg in result.failed_plugins:
        ops_alert(f"Tax-Plugin '{name}' broken: {msg}")
```

## 6. Sicherheit

Plugin-Loading bedeutet **Code-Ausfuehrung auf dem Host**. Daher:

- Nur Pakete aus **vertrauenswuerdiger Quelle** installieren (privater
  Index, signierte Pakete, intern auditiert).
- Fuer Multi-Tenant-Hosting sollten Plugins **per Tenant deaktivierbar**
  sein (Config-Flag `disabled_tax_plugins`).
- Sandbox-Ausfuehrung (z.B. `RestrictedPython`) ist NICHT vorgesehen
  — das Plugin laeuft im gleichen Prozess wie 5eyes selbst.

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
- Original-Plugin-Spec: `docs/planning/2026-05-17-sprint-3-tax-plugin-system.md`
