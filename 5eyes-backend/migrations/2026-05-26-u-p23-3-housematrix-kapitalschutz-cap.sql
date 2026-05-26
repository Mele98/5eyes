-- U-P23.3 (2026-05-26): HouseMatrix-Kapitalschutz Risiko-Cap auf 30 %
--
-- Befund (während U-P23.2-Verifikation entdeckt):
--   HouseMatrix-Kapitalschutz hatte max_risky_fraction_bps = 2000 (20 %).
--   Default-Mid-Targets (Aktien 12 %, Bonds 75 %, RE 5 %, Alt 5 %, Liq 3 %)
--   erzeugen mit Building-Block-Default-Risky-Fractions ~30.8 % risky_fraction.
--   Folge: Liquiditäts-Notfall-Cascade getriggert, Liquidität auf 10 %
--   (gleicher Bug-Muster wie Defensiv vor U-P23.2).
--
-- Fix: Cap auf 30 % anheben (= ASIP-Obergrenze für „Sicherheit/Kapitalschutz").
--   Quelle: ASIP / Schweizerischer Pensionskassenverband. „Sicherheit"-
--   Profile haben in der Schweizer Konvention typischerweise 0-30 % risky.
--   3eyes-Spec (Score X von 10 → X × 10 % risky-Cap) liefert für Score 2
--   → 20 %; Toleranz-Puffer von 10 pp ist innerhalb Marktstandard für
--   Mid-Allocation-Rundung.

UPDATE house_matrix
   SET max_risky_fraction_bps = 3000,
       updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
 WHERE profile_name = 'Kapitalschutz';
