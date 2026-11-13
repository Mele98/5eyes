// G7 -- gemeinsamer Rundungsformatter (Policy "ares-rounding/1") fuer die
// Classic-App. Eigenstaendiges Modul (STANDALONE_FRONTEND_MODULES), klassisches
// Skript ohne Abhaengigkeiten; global als window.AresRounding, in Node via
// module.exports (Vertragstests).
//
// Derselbe Vertrag ist in ares-backend/core/presentation_rounding.py (PDF)
// und reporting/src/lib/presentationRounding.ts (React) umgesetzt; alle drei
// lesen in ihren Tests denselben Golden-Vektor
// ares-backend/core/presentation_rounding_golden.json.
//
// Kurzfassung: exakte Dezimalarithmetik (BigInt), ROUND_HALF_UP symmetrisch
// (+12.25 -> +12.3, -12.25 -> -12.3), kein toFixed/Math.round auf Anzeige-
// werten; Zahlen werden ueber String(n) (kuerzeste Round-trip-Darstellung)
// gelesen. Auf 0 gerundete Werte ohne Vorzeichen. Apostroph U+0027 als
// Tausendertrennung. Keine Angabe -> U+2014, 0 bleibt 0. Typografie "screen"
// (App): Minus U+2212, U+00A0 vor "%"; "plain" (PDF): "-" und U+0020.
// Summenerhaltung: Largest Remainder, Gleichstand in Eingabereihenfolge
// (= kanonische Reihenfolge des Aufrufers).
(function (root, factory) {
  var api = factory();
  if (typeof module === 'object' && module && module.exports) module.exports = api;
  if (root) root.AresRounding = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';
  var POLICY_VERSION = 'ares-rounding/1';
  var NO_VALUE = '—';
  var CANONICAL_ASSET_CLASS_ORDER = ['equities', 'bonds', 'real_estate', 'alternatives', 'liquidity'];
  var TYPO = {
    plain: { minus: '-', pctSep: ' ' },
    screen: { minus: '−', pctSep: ' ' }
  };
  var CURRENCY_EXPONENTS = { CHF: 2, EUR: 2, USD: 2, GBP: 2, SEK: 2, NOK: 2, DKK: 2, CAD: 2, AUD: 2, JPY: 0 };
  var NUM_RE = /^([+-]?)(\d*)(?:\.(\d*))?(?:e([+-]?\d+))?$/i;
  var TEN = BigInt(10);
  var ZERO = BigInt(0);
  var ONE = BigInt(1);
  var TWO = BigInt(2);

  function glyphs(t) {
    var g = TYPO[t || 'screen'];
    if (!g) throw new Error('unbekannte Typografie: ' + t);
    return g;
  }
  function pow10(n) { var r = ONE; for (var i = 0; i < n; i++) r *= TEN; return r; }

  // Wert -> {neg, coef(BigInt >= 0), exp} oder null (= keine Angabe).
  function toDecimal(value) {
    if (value === null || value === undefined || typeof value === 'boolean') return null;
    if (typeof value === 'bigint') return { neg: value < ZERO, coef: value < ZERO ? -value : value, exp: 0 };
    var s;
    if (typeof value === 'number') {
      if (!isFinite(value)) return null;
      s = String(value);
    } else if (typeof value === 'string') {
      s = value.trim();
      if (!s) return null;
    } else if (value && typeof value === 'object' && typeof value.coef === 'bigint') {
      return value;
    } else {
      var n = Number(value);
      if (!isFinite(n)) return null;
      s = String(n);
    }
    var m = NUM_RE.exec(s);
    if (!m || (m[2] === '' && (m[3] === undefined || m[3] === ''))) return null;
    var frac = m[3] || '';
    var coef = BigInt((m[2] || '0') + frac);
    return { neg: m[1] === '-' && coef !== ZERO, coef: coef, exp: (m[4] ? parseInt(m[4], 10) : 0) - frac.length };
  }
  function scale(d, k) { return { neg: d.neg, coef: d.coef, exp: d.exp + k }; }

  // Half-up (vom Nullpunkt weg) auf `decimals` -> {neg, units} mit Wert units*10^-decimals.
  function roundUnits(d, decimals) {
    var shift = d.exp + decimals, units;
    if (shift >= 0) units = d.coef * pow10(shift);
    else {
      var p = pow10(-shift), q = d.coef / p, r = d.coef % p;
      units = (TWO * r >= p) ? q + ONE : q;
    }
    return { neg: d.neg && units !== ZERO, units: units };
  }
  function group(intDigits) { return intDigits.replace(/\B(?=(\d{3})+(?!\d))/g, "'"); }
  function digits(units, decimals) {
    var s = units.toString();
    if (decimals <= 0) return group(s);
    while (s.length <= decimals) s = '0' + s;
    return group(s.slice(0, s.length - decimals)) + '.' + s.slice(s.length - decimals);
  }
  function dec(v) { return v == null ? 0 : Number(v); }

  function formatDecimal(value, decimals, opts) {
    opts = opts || {};
    var d = toDecimal(value);
    if (!d) return NO_VALUE;
    var n = dec(decimals), r = roundUnits(d, n), body = digits(r.units, n);
    if (r.neg) return glyphs(opts.typography).minus + body;
    if (opts.signed && r.units !== ZERO) return '+' + body;
    return body;
  }
  function formatPercent(valuePct, decimals, opts) {
    opts = opts || {};
    var core = formatDecimal(valuePct, decimals == null ? 1 : decimals, opts);
    return core === NO_VALUE ? core : core + glyphs(opts.typography).pctSep + '%';
  }
  function formatPercentBps(bps, decimals, opts) {
    var d = toDecimal(bps);
    if (!d) return NO_VALUE;
    return formatPercent(scale(d, -2), decimals == null ? 1 : decimals, opts);
  }
  function formatProbabilityPct(valuePct, opts) { return formatPercent(valuePct, 0, opts); }
  function currencyExponent(currency) {
    var c = String(currency || '').toUpperCase().trim();
    if (!(c in CURRENCY_EXPONENTS)) throw new Error('Minor-Unit-Exponent unbekannt: ' + currency);
    return CURRENCY_EXPONENTS[c];
  }
  // N-894-01: Ares speichert alle *_rappen-Felder mit Faktor 100 (auch JPY);
  // gelesen wird immer mit STORAGE_EXPONENT, angezeigt hoechstens mit den
  // ISO-Nachkommastellen (displayDecimals, JPY 0).
  var STORAGE_EXPONENT = 2;
  function displayDecimals(currency) { return minorExponent(currency); }
  function requireInt(v, what) {
    var n = typeof v === 'string' && v.trim() !== '' ? Number(v) : v;
    if (typeof n !== 'number' || !isFinite(n) || Math.floor(n) !== n) throw new Error(what + ': Ganzzahl erwartet');
    return n;
  }
  function formatStoredAmount(rappen, currency, decimals, opts) {
    var unit = unitOf(currency);
    var shown = Math.min(decimals == null ? 0 : Number(decimals), displayDecimals(unit));
    return formatMoneyMinor(rappen, unit, STORAGE_EXPONENT, shown, opts);
  }
  function minorExponent(currency) {
    var c = String(currency || '').toUpperCase().trim();
    return c in CURRENCY_EXPONENTS ? CURRENCY_EXPONENTS[c] : 2;
  }
  function unitOf(currency) {
    var c = String(currency || '').toUpperCase().trim();
    if (!c) throw new Error('Waehrung ist Pflicht');
    return c;
  }
  function formatMoneyMinor(minor, currency, exponent, decimals, opts) {
    var unit = unitOf(currency), d = toDecimal(minor);
    if (!d) return NO_VALUE;
    var shown = decimals == null ? Number(exponent) : Number(decimals);
    return unit + ' ' + formatDecimal(scale(d, -Number(exponent)), shown, opts);
  }
  function formatSignedMoneyMinor(minor, currency, exponent, decimals, opts) {
    var unit = unitOf(currency), d = toDecimal(minor);
    if (!d) return NO_VALUE;
    var shown = decimals == null ? Number(exponent) : Number(decimals);
    var r = roundUnits(scale(d, -Number(exponent)), shown), body = digits(r.units, shown);
    if (r.units === ZERO) return unit + ' ' + body;
    return (r.neg ? glyphs(opts && opts.typography).minus : '+') + unit + ' ' + body;
  }
  function absGreaterEqualMillion(d) {
    // |d| >= 1'000'000 exakt.
    var shift = d.exp - 6;
    if (shift >= 0) return d.coef !== ZERO;
    return d.coef >= pow10(-shift);
  }
  function formatCompactAmount(major, opts) {
    var d = toDecimal(major);
    if (!d) return NO_VALUE;
    if (absGreaterEqualMillion(d)) return formatDecimal(scale(d, -6), 2, opts) + ' Mio.';
    return formatDecimal(d, 0, opts);
  }
  function formatMoneyCompactMinor(minor, currency, exponent, opts) {
    var unit = String(currency || '').toUpperCase().trim(), d = toDecimal(minor);
    if (!d) return NO_VALUE;
    return unit + ' ' + formatCompactAmount(scale(d, -Number(exponent)), opts);
  }

  // Largest Remainder. values: Werte in bps (>= 0); decimals: Prozent-Nachkommastellen;
  // targetDisplay: optionale Gruppensumme in Prozent (z. B. angezeigter Klassenwert).
  // Rueckgabe: Anzeigeeinheiten (BigInt) je Wert, Einheit = 10^-decimals Prozent.
  function apportionUnits(values, decimals, targetUnits) {
    var ds = (values || []).map(function (v) {
      var d = toDecimal(v);
      if (!d) throw new Error('Apportionierung braucht Werte');
      if (d.neg) throw new Error('Apportionierung nur fuer nicht-negative Gewichte');
      return scale(d, decimals - 2); // in Anzeigeeinheiten
    });
    var e = 0;
    ds.forEach(function (d) { if (d.exp < e) e = d.exp; });
    var p = pow10(-e), ints = ds.map(function (d) { return d.coef * pow10(d.exp - e); });
    var units = ints.map(function (v) { return v / p; });
    var rems = ints.map(function (v) { return v % p; });
    var sum = ints.reduce(function (a, b) { return a + b; }, ZERO);
    var target = targetUnits;
    if (target == null) target = roundUnits({ neg: false, coef: sum, exp: e }, 0).units;
    target = BigInt(target);
    var missing = target - units.reduce(function (a, b) { return a + b; }, ZERO);
    var withRem = rems.filter(function (r) { return r !== ZERO; }).length;
    if (missing < ZERO || missing > BigInt(withRem)) throw new Error('Ziel der Apportionierung unvereinbar');
    var order = units.map(function (_, i) { return i; }).sort(function (a, b) {
      if (rems[a] !== rems[b]) return rems[a] > rems[b] ? -1 : 1;
      return a - b;
    });
    for (var k = 0; BigInt(k) < missing; k++) units[order[k]] += ONE;
    return units;
  }
  function targetUnitsFromDisplay(targetDisplay, decimals) {
    if (targetDisplay == null) return null;
    var d = toDecimal(targetDisplay);
    if (!d) throw new Error('targetDisplay fehlt');
    return roundUnits(d, decimals).units;
  }
  function unitsToDecimal(u, decimals) { return { neg: false, coef: u, exp: -decimals }; }
  // -> Prozentwerte als Dezimalstrings ("33.4"), Summe erhalten.
  function apportionPercentBps(values, decimals, opts) {
    var n = decimals == null ? 1 : decimals;
    opts = opts || {};
    var units = apportionUnits(values, n, targetUnitsFromDisplay(opts.targetDisplay, n));
    return units.map(function (u) { return digits(u, n).replace(/'/g, ''); });
  }
  function formatApportionedPercentBps(values, decimals, opts) {
    var n = decimals == null ? 1 : decimals;
    opts = opts || {};
    var units = apportionUnits(values, n, targetUnitsFromDisplay(opts.targetDisplay, n));
    return units.map(function (u) { return formatPercent(unitsToDecimal(u, n), n, opts); });
  }
  // Betraege der Soll-Darstellung in ganzen Einheiten (identisch zu presentation_amounts
  // in core/presentation_rounding.py): Beratungsvermoegen/Strategiebasis Half-up,
  // Reserve = Differenz, Klassen = Largest Remainder der Basis nach Gewicht
  // (Gleichstand: groesseres Gewicht, dann Engine-Schluessel, dann Position).
  var ASSET_KEYS = { aktien: 'equities', equities: 'equities', obligationen: 'bonds', anleihen: 'bonds', bonds: 'bonds',
    immobilien: 'real_estate', real_estate: 'real_estate', 'real estate': 'real_estate', alternative: 'alternatives',
    alternativen: 'alternatives', alternatives: 'alternatives', liquiditaet: 'liquidity', 'liquidität': 'liquidity', liquidity: 'liquidity' };
  function assetClassKey(label) {
    var raw = String(label == null ? '' : label).trim();
    return ASSET_KEYS[raw.toLowerCase()] || raw;
  }
  function wholeUnits(minor, exponent) {
    var d = toDecimal(minor);
    if (!d) return ZERO;
    var r = roundUnits(scale(d, -Number(exponent == null ? 2 : exponent)), 0);
    return r.neg ? -r.units : r.units;
  }
  function splitLargestRemainder(total, weights, labels) {
    var clean = weights.map(function (w) { return BigInt(Math.max(0, requireInt(w, 'Gewicht'))); });
    var sum = clean.reduce(function (a, b) { return a + b; }, ZERO);
    total = BigInt(total);
    if (sum <= ZERO || total <= ZERO) return clean.map(function () { return ZERO; });
    var floors = clean.map(function (w) { return total * w / sum; });
    var rems = clean.map(function (w) { return total * w % sum; });
    var order = clean.map(function (_, i) { return i; }).sort(function (a, b) {
      if (rems[a] !== rems[b]) return rems[a] > rems[b] ? -1 : 1;
      if (clean[a] !== clean[b]) return clean[a] > clean[b] ? -1 : 1;
      var la = String(labels[a]), lb = String(labels[b]);
      if (la !== lb) return la < lb ? -1 : 1;
      return a - b;
    });
    var missing = total - floors.reduce(function (a, b) { return a + b; }, ZERO);
    for (var k = 0; BigInt(k) < missing; k++) floors[order[k]] += ONE;
    return floors;
  }
  function presentationAmounts(advisoryMinor, baseMinor, weights, labels, exponent) {
    var e = exponent == null ? STORAGE_EXPONENT : Number(exponent);
    var adv = Math.max(0, requireInt(advisoryMinor == null ? 0 : advisoryMinor, 'Beratungsvermoegen'));
    var baseRaw = baseMinor == null ? adv : Math.max(0, requireInt(baseMinor, 'Strategiebasis'));
    var base = wholeUnits(Math.min(baseRaw, adv), e), advisory = wholeUnits(adv, e);
    var keys = (labels || []).map(assetClassKey);
    var buckets = base > ZERO ? splitLargestRemainder(base, weights || [], keys) : keys.map(function () { return ZERO; });
    var reserve = advisory - base;
    return { advisory: Number(advisory), base: Number(base), reserve: Number(reserve > ZERO ? reserve : ZERO),
      buckets: buckets.map(function (u) { return Number(u); }) };
  }
  function canonicalRank(key) {
    var i = CANONICAL_ASSET_CLASS_ORDER.indexOf(String(key || ''));
    return i < 0 ? CANONICAL_ASSET_CLASS_ORDER.length : i;
  }
  // N-894-02: Soll-Anteile einer Bucket-Liste ({asset_class,target_weight_bps})
  // gemeinsam apportionieren (kanonische Gleichstandsregel) -> Map asset_class ->
  // Anzeige (auch unter dem Engine-Schluessel). Gleiche Regel wie
  // allocation_pct_texts (PDF) und aaChartPrepare.
  function bucketPctMap(buckets, opts) {
    var list = (buckets || []).map(function (b, i) { return { b: b, i: i }; }).filter(function (x) {
      return x.b && Number(x.b.target_weight_bps) > 0;
    }).sort(function (x, y) {
      return (canonicalRank(assetClassKey(x.b.asset_class)) - canonicalRank(assetClassKey(y.b.asset_class))) || (x.i - y.i);
    });
    var out = {};
    if (!list.length) return out;
    var shown = formatApportionedPercentBps(list.map(function (x) { return Math.round(Number(x.b.target_weight_bps)); }), 1, opts);
    list.forEach(function (x, k) {
      out[String(x.b.asset_class)] = shown[k];
      out[assetClassKey(x.b.asset_class)] = shown[k];
    });
    return out;
  }
  // Unterklassen (Name -> bps, gleiche Namen summiert) auf den angezeigten
  // Klassenwert apportionieren; Rest "ohne Unterklasse" zuletzt, nicht ausgegeben.
  // Identisch zu apportion_sub_bps (Python).
  function subPctMap(classDisplay, subs, classBps, opts) {
    var agg = {};
    (subs || []).forEach(function (s) {
      var n = String(s && s.name != null ? s.name : ''), v = Math.round(Number(s && s.bps) || 0);
      if (n && v > 0) agg[n] = (agg[n] || 0) + v;
    });
    var names = Object.keys(agg).sort(function (a, b) { return a < b ? -1 : (a > b ? 1 : 0); });
    var out = {};
    if (!names.length) return out;
    var values = names.map(function (n) { return agg[n]; });
    var total = values.reduce(function (a, b) { return a + b; }, 0), klass = Math.round(Number(classBps) || 0);
    var target = null;
    if (total <= klass) {
      if (total < klass) values.push(klass - total);
      target = String(classDisplay || '').replace(/[^0-9.]/g, '');
    }
    var shown = formatApportionedPercentBps(values, 1, { typography: opts && opts.typography, targetDisplay: target });
    names.forEach(function (n, k) { out[n] = shown[k]; });
    return out;
  }
  function presentationArtifact(raw, unit, display) {
    return { raw: raw, unit: unit, policy_version: POLICY_VERSION, display: display };
  }
  // Golden-Fall ausfuehren (gleiche Funktionsnamen wie Python/TS).
  function runCase(fn, args, typography) {
    var o = { typography: typography };
    switch (fn) {
      case 'number': return formatDecimal(args[0], args.length > 1 ? args[1] : 0, o);
      case 'signed_number': return formatDecimal(args[0], args.length > 1 ? args[1] : 0, { typography: typography, signed: true });
      case 'percent_bps': return formatPercentBps(args[0], args.length > 1 ? args[1] : 1, o);
      case 'signed_percent_bps': return formatPercentBps(args[0], args.length > 1 ? args[1] : 1, { typography: typography, signed: true });
      case 'percent': return formatPercent(args[0], args.length > 1 ? args[1] : 1, o);
      case 'probability_pct': return formatProbabilityPct(args[0], o);
      case 'money_minor': return formatMoneyMinor(args[0], args[1], args[2], args.length > 3 ? args[3] : null, o);
      case 'signed_money_minor': return formatSignedMoneyMinor(args[0], args[1], args[2], args.length > 3 ? args[3] : null, o);
      case 'money_compact_minor': return formatMoneyCompactMinor(args[0], args[1], args[2], o);
      case 'apportion_percent_bps': return formatApportionedPercentBps(args[0], args[1], { typography: typography, targetDisplay: args.length > 2 ? args[2] : null });
      case 'stored_amount': return formatStoredAmount(args[0], args[1], args.length > 2 ? args[2] : 0, o);
      case 'presentation_amounts': {
        var pa = presentationAmounts(args[0], args[1], args[2], args[3], args.length > 4 ? args[4] : 2);
        return [String(pa.advisory), String(pa.base), String(pa.reserve)].concat(pa.buckets.map(String));
      }
      case 'apportioned_sum': {
        var n = args.length > 1 ? args[1] : 1;
        var u = apportionUnits(args[0], n, null).reduce(function (a, b) { return a + b; }, ZERO);
        return formatPercent(unitsToDecimal(u, n), n, o);
      }
      default: throw new Error('unbekannte Golden-Funktion ' + fn);
    }
  }
  return {
    POLICY_VERSION: POLICY_VERSION,
    NO_VALUE: NO_VALUE,
    CANONICAL_ASSET_CLASS_ORDER: CANONICAL_ASSET_CLASS_ORDER.slice(),
    CURRENCY_EXPONENTS: CURRENCY_EXPONENTS,
    toDecimal: toDecimal,
    formatDecimal: formatDecimal,
    formatPercent: formatPercent,
    formatPercentBps: formatPercentBps,
    formatProbabilityPct: formatProbabilityPct,
    currencyExponent: currencyExponent,
    minorExponent: minorExponent,
    STORAGE_EXPONENT: STORAGE_EXPONENT,
    displayDecimals: displayDecimals,
    formatStoredAmount: formatStoredAmount,
    formatMoneyMinor: formatMoneyMinor,
    formatSignedMoneyMinor: formatSignedMoneyMinor,
    formatCompactAmount: formatCompactAmount,
    formatMoneyCompactMinor: formatMoneyCompactMinor,
    apportionUnits: apportionUnits,
    apportionPercentBps: apportionPercentBps,
    formatApportionedPercentBps: formatApportionedPercentBps,
    canonicalRank: canonicalRank,
    assetClassKey: assetClassKey,
    presentationAmounts: presentationAmounts,
    bucketPctMap: bucketPctMap,
    subPctMap: subPctMap,
    presentationArtifact: presentationArtifact,
    runCase: runCase
  };
});
