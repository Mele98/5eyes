-- U-FINMA-2.1 (2026-05-28): AdvisoryLog FINMA-Erweiterung
--
-- Adressiert FIDLEG Art. 16 + 17 und FINMA-Audit-Pflicht für
-- Beratungsprotokolle. 18 neue Spalten + Indexe.
--
-- Strategie: alle neuen Spalten nullable mit defensiven Defaults.
-- Bestehende AdvisoryLog-Einträge bleiben gültig (kein Daten-Verlust).
--
-- Berechnete Felder (integrity_hash, retain_until) bleiben fuer Alt-
-- Eintraege NULL — das ist FINMA-konform: alte Eintraege wurden vor der
-- Hash-Pflicht erstellt; ein Backfill waere kein echter Audit-Marker.

-- Zeit + Dauer
ALTER TABLE advisory_log ADD COLUMN entry_datetime TEXT;
ALTER TABLE advisory_log ADD COLUMN duration_minutes INTEGER;

-- Kommunikationskanal
ALTER TABLE advisory_log ADD COLUMN communication_channel TEXT;

-- Sprache + Ort
ALTER TABLE advisory_log ADD COLUMN language TEXT;
ALTER TABLE advisory_log ADD COLUMN location TEXT;

-- Strukturierte JSON-Listen
ALTER TABLE advisory_log ADD COLUMN participants_json TEXT;
ALTER TABLE advisory_log ADD COLUMN topics_json TEXT;
ALTER TABLE advisory_log ADD COLUMN risk_warnings_given_json TEXT;
ALTER TABLE advisory_log ADD COLUMN conflict_disclosure_ids_json TEXT;

-- Boolean: Ex-ante Kosten kommuniziert
ALTER TABLE advisory_log ADD COLUMN cost_disclosure_given INTEGER NOT NULL DEFAULT 0;

-- FK zur Eignungsprüfung (nullable)
ALTER TABLE advisory_log ADD COLUMN suitability_check_id TEXT REFERENCES suitability_checks(id) ON UPDATE CASCADE;

-- Integritäts-Hash
ALTER TABLE advisory_log ADD COLUMN integrity_hash TEXT;

-- Aufbewahrungs-Datum (= entry_datetime + 10 Jahre)
ALTER TABLE advisory_log ADD COLUMN retain_until TEXT;

-- Versions-Geschichte
ALTER TABLE advisory_log ADD COLUMN version INTEGER NOT NULL DEFAULT 1;
ALTER TABLE advisory_log ADD COLUMN supersedes_id TEXT REFERENCES advisory_log(id);
ALTER TABLE advisory_log ADD COLUMN superseded_by_id TEXT REFERENCES advisory_log(id);

-- Read-Audit
ALTER TABLE advisory_log ADD COLUMN last_read_at TEXT;
ALTER TABLE advisory_log ADD COLUMN last_read_by TEXT REFERENCES users(id);

-- Indexe für gängige Queries
CREATE INDEX IF NOT EXISTS idx_advisory_log_active ON advisory_log(mandate_id, superseded_by_id);
CREATE INDEX IF NOT EXISTS idx_advisory_log_retain ON advisory_log(retain_until);
CREATE INDEX IF NOT EXISTS idx_advisory_log_suitability ON advisory_log(suitability_check_id);
