# Änderungsprotokoll Berater-Handbuch — Juli 2026

Ergänzt das [Berater-Handbuch](berater-handbuch.md) um die in der Woche vom
2026-07-19 bis 2026-07-23 gebauten Funktionen. Reihenfolge = Datum der Umsetzung.

## 2026-07-19 — Indexierungs-Schalter in der Cashflow-Projektion
Neuer Schalter **«Indexierung berücksichtigen»** über der IST-Kurve auf Seite 3
(Cashflows & Ziele). AN (Standard) rechnet inflationsgekoppelte Einnahmen und
Ausgaben über die Jahre gemäss Markt-Szenario hoch (reale Kaufkraftentwicklung);
AUS zeigt alles nominal (heutige Kaufkraft). Löst den früheren, rein optischen
Indexierungs-Umschalter ab — der neue Schalter berechnet die Projektion tatsächlich
im Hintergrund neu. Siehe Handbuch §1.3.

## 2026-07-19 — Eignungsprüfungs-Audit auf Mandatsebene (FIDLEG Art. 10/12)
Der Compliance-Audit im Advisory-Report prüft neu korrekt pro Mandat, ob ein
aktuelles (≤ 12 Monate altes) Risikoprofil vorliegt, statt — wie zuvor technisch
bedingt — immer «konform» zu melden. «Nicht konform» heisst: Risikoprofil fehlt
oder ist veraltet → mit dem Kunden neu durchgehen. Execution-only-Mandate sind
ausgenommen. Siehe Handbuch §7.

## 2026-07-19 — Signatur des Risikoprofils (Portal + Berater)
Die Eignungsprüfung (Risikoprofil) kann jetzt als vom Kunden zur Kenntnis
genommen signiert werden — durch den Kunden selbst im Kunden-Portal oder durch
den Berater über «Signatur erfassen» in der Review-Zusammenfassung. Die
Risikoprofil-Karte zeigt Datum + Weg der Signatur («Portal» / «Berater») bzw.
«nicht signiert». Siehe Handbuch §1.4.

## 2026-07-20 — Kostenausweis Ex-ante durchgängig im Advisory-Report
Der Ex-ante-Kostenausweis (FIDLEG Art. 8/9) ist nicht mehr nur eine eigenständige
PDF-Sektion, sondern Teil des zentralen Advisory-Report-Datenmodells — dieselben
Kostenzahlen erscheinen konsistent in PDF und Online-Ansicht. Siehe Handbuch §7.

## 2026-07-22 — Anklickbares PDF-Inhaltsverzeichnis
Die Inhaltsverzeichnisse in den PDF-Berichten sind jetzt anklickbar (Sprung zum
Abschnitt) und die Berichte haben ein Lesezeichen-/Outline-Menü im PDF-Viewer.
Siehe Handbuch §7.

## 2026-07-23 — Reserve-Erklärbarkeit im Advisory-Report
Neuer Report-Abschnitt zeigt, warum die SOLL-Allokation eine Liquiditätsreserve
ausweist (kurzfristiger Cashflow-Bedarf, nahe Ziele, manuelle Vorgabe) und ob ein
Teil davon als externe Reserve ausserhalb des Mandats empfohlen wird. Reine
Herleitung der bei der letzten Strategie-Berechnung ermittelten Zahlen — keine
Neuberechnung im Report. Siehe Handbuch §2.

## 2026-07-23 — Dark Mode (Hauptapp)
Umschalter in der Kopfzeile für helle/dunkle Darstellung, inkl. Chart-Farben;
Einstellung wird pro Gerät gespeichert. Rein optisch. Siehe Handbuch §6.
