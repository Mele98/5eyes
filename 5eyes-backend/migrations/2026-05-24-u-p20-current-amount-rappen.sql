-- Sprint U-P20 (2026-05-24): current_amount_rappen Column für RecommendationPosition
--
-- Problem: services/depot_check.py liest seit Sprint U-P12 (2026-05-20)
-- via getattr(rec_pos, "current_amount_rappen", 0) — aber das Feld war
-- nie als DB-Column definiert. Resultat: depot_check sah immer IST=0
-- und fiel auf target_amount zurück → IST==SOLL → KEIN echter Drift
-- möglich (alle Drift-Werte = 0).
--
-- Fix: current_amount_rappen als nullable INTEGER Column hinzufügen.
-- NULL bedeutet "noch nicht gepflegt" (Empfehlung erstellt, Kunde hat
-- noch nichts gekauft). depot_check verwendet dann target_amount als
-- Approximation (= bestehendes Verhalten, backwards-compat).
--
-- Bezug: docs/planning/2026-05-24-sprint-u-p20-depot-check-soll-drift.md

ALTER TABLE recommendation_positions
  ADD COLUMN current_amount_rappen INTEGER
  CHECK(current_amount_rappen IS NULL OR current_amount_rappen >= 0);

-- Index nicht nötig: Column wird immer im Kontext von run_id gelesen,
-- bestehender idx_rec_positions_run reicht.

-- Pflegen kann der Berater entweder:
-- 1. Via PATCH /mandates/{id}/recommendation/positions/{pos_id}
--    (Endpoint muss separat ergänzt werden — out of Scope für U-P20)
-- 2. Beim "Empfehlung übernehmen"-Workflow setzen (= aktuell = target_amount).
-- 3. Manuell via Admin-DB-Tool.
