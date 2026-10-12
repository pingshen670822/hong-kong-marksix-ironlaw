"""Re-fetch every modern-era draw and compare it with the stored official file."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone

from .data import DATA_PATH, ROOT, load_verified
from .official_source import ENDPOINT, OfficialDraw, fetch_months

HKT = timezone(timedelta(hours=8))


def compare(stored: list[OfficialDraw], official: list[OfficialDraw], csv_sha256: str) -> dict:
    local = {draw.draw_date: draw for draw in stored}
    remote = {draw.draw_date: draw for draw in official}
    missing = sorted(remote.keys() - local.keys())
    extra = sorted(local.keys() - remote.keys())
    mismatches = sorted(day for day in local.keys() & remote.keys() if local[day] != remote[day])
    return {
        "schema": "marksix_full_official_audit_v1",
        "checked_at": datetime.now(HKT).isoformat(timespec="seconds"),
        "source": ENDPOINT,
        "range_start": "2003-01",
        "range_end": datetime.now(HKT).strftime("%Y-%m"),
        "stored_count": len(stored),
        "official_count": len(official),
        "matched_count": len(local.keys() & remote.keys()) - len(mismatches),
        "missing_local": missing,
        "extra_local": extra,
        "mismatched_dates": mismatches,
        "stored_csv_sha256": csv_sha256,
        "latest_period": official[-1].period if official else None,
        "latest_date": official[-1].draw_date if official else None,
        "matched": bool(stored) and stored == official,
    }


def main() -> int:
    stored = load_verified()
    now = datetime.now(HKT)
    official = fetch_months((2003, 1), (now.year, now.month), workers=4)
    record = compare(stored, official, hashlib.sha256(DATA_PATH.read_bytes()).hexdigest())
    raw = json.dumps(record, ensure_ascii=False, indent=2)
    for name in ("reports", "site", "docs"):
        destination = ROOT / name / "full_official_audit.json"
        temporary = destination.with_suffix(".tmp")
        temporary.write_text(raw, encoding="utf-8")
        temporary.replace(destination)
    print(raw)
    return 0 if record["matched"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
