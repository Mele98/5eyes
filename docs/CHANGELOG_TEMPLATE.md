# CHANGELOG Template

Format: [Keep a Changelog 1.1](https://keepachangelog.com/de/1.1.0/)
Versioning: [Semantic Versioning 2.0](https://semver.org/spec/v2.0.0.html)

---

## [Unreleased]

### Added
- (Was wurde NEU hinzugefuegt, additiv)

### Changed
- (Was wurde GEAENDERT — Verhalten/UX, kompatibel)

### Deprecated
- (Was wird BALD entfernt — Vorwarnung)

### Removed
- (Was wurde ENTFERNT — Breaking)

### Fixed
- (Was wurde GEFIXT — Bugs)

### Security
- (SEC-Fixes — pflichtgemaess gesondert dokumentiert)

---

## Template fuer Release-Eintrag

```markdown
## [1.4.0] - 2026-06-15

### Added
- U-66 FIDLEG-Suitability-Audit + Aggregator-Sektion 19 (#133)
- U-68 ConflictOfInterest-Disclosures Sektion 18 (#132)
- ...

### Changed
- U-22 Mandate-Lock-Status macht Read-Only-Reason sichtbar (#141)

### Fixed
- U-7 CSP-Header verhindern Script-Injection (#152)

### Security
- U-59 Bearer-Token max 24h in production (#127)
- U-61 Electron-Security Hardening (#125)

### Compliance-Review
- Reviewer: <Name>, Datum: <YYYY-MM-DD>
```

---

## Berater-tauglich vs Engineering-only

Ein Changelog ist KEIN Git-Log. Ein Eintrag muss:

- Aus Berater-Perspektive verstaendlich sein
- Den FACHLICHEN Effekt beschreiben (nicht den Code-Refactor)
- FINMA-relevante Aenderungen klar markieren (-> Compliance-Review)

**Schlecht:** `Refactor of advisory_report.py to use lazy imports`
**Gut:** `Aggregator startet schneller bei Mandaten ohne Risikoprofil`

**Schlecht:** `bump pytest 9.0.1 -> 9.0.2`
**Gut:** (Dependency-Updates gehoeren NICHT in den User-facing Changelog;
       separates Dependency-Logbook fuehren)

---

## Workflow

1. Bei jedem PR: `[Unreleased]`-Sektion ergaenzen falls user-facing
2. Bei Release: `[Unreleased]` zu `[X.Y.Z] - YYYY-MM-DD` umbennen
3. Neuen leeren `[Unreleased]`-Block oben einfuegen
4. Release-Tag erstellen (siehe `docs/RELEASE_TAGS.md`)
