-- U-P23.2 (2026-05-26): HouseMatrix-Defensiv Risiko-Cap auf 45 %
--
-- Befund (Audit + Live-Test 2026-05-25):
--   HouseMatrix-Defensiv hatte max_risky_fraction_bps = 4000 (40 %).
--   Die Default-Mid-Targets (25 % Aktien / 60 % Bonds / 10 % RE / 3 % Alt /
--   2 % Liq) erzeugen mit den BuildingBlock-Risky-Fractions aber ~42 %
--   risky_fraction. Folge: Engine pumpt Liquidität auf 10 % um das Cap
--   zu treffen → Compliance-Verstoss + Cash-Drag.
--
-- Fix: Cap auf 45 % anheben (= ASIP-Obergrenze für „Defensiv"-Profile).
--   Wissenschaftliche Quelle: ASIP / Schweizerischer Pensionskassenverband
--   Konvention „Defensiv = 25–45 % risikobehaftete Anlagen". 3eyes-Spec
--   (Score X von 10 → X × 10 % risky) liefert für Score 4 → 40 %; ein
--   Toleranz-Puffer von 5 pp ist innerhalb Marktstandard.
--
-- Effekt: bei Defensiv-Mandaten (Score 3-4) landet die SAA jetzt mit
--   Liquidität 2-3 % (HM-Default), nicht mehr 10 %. Berater-Feedback
--   umgesetzt ohne defensiver zu werden.
--
-- Auditierbar: die HouseMatrix kann jederzeit weiter angepasst werden
--   (z.B. Aktien-Target senken oder BB-Risky-Fractions justieren).

UPDATE house_matrix
   SET max_risky_fraction_bps = 4500,
       updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
 WHERE profile_name = 'Defensiv';
