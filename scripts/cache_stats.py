"""CLI: Aggregator-Cache-Statistik auslesen.

Direkter DB-Zugriff (kein Backend-Server noetig). Liest die Tabelle
`market_data_cache` und zeigt Aggregat-Stats pro cache_kind + die
aelteste/neueste Eintragszeit. Optional --purge-expired ruft die
existierende CachedAggregator.purge_expired()-Logik.

Aufruf:
    python scripts/cache_stats.py
    python scripts/cache_stats.py --db-path /pfad/zur/5eyes.db
    python scripts/cache_stats.py --purge-expired
    python scripts/cache_stats.py --json

Exit-Codes:
    0 = OK
    1 = DB nicht erreichbar oder leer-und-bezahlt-Fall
"""
from __future__ import annotations

import argparse
import json as _json
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _ensure_backend_on_path() -> None:
    here = Path(__file__).resolve()
    backend = here.parent.parent / "5eyes-backend"
    if backend.exists() and str(backend) not in sys.path:
        sys.path.insert(0, str(backend))


@dataclass
class KindStats:
    kind: str
    total: int = 0
    valid: int = 0
    expired: int = 0


@dataclass
class CacheStatsReport:
    db_path: str
    total_entries: int = 0
    by_kind: list[KindStats] = field(default_factory=list)
    oldest_fetched_at: str | None = None
    newest_fetched_at: str | None = None
    purged: int | None = None
    error: str | None = None


def _now_utc_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def collect_cache_stats(db_path: str | None = None) -> CacheStatsReport:
    """Liest market_data_cache und baut Stats."""
    from sqlalchemy import create_engine, func
    from sqlalchemy.orm import sessionmaker
    from models.market_data_cache import MarketDataCacheEntry

    if db_path:
        url = f"sqlite:///{db_path}"
        path_str = db_path
    else:
        from config import settings
        url = f"sqlite:///{settings.db_path}"
        path_str = settings.db_path

    rpt = CacheStatsReport(db_path=path_str)
    try:
        engine = create_engine(url, connect_args={"check_same_thread": False})
        Session = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    except Exception as exc:  # noqa: BLE001
        rpt.error = f"engine init: {exc}"
        return rpt

    db = Session()
    try:
        try:
            rows = db.query(
                MarketDataCacheEntry.cache_kind,
                MarketDataCacheEntry.expires_at,
                MarketDataCacheEntry.fetched_at,
            ).all()
        except Exception as exc:  # noqa: BLE001
            rpt.error = f"query failed: {exc}"
            return rpt

        now_iso = _now_utc_iso()
        by_kind: dict[str, KindStats] = {}
        fetched_times: list[str] = []
        for kind, expires_at, fetched_at in rows:
            rpt.total_entries += 1
            bucket = by_kind.setdefault(str(kind), KindStats(kind=str(kind)))
            bucket.total += 1
            if (expires_at or "") <= now_iso:
                bucket.expired += 1
            else:
                bucket.valid += 1
            if fetched_at:
                fetched_times.append(str(fetched_at))

        rpt.by_kind = sorted(by_kind.values(), key=lambda k: k.kind)
        if fetched_times:
            rpt.oldest_fetched_at = min(fetched_times)
            rpt.newest_fetched_at = max(fetched_times)
    finally:
        try:
            db.close()
        except Exception:  # noqa: BLE001
            pass
        try:
            engine.dispose()
        except Exception:  # noqa: BLE001
            pass

    return rpt


def purge_expired(db_path: str | None = None) -> int:
    """Ruft CachedAggregator.purge_expired(). Returns Anzahl geloeschter."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from services.market_data import CachedAggregator
    from services.market_data.factory import build_default_aggregator

    if db_path:
        url = f"sqlite:///{db_path}"
    else:
        from config import settings
        url = f"sqlite:///{settings.db_path}"

    engine = create_engine(url, connect_args={"check_same_thread": False})
    Session = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    cached = CachedAggregator(
        base=build_default_aggregator(),
        session_factory=Session,
    )
    try:
        return cached.purge_expired()
    finally:
        engine.dispose()


def format_report(rpt: CacheStatsReport) -> str:
    """Reine Formatierung; kein I/O."""
    lines: list[str] = []
    lines.append("=== Aggregator Cache-Stats ===")
    lines.append(f"DB-Pfad: {rpt.db_path}")
    if rpt.error:
        lines.append(f"FEHLER: {rpt.error}")
        return "\n".join(lines)
    lines.append(f"Total Eintraege: {rpt.total_entries}")
    if rpt.oldest_fetched_at:
        lines.append(f"Aeltester Eintrag: {rpt.oldest_fetched_at}")
    if rpt.newest_fetched_at:
        lines.append(f"Neuester Eintrag: {rpt.newest_fetched_at}")
    lines.append("")
    lines.append(f"{'kind':<12} {'total':>7} {'valid':>7} {'expired':>9}")
    lines.append("-" * 39)
    for k in rpt.by_kind:
        lines.append(f"{k.kind:<12} {k.total:>7} {k.valid:>7} {k.expired:>9}")
    if rpt.purged is not None:
        lines.append("")
        lines.append(f"Purge: {rpt.purged} expired Eintraege entfernt.")
    return "\n".join(lines)


def report_to_dict(rpt: CacheStatsReport) -> dict[str, Any]:
    return {
        "db_path": rpt.db_path,
        "total_entries": rpt.total_entries,
        "by_kind": [asdict(k) for k in rpt.by_kind],
        "oldest_fetched_at": rpt.oldest_fetched_at,
        "newest_fetched_at": rpt.newest_fetched_at,
        "purged": rpt.purged,
        "error": rpt.error,
    }


def main(argv: list[str] | None = None) -> int:
    _ensure_backend_on_path()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db-path", default=None,
        help="Pfad zur SQLite-DB (default: settings.db_path).",
    )
    parser.add_argument(
        "--purge-expired", action="store_true",
        help="Loescht abgelaufene Cache-Eintraege vor dem Report.",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Output als JSON statt formatiertem Text.",
    )
    args = parser.parse_args(argv)

    purged: int | None = None
    if args.purge_expired:
        try:
            purged = purge_expired(args.db_path)
        except Exception as exc:  # noqa: BLE001
            print(f"purge_expired failed: {exc}", file=sys.stderr)
            return 1

    rpt = collect_cache_stats(args.db_path)
    rpt.purged = purged
    if args.json:
        print(_json.dumps(report_to_dict(rpt), indent=2, ensure_ascii=False))
    else:
        print(format_report(rpt))
    if rpt.error:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
