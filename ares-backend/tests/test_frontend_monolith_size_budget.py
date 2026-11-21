"""Groessen-Budget des Monolithen (Electron-Frontend, eine HTML-Datei).

Ratchet, nur sinkend: neue Fachlogik gehoert in Module bzw. die React-App,
nicht in den Monolithen. Die Grenze ist die Zeilenzahl beim Einfuehren
des Budgets, Toleranz 0. Wer den Monolithen verkleinert, senkt
``MONOLITH_MAX_LINES`` im selben PR auf den neuen Stand; anheben ist nicht
vorgesehen (nur per ausdruecklichem Owner-Entscheid).

N-861-5 (Pruefrunde #861): zusaetzlich ein Byte-Budget. Das Zeilen-Budget
allein liess sich umgehen, indem Code an bestehende Zeilen angehaengt wird.
Gemessen mit LF-Zeilenenden (eine CRLF-Arbeitskopie zaehlt gleich). Grenze =
Stand beim Einfuehren, Toleranz 0, ebenfalls nur sinkend.

N-861-9: 1908660 = gemessener gemeinsamer Stand nach dem Merge von #858
(r5/livetest-fixes, enthaelt #853) in #861 (Merge-Reihenfolge #858 -> #861).
Kein Anheben gegenueber einem gemergten Stand: das Budget existierte nur auf
#861 (1902644), #858 brachte seine geprueften Live-Test-Fixes (+6016 Bytes)
ohne Byte-Budget mit; beide Staende werden hier zusammengefuehrt.

H3/I-04 (2026-11-07): Nach der Integrationsprobe lag der Monolith exakt am
Budget (31190 Zeilen / 1908660 Bytes). Drei in sich geschlossene Bloecke
wurden verhaltensneutral ausgelagert (ares.css, intro-sequence.js,
goal-review-runtime.js; siehe tests/monolith_source.py). Budget gesenkt auf
den neuen Stand 27675 / 1695446 (der Ratchet bleibt: nur sinkend). Die
ausgelagerten Dateien bekommen je ein eigenes Budget nach derselben Regel
(Stand beim Einfuehren, Toleranz 0) -- sonst waere die Auslagerung ein
Schlupfloch, ueber das der Monolith unbemerkt weiterwaechst.

H8 Kundeninformation/KYC/Vertretung (2026-11-07): neue Masken im neuen Teil
client-compliance.js (eigenes Budget, Stand bei Einfuehrung); sie haengen sich
selbst in Administration und Stammdaten ein. Im Monolithen nur die Einbindung;
renderAuditLogTable ist mit der Feldbezeichnung (N-873-09) in den Teil
umgezogen. Der Monolith schrumpft dabei (Budget auf den neuen Stand).

C-890-01 (2026-11-11): client-compliance.js +5 Zeilen/+727 Bytes fuer die
Statuszeile der KYC-Wiedervorlage-Policy (Budget auf den neuen Stand).
C-890-01 Nachtrag 1: neuer Teil kyc-review-policy.js (eigenes Budget, Stand bei
Einfuehrung); adminUpdateNewUserRoleHint aus dem Monolithen umgezogen -- der
Monolith schrumpft trotz Einbindung (Budget gesenkt: 27631 Z./1692930 B).
C-890-01 Nachtrag 2: kyc-review-policy.js +63 Z./+4282 B fuer "Offene
KYC-Freigaben" (Entscheid der zweiten Person); Monolith unveraendert.
C-890-01 Nachtrag 3: kyc-review-policy.js 413/24620 (Einladung der externen
Compliance-Person, 2FA-Hinweis, Konto-Herkunft), client-compliance.js 465/29504
(Hinweis "keine Kundennamen", Warnung bei Personendaten).
C-890-01 Nachtrag 4: kyc-review-policy.js 421/25340 (Einladung nur per Mail,
Weitergabe-Hinweis, Herkunftsindiz und Kompromittierungs-Hinweis).
C-890-01 Nachtrag 5: kyc-review-policy.js 427/25832 (Mailfehler-Hinweis,
Kompromittierungs-Satz).
H10 Datenschutz-Governance (2026-11-11): neue Masken im neuen Teil
privacy-governance.js (eigenes Budget, Stand bei Einfuehrung). Im Monolithen
nur die Einbindung; renderAuditLogPagination ist unveraendert in den Teil
umgezogen, der Monolith schrumpft (Budget auf den neuen Stand).
RC-CH-1 Teil 2a (Merge H10 nach C-890-01): beide Pakete lagern je eine
Funktion aus dem Monolithen aus (adminUpdateNewUserRoleHint ->
kyc-review-policy.js, renderAuditLogPagination -> privacy-governance.js);
beide Einbindungen bleiben. Budget bewusst auf den gemessenen Stand des
Integrationsbaums gesenkt: 27617 Z./1691994 B (kleiner als beide Seiten).

H6 (2026-11-07, Asset-Allocation-Grafik): Torte/Legende/SOLL-Quoten-Logik
und die zugehoerigen Stile nach ``aa-chart.js``/``aa-chart.css`` verlegt
(neue Teile mit eigenem Budget, Stand beim Einfuehren). Monolith dadurch
27639 / 1689802, ``ares.css`` 1143 / 90070 -- beide Budgets entsprechend gesenkt
(Stand H6-Feinschliff; die neuen Teile sind noch nicht gemergt, ihr Budget ist
der Stand bei der Einfuehrung durch diesen PR).

G7 (2026-11-11, gemeinsamer Rundungsformatter): Formatter-Logik nach
``presentation-rounding.js`` (eigenstaendiges Modul, STANDALONE_FRONTEND_MODULES)
verlegt; fmtNumber/fmtPct/formatRappen u. a. delegieren nur noch. Monolith dadurch
27619 / 1689693, ``aa-chart.js`` 329 / 20791 -- beide Budgets gesenkt.
H-153 Nachtrag 1: restliche Anzeige-Rundungen und Mandatswaehrung -> 27613 / 1689320,
``aa-chart.js`` 318 / 20791.
H-153 Nachtrag 2 (N-894-01..06): 27598 / 1689133, ``aa-chart.js`` 318 / 20681.
H-153 Nachtrag 3 (N-894-07..11, CHF-Guard): 27582 / 1688745, ``goal-review-runtime.js`` 1588 / 84613.
H-153 Nachtrag 4 (Grundregel Waehrung, N-894-12..17): 27447 / 1682837, ``goal-review-runtime.js`` 1564 / 83881,
``aa-chart.js`` 316 / 20632 (Kommentare gekuerzt, Budgets gesenkt).
RC-CH-1 Teil 2b (Merge G7+H6 nach H8/C-890-01/H10): Auslagerungen beider
Seiten gelten; Budget bewusst auf den gemessenen Stand des Integrationsbaums
gesenkt: 27389 Z./1679385 B (kleiner als beide Seiten).

E2 Nachhaltigkeitspraeferenzen (Dok. 106, 2026-11-07): Kundenmaske im neuen
Teil sustainability-preferences.js mit eigenem Budget. Im Monolithen nur die
Einbindung; Platz dafuer durch eine gemeinsame Themen-Namensliste
(AA_THEME_NAMES statt dreier gleicher Literale), er schrumpft dabei.
RC-CH-1 Teil 2b (Merge E2 nach G7): Budget auf den gemessenen Stand des
Integrationsbaums gesenkt: 27389 Z./1679248 B.

H9 (2026-11-08, Owner-UX): Gate der verbesserten Kurve in der
Vermoegensentwicklung nach ``ist-projection-gate.js`` (neuer Teil, Budget =
Stand bei Einfuehrung); erfundene Demo-/Platzhalterpfade entfernt. Monolith
27613 / 1687921 -- Budget entsprechend gesenkt. Danach Warnbox/Badge der
Risikofaehigkeits-Plausibilitaet aus der Maske entfernt: 27504 / 1681449.
H9 Nachtrag 1 (2026-11-11, Pruefrunde 61d8d69d): IST-Grafik-Aufbau in
``ist-projection-gate.js`` verschoben (IST-Horizont, Server-Pruefung),
Sitzungsgrenze als neuer Teil ``session-boundary.js``, Demo-IST-Pfad in
initCharts entfernt. Monolith 27460 / 1679579 -- gesenkt.
H9 Nachtrag 2 (2026-11-12): IST-Projektion aus EINER Server-Basis
(``ist-projection-basis.js``, neuer Teil), Kennzahlen-Renderer der
Vermoegensentwicklung nach ``ist-projection-gate.js`` verschoben. Monolith
27413 / 1676448 -- gesenkt.
H9 Nachtrag 4 (N-892-05..08): ungesicherte Eingaben als neuer Teil
``unsaved-changes.js``, ``doLogout`` nach ``session-boundary.js`` verschoben.
Monolith 27401 / 1676042 -- gesenkt.
RC-CH-1 Teil 2b (Merge H9 nach G7/E2): H9-Auslagerungen gelten; die G7-
Waehrungslogik der verschobenen Renderer ist in ist-projection-gate.js
nachgezogen (toter KPI-Zweig entfernt), die ESG-Erkennung in
unsaved-changes.js zeigt auf die E2-Karte. Budget auf den gemessenen Stand
gesenkt: 27163 Z./1666083 B; ist-projection-gate.js 288/15951,
unsaved-changes.js 86/4604.
CCX-P3-FX (2026-11-14): Vermoegenszufluesse (Waehrung je Zufluss) samt
cashflowSummaryQuery als neuer Teil ``wealth-inflows.js`` (282/16491)
ausgelagert; Monolith auf den gemessenen Stand gesenkt: 26905 Z./1651192 B.
CCX-P4 (2026-11-14): Publikationsstatus der Soll-Allokation und "Portfolio
umsetzen" (drei Funktionen umgezogen) als neuer Teil
``allocation-publication.js`` (276/13973); Monolith auf den gemessenen Stand
gesenkt: 26746 Z./1644375 B.
CCX-P3 Nachtrag 1 (N-909-07): Finalisierung mit Bestaetigung "Bewertung
aktuell" als Teil ``finalize-attestation.js`` (27/1705); Monolith 26887 Z./
1650341 B.
Merge P3 Nachtrag 1 in CCX-P4 (2026-11-18): beide Teile gelten; die P4-Statusmeldung
nach dem Finalisieren ("Kundenwirksam wird es nach der Publikation" +
refreshAllocationPublication) sitzt jetzt in ``finalize-attestation.js``
(27/1753); Monolith auf den gemessenen Stand gesenkt: 26728 Z./1643476 B.
CCX-P3 Nachtrag 2 (N-909-11): Wechselkurs-Editor als Teil
``fx-rates-editor.js`` (99/5202) ausgelagert; Monolith 26827 Z./1647400 B.
Merge P3 Nachtrag 2 in CCX-P4 (2026-11-18): alle drei Teile gelten
(allocation-publication.js, finalize-attestation.js 27/1753 mit P4-Meldung,
fx-rates-editor.js 99/5202); Monolith auf den gemessenen Stand: 26668 Z./1640535 B.
H11 Hygiene-Welle: Rueckfrage beim Mandatswechsel (unsaved-changes.js),
Anfragezaehler (sustainability-preferences.js), Ladehinweis
(privacy-governance.js), Vorzeichen-Fix -- je Datei ohne Wachstum; Budget auf
den gemessenen Stand gesenkt: 27161 Z./1666013 B; unsaved-changes.js 83/4476,
sustainability-preferences.js 517/26065, privacy-governance.js 500/35256.
Merge H11 in H12 (2026-11-18): alle Teile beider Seiten gelten; Monolith und
Teilbudgets auf den gemessenen Stand nach dem Merge: 26665 Z./1640432 B; privacy-governance.js
500/35256, sustainability-preferences.js 517/26065 (H11-Stand).
K1 Property-Gate (2026-11-19): Wertsteigerungs- und Amortisationsfeld aus der
Vermoegensmaske entfernt (Hinweis "Zins und Amortisation als Ausgaben-Cashflow
erfassen"), "Gemischt" nur noch als Altbestand waehlbar; Monolith 26662 Z./1639661 B.
K1-Nachtrag 1 (N-913-01/-11): Amortisationsfeld zurueck (Zins/Amortisation werden
aus den erfassten Werten gerechnet), tote Altmaske #m-edit-hypo entfernt; Monolith
26632 Z./1637553 B.
Integration H12+K1 (2026-11-19, r5/kern-integration): alle Teile beider Seiten
gelten; Monolith auf den gemessenen Stand nach dem Merge: 26629 Z./1637450 B.
K2 Kernkette CH (Dok. 115, 2026-11-19): Berater-Fuehrung als neuer Teil
``advisor-guidance.js`` (Budget = Stand bei Einfuehrung). Im Monolithen nur
Einbindung und Hooks; vier nie geoeffnete Legacy-Masken (m-edit-depot/-immo/
-hypo/-custom, mit Drittbank-Namen) und statische Platzhalterdaten entfernt --
der Monolith schrumpft (Budget gesenkt). allocation-publication.js schrumpft
(Einzelfreigabe-Ablauf nach advisor-guidance.js), finalize-attestation.js
ebenso; client-compliance.js +4 Z./+474 B fuer E2E-18 (Zeitpunkt der Uebergabe
sekundengenau, lokale Zeit und Kanal-Label).
K2-Nachtrag 1 (Pruefbericht H-166): Monolith 26485 Z./1625431 B (Hooks gegen
nominale Mischsummen, tote m-edit-Verweise entfernt, zwei Kommentare gekuerzt);
unsaved-changes.js 85/4470 (tote Masken-Eintraege). advisor-guidance.js ist im
selben, noch nicht gemergten PR eingefuehrt; sein Einfuehrungsstand umfasst den
Nachtrag (728/43966: Erst-Einrichtungsdialog mit "spaeter", Finalisieren-
Wegweiser, Verzehr-Logik, Grund fuer den gesperrten Ist-Pfad).
Integration H12+K1+K2 (2026-11-19, r5/kern-integration): alle Teile aller
Seiten gelten; Monolith und Teilbudgets auf den gemessenen Stand nach dem Merge:
26479 Z./1624968 B; unsaved-changes.js 82/4342 (H11-Rueckfrage + K2-Bereinigung).
KN-U Kernkette-Nachtrag Classic-UI (Dok. 117, 2026-11-19): neuer Teil
``mandate-view.js`` (Budget = Stand bei Einfuehrung): Reset beim Mandatswechsel,
Banner unter der Kopfzeile, veraltete Soll-Allokation mit Ursache, "Umrechnung
offen" statt "keine Position", Verzehr-Kachel. clearStrategySummaryForDirtyState
ist in den Teil umgezogen; der Monolith schrumpft trotz Umlaut-/Textkorrekturen.
advisor-guidance.js, fx-rates-editor.js, ist-projection-basis.js gesenkt.
Kern-Integration Runde 2 (H-167, KN-B + KN-U): Stammdaten-Maske speichert einen
unberuehrten Horizont-Vorschlag nicht mehr (Save-Autofill ersetzt); Monolith
gemessen 26450 Z./1623866 B.
KN3-U Kernkette Runde 3 (Dok. 118 / H-167 R2, Classic-UI): neuer Teil ``kn3-ui.js``
(Budget = Stand bei Einfuehrung): gemeinsame Bandlogik, Betraege nach Kurs-/
Vermoegensaenderung, KYC-Formular, neues Mandat auffindbar, kein "veraltet" ohne
Strategie. Umgezogen: reviewBandVisualHtml (ares.html), aresTerm und Cashflow-HUD
(mandate-view.js). Alle betroffenen Budgets gesenkt bzw. gehalten (Monolith,
goal-review-runtime.js, client-compliance.js, mandate-view.js).
KN4-U Kernkette Runde 4 (Dok. 119 / H-172-Pruefung, Classic-UI): neuer Teil
``kn4-ui.js`` (Budget = Stand bei Einfuehrung): ein Reset fuer Kundenwechsel und
neues Mandat, eine Rundungsquelle je Zahl, Portfolio bei veralteter Strategie,
fehlendes Ist nicht bewertbar. normalizeCashflowProjectionLabels aus ares.html
umgezogen, reviewBandVisualHtml (ohne Aufrufer) aus kn3-ui.js entfernt. Budgets
gesenkt: Monolith, kn3-ui.js, aa-chart.js. Zusatz Pitch-Selbsttest (DEMO-B1/B2/B4): kn4-ui.js
245/13547 (Stand bei Einfuehrung inkl. Zusatz), finalize-attestation.js gesenkt auf 1741 B.
Kern-Integration R4 (N-917R3-08, H-176): aresSplitIs100 (Depot-/Vorsorge-Aufteilung = Serverregel)
nach kn4-ui.js statt in den Monolithen: kn4-ui.js 246/13742, Monolith gesenkt auf 1623083 B.
KN5 (H-176-Pruefung): neuer Teil ``kn5-ui.js`` (Budget = Stand bei Einfuehrung): Review mit
Reserve ausserhalb der Strategie (N-917R4-02; Label = PDF, +46 B nach N858-5), Hinweis ohne Apportionierung (N-917R4-05);
allocationReserveBreakdown aus ares.html umgezogen -> Monolith gesenkt auf 26418/1622457.
kn4-ui.js 250/14025: Toleranzschranke direkt in aresPortfolioDisplayPositions (N-917R4-05,
Korrektur der bestehenden Apportionierung, keine neue Funktion; Hinweis in kn5-ui.js).
H-179 L2/L3 Vertragsschicht (2026-11-21): neuer Teil ``owner-content.js`` (Budget = Stand
bei Einfuehrung, 298/18904); im Monolithen nur die Einbindung (+42 B, gleiche Zeile) und
der Vorgabe-Ort «Zürich» der Vertragsmaske entfernt (Ort = Pflichtfeld): 1622472 B.
"""
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
MONOLITH = REPO_ROOT / "ares-desktop" / "frontend" / "ares.html"

MONOLITH_MAX_LINES = 26418
TOLERANCE_LINES = 0
MONOLITH_MAX_BYTES = 1622472
TOLERANCE_BYTES = 0

# Ausgelagerte Teile: Dateiname -> (max. Zeilen, max. Bytes LF-normalisiert).
EXTRACTED_PART_BUDGETS = {
    "ares.css": (1143, 90070),
    "aa-chart.css": (66, 5978),
    "intro-sequence.js": (761, 36861),
    "aa-chart.js": (316, 20608),
    "ist-projection-gate.js": (288, 15951),
    "session-boundary.js": (53, 2763),
    "ist-projection-basis.js": (87, 4627),
    "unsaved-changes.js": (82, 4342),
    "goal-review-runtime.js": (1563, 83881),
    "client-compliance.js": (469, 29962),
    "kyc-review-policy.js": (427, 25832),
    "owner-content.js": (298, 18904),
    "privacy-governance.js": (500, 35256),
    "sustainability-preferences.js": (517, 26065),
    "wealth-inflows.js": (282, 16491),
    "allocation-publication.js": (272, 13780),
    "finalize-attestation.js": (27, 1741),
    "fx-rates-editor.js": (97, 5091),
    "mandate-view.js": (604, 35395),
    "kn3-ui.js": (259, 14886),
    "kn4-ui.js": (250, 14025),
    "kn5-ui.js": (105, 6960),
    "advisor-guidance.js": (728, 43963),
}


def _line_count(path: Path) -> int:
    return len(path.read_bytes().splitlines())


def test_monolith_does_not_grow_beyond_budget():
    actual = _line_count(MONOLITH)
    assert actual <= MONOLITH_MAX_LINES + TOLERANCE_LINES, (
        f"Monolith hat {actual} Zeilen, Budget {MONOLITH_MAX_LINES} (Toleranz "
        f"{TOLERANCE_LINES}). Logik auslagern statt den Monolithen zu vergroessern."
    )


def _byte_count(path: Path) -> int:
    return len(path.read_bytes().replace(b"\r\n", b"\n"))


def test_monolith_does_not_grow_beyond_byte_budget():
    actual = _byte_count(MONOLITH)
    assert actual <= MONOLITH_MAX_BYTES + TOLERANCE_BYTES, (
        f"Monolith hat {actual} Bytes, Budget {MONOLITH_MAX_BYTES} (Toleranz "
        f"{TOLERANCE_BYTES}). Logik auslagern statt an bestehende Zeilen anzuhaengen."
    )


def test_byte_budget_counts_appended_code_on_existing_lines(tmp_path):
    """Gegenprobe im Kleinen: gleiche Zeilenzahl, mehr Bytes -> erkannt."""
    base = tmp_path / "m.html"
    base.write_bytes(b"a\nb\n")
    grown = tmp_path / "g.html"
    grown.write_bytes(b"a; extra()\nb\n")
    assert _line_count(base) == _line_count(grown)
    assert _byte_count(grown) > _byte_count(base)
    crlf = tmp_path / "c.html"
    crlf.write_bytes(b"a\r\nb\r\n")
    assert _byte_count(crlf) == _byte_count(base)


def test_budget_has_no_tolerance():
    assert TOLERANCE_LINES == 0
    assert TOLERANCE_BYTES == 0


def test_extracted_parts_do_not_grow_beyond_budget():
    from tests.monolith_source import EXTRACTED_PARTS

    assert {name for name, _kind in EXTRACTED_PARTS} == set(EXTRACTED_PART_BUDGETS)
    for name, (max_lines, max_bytes) in EXTRACTED_PART_BUDGETS.items():
        path = MONOLITH.parent / name
        lines, size = _line_count(path), _byte_count(path)
        assert lines <= max_lines + TOLERANCE_LINES, (
            f"{name} hat {lines} Zeilen, Budget {max_lines}. Neue Logik in eigene Module."
        )
        assert size <= max_bytes + TOLERANCE_BYTES, (
            f"{name} hat {size} Bytes, Budget {max_bytes}. Neue Logik in eigene Module."
        )
