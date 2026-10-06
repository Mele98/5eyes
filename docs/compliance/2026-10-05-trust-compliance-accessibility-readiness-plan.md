# 5eyes Trust-, Compliance- und Accessibility-Readiness

**Stand:** 2026-10-05
**Status:** repository-basierte Ersttriage und umsetzbarer Backlog; keine
Rechtsfreigabe
**Produktkontext:** B2B-Beratersoftware fuer Schweizer Vermoegensberater
(Electron + FastAPI, optional Self-Hosted/Shared-Cloud/Dedicated)
**Owner fuer Abschlussfreigabe:** Geschaeftsleitung, Compliance/Recht,
Datenschutz, Security und Product gemeinsam

**Bestaetigte Scope-Entscheidung:** ausschliesslich **B2B**; vom Product Owner
am 2026-10-05 bestaetigt. B2C-spezifische Anforderungen sind nicht Bestandteil
des aktuellen Zielprodukts und werden nur als Re-Evaluation-Trigger gefuehrt.

> Dieses Dokument ist keine Rechtsberatung. Rechtstexte, Rechtsgrundlagen,
> Aufbewahrungsfristen und regulatorische Einordnung muessen vor Echtdatenbetrieb
> durch qualifizierte Schweizer Fachpersonen sowie fuer jedes weitere Zielland
> separat freigegeben werden.

## 1. Kurzurteil

Die vorgeschlagenen Punkte sind richtig, aber nicht alle sind fuer 5eyes gleich
anzuwenden. 5eyes ist derzeit keine generische Consumer-Webseite, sondern eine
Beratungssoftware mit sensiblen Finanz-, Familien-, Vorsorge- und Profildaten.
Deshalb sind technisch belegte Datenlebenszyklen, FIDLEG-Nachweise,
Auftragsbearbeitung, Security und barrierefreie Kernworkflows hoeher zu
priorisieren als ein pauschaler Cookie-Banner oder ein allgemeines
Rueckerstattungsformular.

Der Repository-Stand zeigt bereits:

- DSFA- und AVV-Vorlagen existieren, sind aber nicht final freigegeben; die DSFA
  bezeichnet sich selbst als Release-Blocker.
- Der Datenlebenszyklus-Audit dokumentiert offene P1-Vertraege fuer
  Betroffenenexport, Loeschung, Retention, Tenant-/User-Offboarding,
  Restore-nach-Loeschung und Notice-/Rechtsgrundlagennachweis.
- Telemetrie ist standardmaessig aus und technisch opt-in; ein versionierter
  mandanten-/nutzerbezogener Consent- und Vendor-Nachweis ist damit noch nicht
  hergestellt.
- Die Anwendung verschickt aktuell Einladungs- und Passwort-Reset-E-Mails,
  jedoch keine im Code erkennbare Newsletter-/Marketingkommunikation.
- Es gibt bereits einzelne ARIA-Attribute und Accessibility-Tests. Gleichzeitig
  existieren klickbare `div`-Elemente ohne native Tastatursemantik; WCAG-2.2-AA-
  Konformitaet ist daher nicht belegt.
- Gebuendelte Schriften und Bilder sind vorhanden, aber kein zentrales
  `THIRD_PARTY_NOTICES`-/Asset-Provenienzregister wurde gefunden. Das
  Electron-Paket ist als `UNLICENSED` markiert; das ersetzt keine
  Drittanbieter-Lizenznachweise.
- Ein Kundenreview-/Bewertungssystem und ein oeffentlicher Checkout wurden im
  Produktcode nicht gefunden. Fake-Review- und Refund-Kontrollen sind daher
  vorerst Governance- beziehungsweise Vertriebskontrollen, keine primaeren
  App-Features.

## 2. Prioritaetsmodell

| Stufe | Bedeutung |
|---|---|
| **P0** | Vor produktivem Echtdatenbetrieb oder verbindlichem Verkauf entscheiden beziehungsweise schliessen |
| **P1** | Vor breitem Rollout; hoher Vertrauens-, Rechts-, Finanz- oder Accessibility-Hebel |
| **P2** | Bedingt durch Vertriebskanal, Marketing, B2C, EU-Bezug oder spaetere Funktionen |
| **N/A bis Trigger** | Nicht implementieren, bevor der genannte Trigger tatsaechlich eintritt |

### B2B-Fokusfilter: investieren, beobachten oder bewusst nicht bauen

Dieser Filter verhindert, dass eine generische Website-Checkliste unnoetige
Produktkomplexitaet erzeugt. Jede neue Compliance-Idee muss zuerst durch diese
drei Klassen:

| Klasse | Entscheidung fuer den aktuellen B2B-Scope | Themen |
|---|---|---|
| **Jetzt investieren** | Release- und Vertrauensgrundlage | B2B-AGB/Lizenz/SLA/Exit, Datenschutzinformation, DSFA, AVV/Subprocessor, Datenfluss, DSAR, Retention/Legal Hold, Loeschung/Offboarding, Restore-Erasure, FIDLEG-/Kosten-/Claim-Evidence, Incident Response, Accessibility der Kernworkflows/PDFs, Vendor-/Lizenz-/SBOM-Nachweise, Pentest und Modellgovernance |
| **Inventarisieren und technisch vorbereitet halten** | Nur aktivieren, wenn ein realer Zweck und eine freigegebene Rechtsgrundlage bestehen | Telemetrie, optionale SDKs, Local-/Session-Storage, Marketingkommunikation, externe Webanalyse, EU-Daten, Open-Banking-Anbindungen und Payment-Funktionen |
| **Aktuell nicht bauen** | Kein nachgewiesener Nutzen im bestaetigten Scope | pauschaler Cookie-Banner ohne optionale Tracker, Consumer-Widerrufsflow, Kinder-Consumer-Accounts/Altersverifikation, Review-/Testimonial-Plattform, Newsletter-Abmeldung ohne Newsletter sowie PCI-/PSD2-/DORA-Implementierungen ohne fachlichen Trigger |

### Die zwoelf B2B-Arbeitspakete mit dem hoechsten Hebel

Die vierzig Detailkontrollen unten bleiben das vollstaendige Register. Fuer
Steuerung und Umsetzung werden sie jedoch in zwoelf lieferbare Pakete gebuendelt:

| Reihenfolge | Arbeitspaket | Gebuendelte Kontrollen | Messbares Ergebnis |
|---:|---|---|---|
| 1 | Betriebs- und Regulierungsmodell | `TRUST-01`, `ASSURE-06` | Rechtseinheit, Rolle, Kundentyp, Land und Hosting-Tier sind pro Angebot eindeutig; unzulaessige Kombinationen koennen nicht verkauft oder aktiviert werden. |
| 2 | Dateninventar und Privacy Architecture | `TRUST-03`, `TRUST-06`, `TRUST-11` | Jede Datenart und ausgehende Verbindung besitzt Zweck, Owner, Speicherort, Empfaenger, Land, Retention und Loeschpfad; unbekannte Flows sind null. |
| 3 | Datenschutz-Freigabepaket | `TRUST-02`, `TRUST-04`, `TRUST-05` | Notice, DSFA, AVV und Subprocessor-Register stimmen mit der technischen Datenflusskarte und jedem Hosting-Tier ueberein. |
| 4 | Betroffenen- und Offboarding-Lifecycle | `TRUST-07`, `TRUST-08`, `TRUST-09` | Vollstaendiger Export, Berichtigung, Legal Hold, Loeschung/Anonymisierung, Tenant-Exit und Restore-Erasure sind End-to-End und fail-closed getestet. |
| 5 | B2B-Vertrags- und Verkaufsstrecke | `FAIR-01`, `FAIR-02`, `FAIR-03`, `FAIR-09` | Angebot, AGB/Lizenz, SLA, Preis, Laufzeit, Kuendigung, Exit, Anbieterangaben und Beschwerdeweg sind konsistent, versioniert und nachweisbar angenommen. |
| 6 | Finanzberatungs- und Kosten-Evidence | `FAIR-05`, `FAIR-08`, `ASSURE-08` | Eignung, Ziele, Modelle, Empfehlung, Kosten, Konflikte und menschliche Freigabe bilden eine unveraenderliche, reproduzierbare und kanalgleiche Kundenakte. |
| 7 | Claim- und Fairness-Governance | `FAIR-04`, `FAIR-07` | Jede starke Rechts-, Sicherheits-, Performance- oder Nachhaltigkeitsaussage besitzt Evidenz und Ablaufdatum; Dark Patterns und Garantiesprache werden vor Release blockiert. |
| 8 | Accessibility des Golden Path | `A11Y-01` bis `A11Y-08` | Login bis signierter Kundenreport funktioniert per Tastatur und Screenreader, bei 200 Prozent Zoom und ohne reine Farbsemantik; PDF-Zugaenglichkeit ist separat belegt. |
| 9 | Drittanbieter- und Lizenzkette | `ASSURE-01`, `ASSURE-02`, `ASSURE-03` | Vendor-Register, Subprocessor-Abgleich, Asset-Provenienz, Third-Party Notices und releasebezogene SBOM sind vollstaendig und CI-geprueft. |
| 10 | Security Assurance | `ASSURE-04`, `ASSURE-07` | Threat Model, sichere Build-/Releasekette, Pentest plus Re-Test und ein ehrliches Kunden-Security-Paket ohne unbelegte Zertifizierungsclaims liegen vor. |
| 11 | Resilienz und Datenschutzvorfaelle | `TRUST-14`, `ASSURE-05` | RTO/RPO, Restore-Drill, Ransomware-/Vendor-/Datenleck-Szenarien, Meldeentscheid und Kommunikationswege wurden praktisch geuebt. |
| 12 | Bedingte Zukunftsfunktionen | `TRUST-10`, `TRUST-12`, `TRUST-13`, `FAIR-06`, `FAIR-10` | Triggerregister verhindert, dass B2C-, Marketing-, Tracking-, Review- oder Kinderdatenfunktionen ohne erneute Scope-, Rechts- und Produktfreigabe aktiviert werden. |

## 3. Bereinigter Backlog

### A. Rechtsgrundlage, Transparenz und Datenrechte

| ID | Thema | Prio | 5eyes-Einordnung und aktueller Stand | Abnahmekriterium |
|---|---|---:|---|---|
| `TRUST-01` | Betriebs-, Rollen- und Jurisdiktionsmatrix | P0 | **B2B ist bestaetigt.** Offen bleiben Betreiber-Rechtseinheit, T1/T2/T3, Verantwortlicher/Auftragsbearbeiter, Ziellaender, regulatorischer Status der Firmenkunden und ob 5eyes selbst Finanzdienstleistungen erbringt oder ausschliesslich Software liefert. | Signierte Matrix je Vertriebs-/Hostingmodell; jeder nachfolgende Text verweist auf eine freigegebene Variante; B2C-Aktivierung erzwingt vorab eine neue Rechts- und Produktpruefung. |
| `TRUST-02` | Datenschutzerklaerung / Privacy Notice | P0 | Eine produktfertige, versionierte Notice wurde nicht gefunden. AVV/DSFA ersetzen die Information der betroffenen Person nicht. | Identitaet/Kontakt des Verantwortlichen, Zwecke, Datenkategorien, Empfaenger/Auftragsbearbeiter, Auslandbekanntgaben/Garantien, Dauer/Kriterien, Rechte, automatisierte Entscheidungen, Beschwerde-/Kontaktweg; Version und Zustellnachweis je betroffener Person. |
| `TRUST-03` | Bearbeitungsverzeichnis und Datenflusskarte | P0 | `CLIENT_DATA_STORAGE_AND_PROCESSING.md` ist ein guter technischer Start, aber kein vollstaendiges, owner-geprueftes Verzeichnis. | Jede Datenkategorie ist Quelle, Zweck, Rechtsgrundlage, System, Empfaenger, Land, Schutzklasse, Owner, Retention, Loeschpfad und DSAR-Exportsektion zugeordnet. |
| `TRUST-04` | DSFA finalisieren | P0 | `docs/compliance/dsfa-datenschutz-folgenabschaetzung.md` ist ausdruecklich eine unausgefuellte Release-Blocker-Vorlage. | Reale Verarbeitung, Risiko, Massnahmen, Restrisiko, Owner-/DPO-Entscheid und Reviewdatum ausgefuellt; bei verbleibendem hohem Risiko formelle Eskalation/Konsultation geprueft. |
| `TRUST-05` | AVV/DPA, Unterauftragsbearbeiter und Auslandtransfers | P0 fuer T2/T3 | AVV-Vorlage existiert. Konkrete Anbieter, Vertragsversionen, Subprocessor-Register, Standorte und Transfergarantien muessen je Hostingmodell gebunden werden. | Unterzeichnete AVV-Variante; versioniertes Subprocessor-Register; Aenderungsprozess; technische Vendor-Liste stimmt mit Vertrag und Notice ueberein. |
| `TRUST-06` | Datenminimierung und Privacy by Default | P0 | Die DSFA nennt Datenminimierung, aber das ist noch kein feldweiser Nachweis. Finanz-/Familien-/Vorsorgedaten erfordern besonders strikte Zweckbindung. | Feldregister mit `required/optional/prohibited`, Zweck und Aufbewahrung; optionale Felder standardmaessig leer; Telemetrie/Analytics standardmaessig aus; regelmaessiger Datenminimierungs-Test. |
| `TRUST-07` | Betroffenenrechte / DSAR / Portabilitaet | P0 | Der vorhandene Audit `PRIV-002` belegt einen unvollstaendigen und fail-soft Export. | Authentifizierter Prozess fuer Auskunft, Berichtigung, Export und Status; vollstaendiges versioniertes Exportmanifest; fehlende Pflichtsektion blockiert `complete`; sichere Zustellung und Auditnachweis. |
| `TRUST-08` | Loeschung, Anonymisierung und Offboarding | P0 | `PRIV-001`, `PRIV-004` und `PRIV-005` sind offen: Tombstone reicht nicht, Tenant/User-Offboarding fehlt, alte Backups koennen Daten reaktivieren. | Zustandsmodell `active -> closing/legal_hold -> erased/anonymized`; alle Kinddaten klassifiziert; Sessions gesperrt; externes Erasure-Ledger; Restore-Reconciliation; Loeschbestaetigung. |
| `TRUST-09` | Retention und Legal Hold | P0 | Dokumentierte zehn Jahre und physische 90-Tage-Loeschung widersprechen sich laut `PRIV-003`; Audit-/Signatur-/Browserdaten besitzen keinen vollstaendigen ausfuehrbaren Vertrag. | Freigegebene Retention-Matrix je Artefakt und Jurisdiktion; `retain_until`, Legal Hold, automatische Jobs, Dry Run, Vier-Augen-Freigabe und zeitgesteuerte Tests. |
| `TRUST-10` | Einwilligung und Widerruf | P1/bedingt | Consent ist nicht pauschal die Rechtsgrundlage fuer alles. Er ist nur fuer den konkreten optionalen Zweck zu verwenden. Ein Konfigurationsflag fuer Telemetrie ist kein Betroffenen-Nachweis. | Zweckgebundene, freiwillige, granulare Zustimmung nur wo erforderlich; Notice-Version, Zeitpunkt, Quelle und Actor gespeichert; Widerruf so einfach wie Erteilung; Kernservice nicht unnoetig gekoppelt. |
| `TRUST-11` | Cookie-/Local-Storage-/SDK-Inventar | P1 | Electron, Reporting-Subapp, Session Storage, Local Storage, Telemetrie und spaetere Website getrennt inventarisieren. | Maschinenlesbare Liste jeder Client-Speicherung/ID/SDK-Verbindung mit Zweck, Laufzeit, Empfaenger und Notwendigkeit; Netzwerk-Mitschnitt bestaetigt Vollstaendigkeit. |
| `TRUST-12` | Cookie-/Consent-Banner | P2/bedingt | Kein Banner allein aus Vorsicht bauen. Fuer ausschliesslich notwendige Technik kann eine transparente Notice genuegen; fuer optionale Tracker/Marketing gilt vorheriges Blockieren nach anwendbarem Recht. | Banner erscheint nur in betroffenen Weboberflaechen; `Ablehnen` gleichwertig zu `Akzeptieren`; keine vorangekreuzten Optionen; optionale Requests vor Zustimmung technisch null; Widerruf persistent erreichbar. |
| `TRUST-13` | Minderjaehrigen-/Kinderdaten-Policy | P1 fuer Datenmodell, B2C-Consent N/A | B2B ist bestaetigt; 5eyes richtet daher keine Consumer-Accounts direkt an Kinder. Haushalts-, Nachkommens- oder Beguenstigtendaten koennen dennoch Personendaten Minderjaehriger enthalten. | Direkte Minderjaehrigen-Consumer-Accounts sind im aktuellen Scope ausgeschlossen; Kinderdaten im Beratungsmandat sind zweckgebunden, minimal, rollenbeschraenkt und ohne Profilierung/Marketing; jede spaetere B2C-Oeffnung loest eine neue Alters-/Consent-Pruefung aus. |
| `TRUST-14` | Datenschutzverletzungsprozess | P0 | Technische Security-Dokumente existieren; benoetigt wird ein operativ geuebter DSG-/Kunden-/FINMA-Eskalationsprozess. | 24/7 Intake, Triage, Risikoentscheidung, Beweissicherung, Rollen/Rufnummern, EDÖB-/Betroffenen-/Kundenmeldung, Fristen, Vorlagen und mindestens jaehrlicher Tabletop-Test. |

### B. Vertrag, Verkauf und faire Produktpraxis

| ID | Thema | Prio | 5eyes-Einordnung und aktueller Stand | Abnahmekriterium |
|---|---|---:|---|---|
| `FAIR-01` | Terms of Service / AGB und Lizenzvertrag | P0 vor Verkauf | Produktlizenz, erlaubte Nutzung, Support/SLA, Verfuegbarkeit, Haftung, Datenrollen, Exit, Updates, Laufzeit und Kuendigung sind vom Datenschutztext zu trennen. | Rechtsgepruefte B2B-Vertragsvariante je Hostingmodell; akzeptierte Version und Vertretungsbefugnis nachweisbar; keine widerspruechlichen In-App-/Vertragsaussagen. |
| `FAIR-02` | B2B-Preis-, Kuendigungs- und Refund-Policy | P1 vor Verkauf | Kein Consumer-Checkout ist Teil des bestaetigten B2B-Scopes. Preis, Laufzeit, Verlaengerung, Kuendigung, Service Credits und Erstattung muessen dennoch im Firmenvertrag transparent und technisch konsistent sein. | Gesamtpreis und nicht optionale Kosten vor Vertrag; klare Trial-/Renewal-/Kuendigungslogik; B2B-Refund-/No-Refund- und Service-Credit-Regel; technisch und vertraglich identisch; B2C/EU-Vertrieb bleibt bis separater Freigabe gesperrt. |
| `FAIR-03` | Geschaeftsangaben / Anbieterkennzeichnung | P0 fuer Onlineangebot | Eine oeffentliche Anbieterkennzeichnung wurde nicht gefunden. Platzhalter duerfen nicht produktiv bleiben. | Firma, Rechtsform, ladungsfaehige Anschrift, gueltige E-Mail, Telefon falls vorgesehen, Handelsregister/UID/MWST soweit zutreffend, verantwortliche Kontaktstellen; auf Website, Vertrag, App-Hilfe und Rechnungen konsistent. |
| `FAIR-04` | Dark-Pattern-Verbot | P1 | Gilt fuer Kauf, Consent, Onboarding, Defaults, Ziel-/Risikofragen und Loeschung. Finanzberatung erfordert besonders neutrale Entscheidungssprache. | UX-Heuristik und Tests: keine asymmetrischen Buttons, Schuld-/Drucksprache, irrefuehrenden Defaults, versteckten Optionen oder kuenstliche Dringlichkeit; Abbruch, Ablehnung und Rueckkehr funktionieren. |
| `FAIR-05` | Keine versteckten Gebuehren / Kostenparitaet | P0 fachlich | Der bestehende Kosten-/Interessenkonflikt-Audit dokumentiert offene P1-Vertraege fuer immutable Kostensnapshots, TER/Fee-Basis, Retrozessionen, Konflikte und PDF/API/UI-Paritaet. | Gesamt- und Einzelkosten, Basis, Periode, Waehrung, TER, Drittentschaedigungen und Konflikte aus demselben signierten Snapshot; keine stillen Nullwerte; API/UI/PDF/Vertrag golden-testgleich. |
| `FAIR-06` | Reviews und Testimonials | N/A bis Nutzung | Im Produkt wurde kein Kundenbewertungssystem gefunden. Keine Funktion bauen, solange keine Reviews angezeigt werden. Marketing darf spaeter nur echte, belegte, nicht selektiv irrefuehrende Testimonials nutzen. | Provenienz, Einwilligung zur Veroeffentlichung, Beziehung/Anreiz, Moderationsregeln und unverfaelschte Negativbewertungen nachweisbar; synthetische/AI-Reviews klar ausgeschlossen. |
| `FAIR-07` | Claim- und Disclaimer-Governance | P0 fachlich | Formulierungen wie `FINMA-konforme Eignungspruefung` sind als starke Rechts-/Konformitaetsbehauptung im Reporting-Frontend vorhanden. Disclaimer heilen keine objektiv unbelegte Behauptung. | Zentrales Claim-Register mit exaktem Text, Kanal, Evidenz, Owner, Jurisdiktion, Gueltigkeitsdatum und erlaubten Varianten; verbotene Superlative/Garantien CI-geprueft; Legal-/Compliance-Freigabe vor Publikation. |
| `FAIR-08` | FIDLEG-Verhaltenspflichten als End-to-End-Nachweis | P0 falls im Scope | Eignung/Angemessenheit, Kundensegment, Information, Dokumentation, Rechenschaft, Kosten, Drittentschaedigungen und Interessenkonflikte duerfen nicht nur einzelne UI-Sektionen sein. | Scope-Entscheid je Kunde/Funktion; versionierte Eingaben und Resultate; blockierende Gates wo erforderlich; dauerhafter Datentraeger; reproduzierbare Kundenakte; Fach-/Compliance-Signoff. |
| `FAIR-09` | Beschwerden und Streitbeilegung | P1 | In der Liste fehlte ein klarer Beschwerdeprozess. Abhaengig vom Finanzdienstleister-/B2B-Modell sind Ombudsstelle und regulatorische Hinweise fachlich zu pruefen. | Sichtbarer Kontakt, Ticket-/Fristenprozess, Eskalation, Unabhaengigkeit, Root-Cause-Analyse, Antwortvorlagen und regulatorisch korrekte Hinweise. |
| `FAIR-10` | Marketing-E-Mails und Abmeldung | P2/bedingt | Aktuell erkennbare Invite-/Reset-Mails sind transaktional; ein Unsubscribe-Link waere dort sachlich falsch. Sobald Newsletter/Marketing existiert, braucht es vorherige Rechtsgrundlagenpruefung und einfache Abmeldung. | Marketing und Transaktion technisch getrennt; Suppression List; ein Klick oder gleichwertig einfacher Opt-out; Absender/Betreff transparent; kein erneuter Versand nach Abmeldung ausser gesetzlich/vertraglich notwendige Nachrichten. |

### C. Accessibility und inklusive Bedienung

| ID | Thema | Prio | 5eyes-Einordnung und aktueller Stand | Abnahmekriterium |
|---|---|---:|---|---|
| `A11Y-01` | WCAG-2.2-AA-Baseline | P1 | Accessibility darf nicht auf Alt-Texte reduziert werden. Desktop-Webviews, Reporting-App und exportierte PDFs benoetigen getrennte Pruefprofile. | Freigegebene Accessibility Policy; automatisierte axe-/HTML-/Kontrast-Gates plus manueller Testplan; bekannte Ausnahmen mit Owner und Frist. |
| `A11Y-02` | Textalternativen und Charts | P1 | Fuer aussagekraeftige Grafiken braucht es nicht nur `alt`, sondern Name, Zusammenfassung, Daten-/Tabellenalternative und nicht-farbige Kodierung. Dekoratives bleibt verborgen. | Inventar aller Bilder, Canvas, SVG und Charts; Screenreader-Test; jede fachliche Grafik besitzt gleichwertige textuelle Aussage/Datenansicht. |
| `A11Y-03` | Farbkontrast und Farbe als Information | P1 | Helles/dunkles Theme, kleine Finanzlabels, Statusfarben und Diagramme pruefen. | WCAG-AA-Kontrast automatisiert und stichprobenweise gemessen; Text mindestens 4.5:1 beziehungsweise 3:1 bei grossem Text; UI-Komponenten/Fokus mindestens 3:1; Information nie nur per Farbe. |
| `A11Y-04` | Tastatur, Fokus und Semantik | P1 | Klickbare `div.qcb`-Elemente belegen ein konkretes Tastaturrisiko. Native Controls sind Eigenbau-Rollen vorzuziehen. | Alle Funktionen mit Tastatur; logische Tab-Reihenfolge; sichtbarer Fokus; keine Tastaturfalle; Dialog-Fokusmanagement; Skip-/Landmark-Struktur; automatisierte und manuelle Regressionstests. |
| `A11Y-05` | Formulare, Fehler und Statusmeldungen | P1 | Risiko-/Ziel-/Vermoegensformulare sind Kernprozesse und muessen Labels, Hilfe, Fehlerbezug und Statusansagen besitzen. | Programmatische Labels/Descriptions; Pflichtfelder erkennbar; Fehlerliste + Feldbezug; `aria-live` nur gezielt; Werte/Einheiten nicht nur im Placeholder. |
| `A11Y-06` | Zoom, Reflow, Motion und Zielgroesse | P1 | Finanzcockpits und dichte Tabellen sind besonders gefaehrdet. | 200-%-Zoom und schmale Viewports ohne Funktionsverlust; Textspacing; Reduced Motion; ausreichende Touch-/Klickziele; keine unersetzbare Drag-only-Interaktion. |
| `A11Y-07` | Barrierefreie PDFs | P1 | Kundenreports sind dauerhafte regulatorische Artefakte; visuell korrekte PDFs sind nicht automatisch zugreifbar. | Tags, Sprache, Lesereihenfolge, Ueberschriften, Tabellenheader, Alternativtexte, Linknamen und Kontrast geprueft; PDF/UA-Zielniveau bewusst festgelegt; menschlicher Screenreader-Test. |
| `A11Y-08` | Accessibility Statement und Feedbackkanal | P2 vor breitem Rollout | Transparenz ueber Zielniveau, bekannte Grenzen und Kontakt fehlt. | Veroeffentlichte Erklaerung mit Scope, Testdatum, bekannten Einschraenkungen und barrierefrei erreichbarem Feedback-/Supportweg. |

### D. Drittanbieter, Lizenzen, Security und „Banking Standard“

| ID | Thema | Prio | 5eyes-Einordnung und aktueller Stand | Abnahmekriterium |
|---|---|---:|---|---|
| `ASSURE-01` | Third-Party-SDK-/Vendor-Audit | P0 fuer Release | Abhaengigkeiten, Datenanbieter, SMTP, optionales Sentry, Update-Feed und Hosting muessen funktional, datenschutzrechtlich, sicherheitstechnisch und vertraglich bewertet werden. | Owner-geprueftes Vendor-Register; Zweck/Daten/Land/Vertrag/SLA/Subprocessor/Exit; keine nicht inventarisierte ausgehende Verbindung; jaehrlicher Review und Aenderungsgate. |
| `ASSURE-02` | Software-, Font- und Bildlizenzen | P0 fuer Distribution | Inter- und Cormorant-Garamond-TTFs sowie zahlreiche Bilder sind gebuendelt; zentrale Provenienz-/Lizenzbelege fehlen. | `THIRD_PARTY_NOTICES`, SPDX/SBOM, Quelle/Version/Lizenz/Urheber/Attribution je Asset; Build enthaelt erforderliche Texte; unbekannte Assets entfernt oder ersetzt. |
| `ASSURE-03` | SBOM, Dependency- und Supply-Chain-Gates | P1 | Lockfiles und Pins existieren, aber Freigabe braucht reproduzierbare Artefakte und Schwachstellenprozess. | CycloneDX/SPDX-SBOM je Release; Hash/signierte Artefakte; SCA fuer Python/NPM/Electron; Severity-/SLA-Policy; Ausnahme mit Ablaufdatum; Herkunft und Build-Provenienz. |
| `ASSURE-04` | Secure SDLC und externe Pruefung | P0/P1 | `PENTEST_PREPARATION.md` existiert, der externe Test ist noch nicht beauftragt. | Threat Model, Security-Requirements, Code-/Dependency-/Secret-Scanning, externer Pentest vor breitem T2/T3-Rollout, Re-Test aller Critical/High, verantwortlicher Disclosure-Prozess. |
| `ASSURE-05` | Incident Response und Business Continuity | P0 | Finanzdatenplattformen brauchen nachweisbaren Restore und Kommunikationsfaehigkeit, nicht nur ein Runbook. | RTO/RPO je Service, verschluesselte/gepruefte Backups, Restore-Drills, Szenario fuer Ransomware/Vendor-Ausfall/Datenleck, Kunden-/Behoerdenkommunikation und Lessons Learned. |
| `ASSURE-06` | Banking-/Finanzstandard-Matrix | P0 Entscheidung | „Banking standard“ ist kein einzelner Standard. FINMA-RS 2023/1 gilt seinem Scope nach fuer bestimmte Institute, nicht automatisch fuer jeden Softwareanbieter. Kunden koennen Anforderungen jedoch vertraglich auf 5eyes herunterreichen. | Applicability Matrix fuer FIDLEG/FIDLEV, DSG/DSV, FINMA-Vorgaben je Kundentyp, GwG sofern relevant, ISO 27001/27017/27018, ISO 22301, SOC 2, OWASP ASVS; DORA/GDPR/PSD2/PCI DSS nur bei realem EU-/Payment-/Open-Banking-Trigger. |
| `ASSURE-07` | Security- und Datenschutz-Kontrollnachweise fuer Kunden | P1 | Institutionelle Kunden benoetigen Due-Diligence-Evidence. | Aktuelles Security Whitepaper, TOMs, Architektur-/Datenflussbild, Subprocessor-Liste, PenTest-Attest, DR-Nachweis, Vulnerability-SLAs, Verschluesselungs-/Key-Management- und Exitbeschreibung; keine unbelegten Zertifizierungsclaims. |
| `ASSURE-08` | Automatisierte Entscheidungen und Modelltransparenz | P0 fachlich | Monte Carlo, Risikoprofil und Optimierer beeinflussen Anlageentscheide. Datenschutzinformation allein reicht nicht; Modellgrenzen und menschliche Verantwortung muessen kanalgleich sein. | Version, Inputs, Annahmen, Unsicherheit, Grenzen, Override/Review, Erklaerung und menschliche Freigabe im Audit-/Kundenartefakt; keine stille automatische Finalisierung. |

## 4. Empfohlene Reihenfolge

### Phase 0 – verbindliche Entscheidungen

1. Auf Basis des bestaetigten B2B-Modells in `TRUST-01` noch Betreiber,
   Vertragsmodell, Hosting-Tier, Ziellaender und regulatorische Rolle festlegen.
2. Echtdaten-Go-live weiterhin sperren, solange die bereits dokumentierten
   P0/P1-Lifecycle-, Security-, Kosten- und Modellvertraege offen sind.
3. Schweizer Datenschutz-/Finanzmarktrecht-Fachperson und Security-Owner fuer
   die Freigaben benennen.

### Phase 1 – Trust Minimum Viable Release

1. Datenfluss-/Bearbeitungsverzeichnis, DSFA, AVV/Subprocessor-Register.
2. Privacy Notice, AGB/Lizenz, Anbieterkennzeichnung und
   Preis-/Kuendigungsmodell als miteinander konsistentes Set.
3. DSAR, Loeschung/Offboarding, Retention/Legal Hold und Restore-Erasure technisch
   schliessen.
4. FIDLEG-/Kosten-/Claim-Vertraege und kanalgleiche Evidence schliessen.
5. Incident-/Breach-Prozess und erster Tabletop-Test.

### Phase 2 – Accessibility, Fairness und Distribution

1. WCAG-2.2-AA-Baseline mit priorisiertem Kernworkflow:
   Login -> Kunde/Mandat -> Risikoprofil -> Ziele -> Asset Allocation -> Review
   -> PDF.
2. Tastatur-/Semantikfehler zuerst, danach Kontrast/Reflow/Charts/PDF.
3. Drittanbieter-/Asset-Lizenzen, SBOM und Vendor-Register vervollstaendigen.
4. Dark-Pattern- und Claim-Review fuer App, Website, Sales-Material und Reports.

### Phase 3 – bedingte Oberflaechen

Cookie-Banner, Marketing-Opt-out, B2C-Refund-Flow, Reviews und Altersverifikation
werden erst gebaut, wenn Website-/Marketing-/B2C-/Kinderdaten-Trigger tatsaechlich
feststehen. Vorher genuegen klare Policies und Architekturverbote; ungenutzte
Consent-Oberflaechen schaffen sonst Komplexitaet und koennen selbst irrefuehrend
sein.

## 5. Definition of Done fuer jeden Punkt

Ein Punkt ist nicht durch ein Dokument oder eine Checkbox allein geschlossen.
Erst alle sechs Ebenen muessen zusammenpassen:

1. **Scope und Rechtsgrundlage** wurden durch den zustaendigen Owner bestaetigt.
2. **Policy/Vertrag** ist versioniert, freigegeben und auffindbar.
3. **Produktverhalten** erzwingt die Regel oder blockiert fail-closed.
4. **Nachweis** bindet Actor, Zeit, Version, Gegenstand und Resultat.
5. **Tests** enthalten Positiv-, Negativ-, Rollen-, Tenant-, Replay- und
   Kanalparitaetsfaelle soweit relevant.
6. **Betrieb** besitzt Owner, Monitoring, Incident-/Ausnahmeprozess,
   Reviewintervall und Exit.

## 6. Interne Quellenkarte fuer Claude/GPT

Vor Umsetzung eines Arbeitspakets ist zuerst die dazugehoerige interne Evidenz
zu lesen. Diese Dokumente sind keine Rechtsfreigabe, verhindern aber, dass
bereits reproduzierte technische Luecken uebersehen oder doppelt erfunden
werden:

- Datenorte und Verarbeitung:
  [`CLIENT_DATA_STORAGE_AND_PROCESSING.md`](../CLIENT_DATA_STORAGE_AND_PROCESSING.md)
- DSFA-Release-Blocker-Vorlage:
  [`dsfa-datenschutz-folgenabschaetzung.md`](dsfa-datenschutz-folgenabschaetzung.md)
- AVV-/DPA-Grundlage:
  [`avv-template.md`](avv-template.md)
- Reproduzierte Datenlebenszyklus-, DSAR-, Retention-, Restore- und
  Consent-/Notice-Luecken:
  [`2026-08-26-data-lifecycle-crypto-browser-followup-audit.md`](../audits/2026-08-26-data-lifecycle-crypto-browser-followup-audit.md)
- Reproduzierte Kosten-, Retrozessions-, Konflikt- und Publikationsluecken:
  [`2026-09-02-ex-ante-cost-inducement-and-conflict-evidence-integrity-audit.md`](../audits/2026-09-02-ex-ante-cost-inducement-and-conflict-evidence-integrity-audit.md)
- Externer Security-Test-Scope und Vorbereitung:
  [`PENTEST_PREPARATION.md`](../PENTEST_PREPARATION.md)
- Accessibility-Negativ-/Regressionsnachweis fuer Charts:
  [`test_frontend_chart_accessibility.py`](../../5eyes-backend/tests/test_frontend_chart_accessibility.py)

## 7. Offizielle Primaerquellen fuer die Fachfreigabe

- Schweizer DSG, insbesondere Informationspflicht und Betroffenenrechte:
  [Fedlex – Datenschutzgesetz](https://www.fedlex.admin.ch/eli/cc/2022/491/de)
- EDÖB zur Informationspflicht:
  [Informationspflicht](https://www.edoeb.admin.ch/de/informationspflicht)
- EDÖB zu Auftragsbearbeitung:
  [Outsourcing/Auftragsdatenbearbeitung](https://www.edoeb.admin.ch/de/outsourcing-auftragsdatenbearbeitung)
- EDÖB zu Cookies und aehnlichen Technologien:
  [Aktualisierter Cookie-Leitfaden](https://www.edoeb.admin.ch/de/cookie-leitfaden-aktualisiert)
- EDÖB zu Datenschutzverletzungen:
  [FAQ Datenschutz](https://www.edoeb.admin.ch/de/faq-datenschutz)
- FINMA zu FIDLEG/FIDLEV und Verhaltenspflichten:
  [Finanzdienstleistungen](https://www.finma.ch/de/dokumentation/rechtsgrundlagen/gesetze-und-verordnungen/finanzdienstleistungen/)
- FINMA zu operationellen Risiken und Resilienz:
  [Rundschreiben 2023/1](https://www.finma.ch/de/~/media/finma/dokumente/dokumentencenter/myfinma/rundschreiben/finma-rs-2023-01-20221207.pdf)
- SECO zu Anbieterangaben und elektronischem Vertragsabschluss:
  [Onlinehandel](https://www.seco.admin.ch/de/onlinehandel)
- SECO zu Kauf, AGB und Widerruf:
  [Probleme nach dem Kauf](https://www.seco.admin.ch/de/probleme-nach-dem-kauf)
- W3C:
  [Web Content Accessibility Guidelines 2.2](https://www.w3.org/TR/WCAG22/)

## 8. Unmittelbar naechster Arbeitsauftrag

Vor der Implementierung gilt der
[B2B-Trust-/Compliance-Pre-Implementation-Coverage-Audit](../audits/2026-10-05-b2b-trust-compliance-pre-implementation-coverage-audit.md).
Er hat sechs fehlende Auditrunden und einen externen Owner-Facts-Block
identifiziert. Die Audits werden in der dort festgelegten Reihenfolge
geschlossen; danach wird die **Evidence-Matrix** erstellt:

1. jeden Eintrag dieses Backlogs gegen konkrete Code-, UI-, API-, PDF-,
   Deployment-, Vertrags- und Betriebsartefakte mappen;
2. fuer fehlende Evidenz kein `erfuellt`, sondern `offen`, `bedingt` oder
   `nicht anwendbar mit Begruendung` vergeben;
3. aus den P0-Punkten kleine, voneinander unabhaengige Claude-Arbeitspakete mit
   Abnahmetests bilden;
4. juristische Platzhalter klar als Platzhalter kennzeichnen und niemals
   automatisch als freigegebenen Rechtstext publizieren.
