"""KN3-U / N-917R2-05 (H-167 R2, Dok. 118): Waechter gegen ASCII-Umschriften
(ae/oe/ue statt ä/ö/ü) in sichtbaren Texten der Classic-Berateroberflaeche.

Geprueft werden alle String-Literale und HTML-Textknoten des Monolithen inkl.
ausgelagerter Teile (``read_monolith_bundle``) und der eigenstaendigen
Frontend-Module (``STANDALONE_FRONTEND_MODULES``) -- ohne Kommentare und ohne
Regex-Literale (Kommentare duerfen Umschrift behalten, Regex-Muster erkennen
Altformen).

Ein Wort gilt als Umschrift, wenn es nach Abzug echter deutscher/englischer
Wortbestandteile mit ae/oe/ue (``REAL_PARTS``: neue, aktuell, Steuer, Quelle,
value, true ...) noch ae/oe/ue enthaelt. camelCase-Bezeichner sind Code.

``KEYS`` ist die begruendete Allowlist fuer Werte, die mit Server/DB
uebereinstimmen muessen (Schluessel, Optionswerte, DOM-IDs, API-Pfade). Diese
werden nie angezeigt; die Anzeige laeuft ueber eine Abbildung mit Umlaut.
"""
from __future__ import annotations

import re

from tests.monolith_source import FRONTEND_DIR, STANDALONE_FRONTEND_MODULES, read_monolith_bundle

COMMENTS = re.compile(r"<!--.*?-->|/\*.*?\*/|(?<![:'\"\\])//[^\n]*", re.S)
LITERALS = re.compile(r"'(?:\\.|[^'\\\n])*'|\"(?:\\.|[^\"\\\n])*\"|`(?:\\.|[^`\\])*`")
TEXT_NODES = re.compile(r">([^<>{}]+)<")
WORD = re.compile(r"[A-Za-zÄÖÜäöü]*(?:ae|oe|ue)[A-Za-zÄÖÜäöü]*", re.I)
CAMEL = re.compile(r"[a-z][A-Z]")

# Echte Wortbestandteile mit ae/oe/ue (deutsch und englisch); werden vor der
# Pruefung aus dem Wort entfernt, damit z. B. "Vermoegensteuer" trotzdem auffaellt.
REAL_PARTS = (
    "aktuell", "manuell", "individuell", "eventuell", "punktuell", "virtuell", "neue", "steuer", "quelle",
    "dauer", "teuer", "genau", "zuerst", "treue", "bauen", "erneuer", "einkommen", "ereignis", "frequen",
    "true", "value", "continue", "issue", "due", "request", "question", "sequence", "segoe", "query",
    "blue", "queue", "duell", "mauer", "trauer", "bauer", "feuer",
)

# Begruendete Allowlist (Wort -> Grund). Nur Werte, keine sichtbaren Texte.
KEYS = {
    "Liquiditaet": "Anlageklassen-Schluessel des Servers (asset_class); Anzeige ueber assetDisplayName/ENGINE_LABELS",
    "liquiditaet": "Bucket-Schluessel (normalizeBandKey/Rundungsmodul), Vergleichswert",
    "Liquiditaet_CHF": "Sub-Anlageklassen-Schluessel (CMA), Anzeige ueber label",
    "Liquiditaet_USD": "Sub-Anlageklassen-Schluessel (CMA), Anzeige ueber label",
    "liquiditaetsreserve": "limiting_factor-Code des Servers; Anzeige 'Liquiditätsreserve bindend'",
    "jaehrlich": "Cashflow-Frequenz-Schluessel (DB-CHECK); Anzeige ueber cashflowDisplayFrequency",
    "halbjaehrlich": "Cashflow-Frequenz-Schluessel (DB-CHECK); Anzeige ueber cashflowDisplayFrequency",
    "vierteljaehrlich": "Cashflow-Frequenz-Schluessel (DB-CHECK); Anzeige ueber cashflowDisplayFrequency",
    "erhoeht": "KYC risk_category-Wert (Schema); Optionstext 'erhöht'",
    "primaer": "Ziel-Haertegrad-Schluessel (Altwert), Vergleich",
    "Primaer": "Ziel-Haertegrad-Schluessel (Altwert), Vergleich",
    "persoenlich": "communication_channel-Wert (Beratungsprotokoll); Optionstext 'Persönlich'",
    "Verkaufserloes": "Zufluss-Quellenschluessel (source_type); Anzeige 'Verkaufserlös'",
    "Saeule": "Teil des Zufluss-Quellenschluessels 'Saeule3b'; Anzeige 'Säule 3b'",
    "nachtraeglich": "delivery_timing-Wert des Servers (Kundeninformation); Anzeige 'nachträglich'",
    "pruefpunkte": "Abschnittsschluessel (Checkbox-Wert) der PDF-Auswahl",
    "risikowaehrungen": "Abschnittsschluessel (Checkbox-Wert) der PDF-Auswahl",
    "reinvermoegen": "DOM-ID kpi-reinvermoegen",
    "beratungsvermoegen": "DOM-ID kpi-beratungsvermoegen",
    "Schwellenlaender": "Sub-Anlageklassen-Name der Seed-Daten (Server-Schluessel); Anzeige ueber aresTerm",
    "Beratungsvermoegen": "Parametername in einer Programmierfehler-Meldung des Rundungsmoduls (presentation-rounding.js)",
    "edoeb": "API-Pfad /edoeb-notification",
    "ae": "Dateinamen-Umschrift (ä -> ae), bewusst",
    "oe": "Dateinamen-Umschrift (ö -> oe), bewusst",
    "ue": "Dateinamen-Umschrift (ü -> ue), bewusst",
}


def _sources() -> dict[str, str]:
    out = {"ares.html (Bundle)": read_monolith_bundle()}
    for entry in STANDALONE_FRONTEND_MODULES:
        name = entry if isinstance(entry, str) else entry[0]
        path = FRONTEND_DIR / name
        if path.suffix == ".js" and path.exists():
            out[name] = path.read_text(encoding="utf-8")
    return out


def _is_transcription(word: str) -> bool:
    if CAMEL.search(word):
        return False
    rest = word.lower()
    for part in REAL_PARTS:
        rest = rest.replace(part, "")
    return re.search(r"ae|oe|ue", rest) is not None


def visible_transcriptions(sources: dict[str, str]) -> list[tuple[str, str, str]]:
    found = []
    for name, text in sources.items():
        stripped = COMMENTS.sub("", text)
        chunks = [m.group(0) for m in LITERALS.finditer(stripped)] + [m.group(1) for m in TEXT_NODES.finditer(stripped)]
        for chunk in chunks:
            for word in WORD.findall(chunk):
                if word in KEYS or not _is_transcription(word):
                    continue
                found.append((name, word, chunk.strip()[:120]))
    return found


def test_no_ascii_transcriptions_in_visible_ui_texts():
    found = visible_transcriptions(_sources())
    assert found == [], "Umschrift statt Umlaut in sichtbarem Text:\n" + "\n".join(f"{n}: {w} -- {c}" for n, w, c in found)


def test_allowlist_entries_are_still_used_and_reasoned():
    sources = _sources()
    joined = "\n".join(COMMENTS.sub("", t) for t in sources.values())
    for word, reason in KEYS.items():
        assert len(reason) > 10, word
        assert re.search(r"(?<![A-Za-z])" + re.escape(word) + r"(?![A-Za-z])", joined), f"Allowlist-Eintrag {word} wird nicht mehr verwendet"


def test_guard_detects_transcriptions_counterproof():
    """Gegenprobe: typische Umschriften in Text und Attribut werden erkannt, echte Woerter nicht."""
    probe = {
        "probe.js": "var a='Kapitalzufluesse';var b=\"3a-Bezuege\";var c=`Vermoegensteuer`;",
        "probe.html": '<div title="x">Strategie geaendert fuer Sie</div><span>Aktuelle neue Steuer-Quelle</span>',
    }
    words = sorted({w for _n, w, _c in visible_transcriptions(probe)})
    assert words == ["3a-Bezuege".split("-")[1], "Kapitalzufluesse", "Vermoegensteuer", "fuer", "geaendert"], words
    # Kommentar und Regex-Literal sind ausgenommen.
    assert visible_transcriptions({"p.js": "// Vermoegen fuer\nvar r=/geaendert/g;"}) == []
    # Schluessel aus der Allowlist bleiben erlaubt.
    assert visible_transcriptions({"p.js": "var k='Liquiditaet';"}) == []
