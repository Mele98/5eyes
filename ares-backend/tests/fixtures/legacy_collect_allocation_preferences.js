// Eingefrorene Referenz: collectAllocationPreferencesFromUI() von origin/develop 9c9b375
// VOR STRATEGY-BLOCKS-PANEL-001 (alter Praeferenzen-Dialog mit separaten Checkboxen).
// Nur fuer test_frontend_strategy_blocks_panel.py (Payload-Gleichheit), nicht produktiv.
function legacyCollectAllocationPreferencesFromUI(){
  var stored=loadAllocationPreferences();
  var prefs=mergeAllocationPreferences(buildDefaultAllocationPreferences(),stored);
  var live={
    policy:{
      // Sprint U-P0 Fix H1-H3: Defaults auf wirkende Werte (waren vorher
      // "esg_integration"/"standard" die nichts taten â€” irrefÃ¼hrend).
      esg:getInputValue('aa-policy-esg')||'none',
      universe:getInputValue('aa-policy-universe')||'funds_only',
      homeBias:getInputValue('aa-policy-home-bias')||'ch_focus',
      hedging:getInputValue('aa-policy-hedging')||'none',
    },
    tilts:{
      fossil:getInputValue('aa-tilt-fossil')||'neutral',
      defense:getInputValue('aa-tilt-defense')||'neutral',
      tobacco:getInputValue('aa-tilt-tobacco')||'neutral',
      alcohol:getInputValue('aa-tilt-alcohol')||'neutral',
      gaming:getInputValue('aa-tilt-gaming')||'neutral',
      nuclear:getInputValue('aa-tilt-nuclear')||'neutral',
    },
    product:{
      noDerivatives:getCheckboxValue('aa-product-no-derivatives'),
      noLeverage:getCheckboxValue('aa-product-no-leverage'),
      noStructured:getCheckboxValue('aa-product-no-structured'),
      listedOnly:getCheckboxValue('aa-product-listed-only'),
      fundsOnly:getCheckboxValue('aa-product-funds-only'),
    },
    limits:{
      singlePosition:getInputValue('aa-limit-single-position'),
      singleIssuer:getInputValue('aa-limit-single-issuer'),
      minReserve:getInputValue('aa-liquidity-min-reserve'),
      maxIlliquid:getInputValue('aa-liquidity-max-illiquid'),
    },
    geo:{
      chFocus:(getInputValue('aa-policy-home-bias')||'ch_focus')==='ch_focus',
      noEm:getCheckboxValue('aa-geo-no-em'),
      hedgingRequired:getCheckboxValue('aa-geo-hedging-required'),
      chfOnly:getCheckboxValue('aa-geo-chf-only'),
      noUsd:getCheckboxValue('aa-geo-no-usd'),
    },
    simulation:{
      stressMultiplier:getInputValue('aa-sim-stress')||'1.0',
      rebalanceMode:getInputValue('aa-sim-rebalance')||'bands',
      monteCarloRuns:getInputValue('aa-sim-mc-runs')||'750',
    },
    assetClasses:{
      equitiesGeo:getRadioValue('aa-equities-geo','Schweiz Fokus'),
      equitiesLargeCap:getCheckboxValue('aa-equities-large-cap'),
      equitiesSmid:getCheckboxValue('aa-equities-smid'),
      bondsDuration:getRadioValue('aa-bonds-duration','Langfristig'),
      bondsInvestmentGrade:getCheckboxValue('aa-bonds-investment-grade'),
      bondsHighYield:getCheckboxValue('aa-bonds-high-yield'),
      bondsEmerging:getCheckboxValue('aa-bonds-emerging'),
      realestateMarket:getRadioValue('aa-realestate-market','Schweiz'),
      realestateFunds:getCheckboxValue('aa-realestate-funds'),
      realestateDirect:getCheckboxValue('aa-realestate-direct'),
      altsGold:getCheckboxValue('aa-alts-gold'),
      altsLiquidAlts:getCheckboxValue('aa-alts-liquid-alts'),
      altsHedge:getCheckboxValue('aa-alts-hedge'),
      altsPe:getCheckboxValue('aa-alts-pe'),
      altsCrypto:getCheckboxValue('aa-alts-crypto'),
      liquidityInstrument:getRadioValue('aa-liquidity-instrument','Geldmarktfonds'),
      liquidityReserveTarget:getInputValue('aa-liquidity-reserve-target'),
    },
  };
  // CH-Fokus hat nur EINE Quelle: policy.homeBias (Dropdown). geo.chFocus wird
  // daraus abgeleitet (siehe oben) und dient nur noch der Restriktions-Anzeige.
  // Der fruehere zweite Schalter (aa-geo-ch-focus Checkbox) ist entfernt, damit
  // sich Dropdown und Checkbox nicht mehr widersprechen koennen.
  prefs.policy=live.policy;
  prefs.tilts=live.tilts;
  // ESG-PREMIUM-CRITERIA-001: BegrÃ¼ndung je Thema nur senden, wenn sie zur
  // Wahl gehÃ¶rt ("Bewusst zulassen" Pflicht, Ãœbergewichten optional) --
  // das Backend validiert die QualitÃ¤t (FIDLEG Art. 13).
  prefs.tiltReasons=collectTiltReasonsFromUI(live.tilts);
  prefs.product=live.product;
  prefs.limits=live.limits;
  prefs.geo=live.geo;
  // SIM-HORIZON-FROM-RISK-PROFILE-001: kein Prognose-Horizont in den Praeferenzen.
  stripLegacySimulationHorizon(live);
  prefs.simulation=live.simulation;
  prefs.assetClasses=live.assetClasses;
  var modal=document.getElementById('m-eq');
  var modalBands=(modal&&modal.classList.contains('open')&&hasCanonicalBandBaseline())?collectBandOverridesFromModal():null;
  prefs.bands=modalBands==null?(prefs.bands||{}):modalBands;
  var reasonInput=document.getElementById('aa-band-deviation-reason');
  if(reasonInput)prefs.bandDeviationReason=String(reasonInput.value||'').trim();
  if(!prefs.bandDeviationReason)delete prefs.bandDeviationReason;
  return prefs;
}
