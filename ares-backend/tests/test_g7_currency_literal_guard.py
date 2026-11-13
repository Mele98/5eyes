"""G7 / H-153 Nachtrag 3 -- systematischer Guard gegen fest eingetragene "CHF".

Jede Fundstelle des Tokens ``CHF`` in Anzeige-/Formatierpfaden (Classic-Bundle inkl.
Standalone-Module, React-Bericht, PDF-Komponenten) muss in der Allowlist
``docs/audits/2026-11-13-g7-currency-literal-allowlist.json`` mit Einzelbegruendung
stehen -- exakt mit Anzahl. Neue Fundstellen (z. B. ein ``'CHF '+`` in einem
Formatter) machen den Test rot; entfernte Fundstellen muessen aus der Allowlist
gestrichen werden.
"""
from __future__ import annotations

import collections
import json

from tests.currency_literal_scan import ALLOWLIST_PATH, REPO_ROOT, scan, scan_text, scanned_files
from tests.livetest_monolith_js import extract_function, html, run_js


def _allowlist() -> dict[tuple[str, str], dict]:
    data = json.loads(ALLOWLIST_PATH.read_text(encoding="utf-8"))
    out = {}
    for e in data["entries"]:
        key = (e["file"], e["code"])
        assert key not in out, f"doppelter Allowlist-Eintrag {key}"
        out[key] = e
    return out


def _unjustified(hits) -> list:
    allow = _allowlist()
    counts = collections.Counter(hits)
    return [(k, n) for k, n in counts.items() if k not in allow or allow[k]["count"] < n]


def test_scope_covers_classic_standalone_react_and_pdf():
    rels = {p.relative_to(REPO_ROOT).as_posix() for p in scanned_files()}
    for must in ("ares-desktop/frontend/ares.html", "ares-desktop/frontend/presentation-rounding.js",
                 "ares-desktop/frontend/aa-chart.js", "ares-desktop/frontend/trade-list-preview.js",
                 "ares-desktop/frontend/goal-review-runtime.js",
                 "ares-desktop/frontend/reporting/src/lib/format.ts",
                 "ares-desktop/frontend/reporting/src/components/MonteCarloPathsChart.tsx",
                 "ares-backend/services/pdf/components/mc_paths_chart.py",
                 "ares-backend/routers/pdf_reports.py"):
        assert must in rels, must
    assert not any("/vendor/" in r or ".test." in r for r in rels)


def test_every_chf_literal_is_individually_justified():
    hits = scan()
    bad = _unjustified(hits)
    assert not bad, "neue/unbegruendete 'CHF'-Literale:\n" + "\n".join(f"{f}: {c} (x{n})" for (f, c), n in bad)
    counts = collections.Counter(hits)
    stale = [k for k, e in _allowlist().items() if counts.get(k, 0) != e["count"]]
    assert not stale, f"veraltete Allowlist-Eintraege (Anzahl/Code geaendert): {stale[:5]}"


def test_reasons_are_site_specific():
    for (rel, _code), e in _allowlist().items():
        r = e["reason"]
        assert r.startswith(rel.split("/")[-1] + " " + e["context"] + ":"), r
        assert len(r) >= 80, r


def test_mutation_new_chf_in_a_formatter_turns_red():
    """Mutation: ein neues ``'CHF '+`` im App-Formatter, im React-Formatter und im PDF-Formatter."""
    src = html()
    fn = extract_function(src, "formatRappen")
    body = fn.split("{", 1)
    mutated = body[0] + "{ if(window.__m)return 'CHF '+fmtNumber(rappen/100,0);" + body[1]
    assert _unjustified(scan_text("ares-desktop/frontend/ares.html", mutated)), "Classic-Mutation nicht erkannt"
    ts = (REPO_ROOT / "ares-desktop/frontend/reporting/src/lib/format.ts").read_text(encoding="utf-8")
    ts += "\nexport function leak(v: number): string { return `CHF ${v}`; }\n"
    assert _unjustified(scan_text("ares-desktop/frontend/reporting/src/lib/format.ts", ts)), "React-Mutation nicht erkannt"
    rel = "ares-backend/services/pdf/components/wealth_chart.py"
    py = (REPO_ROOT / rel).read_text(encoding="utf-8") + '\n\ndef _leak(x):\n    return f"CHF {x}"\n'
    assert _unjustified(scan_text(rel, py)), "PDF-Mutation nicht erkannt"


def test_ccy_labels_follow_mandate_and_position_currency():
    out = run_js(
        ("cashflowAmountLabel", "aaChartCurrency"),
        "var spans=[{textContent:'CHF'},{textContent:'CHF'}];"
        "var root={querySelectorAll:function(){return spans;}};"
        "document.querySelectorAll=function(sel){return sel==='.ccy'?spans:[];};"
        "syncCcy(); var a=spans.map(function(s){return s.textContent;});"
        "syncCcy('USD',root); var b=spans[0].textContent;"
        "var l1=cashflowAmountLabel('jährlich','Income','Lohn');"
        "currentCashflowEditId='c1'; var l2=cashflowAmountLabel('einmalig','Income','Erbe');"
        "return {a:a,b:b,l1:l1,l2:l2};",
        prelude="var currentMandateData={base_currency:'EUR'};var currentCashflows=[{id:'c1',currency:'JPY'}];"
                "var currentCashflowEditId=null;function isCapitalWithdrawalCashflow(){return false;}"
                "function isOneOffCashflow(f){return f==='einmalig';}"
                + extract_function(html(), "syncCcy"),
    )
    assert out["a"] == ["EUR", "EUR"]
    assert out["b"] == "USD"
    assert out["l1"] == "Betrag pro Periode (EUR) *"
    assert out["l2"] == "Betrag (JPY) *"
