"""Verified-only data store. The legacy CSV is never an input to the v9 model."""
from __future__ import annotations

import csv
import hashlib
import io
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .official_source import ENDPOINT, OfficialDraw, fetch_months, fetch_recent

ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = ROOT / "data" / "hkjc_verified_v9.csv"
MANIFEST_PATH = ROOT / "data" / "hkjc_verified_v9_manifest.json"
FIELDS = ["period", "draw_date", "n1", "n2", "n3", "n4", "n5", "n6", "special", "source_id"]


def _validate(draws: list[OfficialDraw]) -> None:
    if not draws or draws != sorted(draws, key=lambda row: row.draw_date):
        raise ValueError("Official data empty or not chronological")
    if len({row.period for row in draws}) != len(draws) or len({row.draw_date for row in draws}) != len(draws):
        raise ValueError("Official data has duplicate period/date")
    for draw in draws:
        if draw.draw_date < "2003-01-01" or len(draw.main) != 6 or len(set(draw.main)) != 6:
            raise ValueError(f"Outside current 49-ball era or invalid draw: {draw.period}")
        if draw.special in draw.main or not all(1 <= n <= 49 for n in (*draw.main, draw.special)):
            raise ValueError(f"Invalid balls: {draw.period}")


def load_verified() -> list[OfficialDraw]:
    if not DATA_PATH.exists():
        return []
    with DATA_PATH.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    draws = [OfficialDraw(row["period"], row["draw_date"], tuple(int(row[f"n{i}"]) for i in range(1, 7)), int(row["special"]), row["source_id"]) for row in rows]
    _validate(draws)
    if MANIFEST_PATH.exists():
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        if hashlib.sha256(DATA_PATH.read_bytes()).hexdigest() != manifest.get("sha256"):
            raise ValueError("Verified data file differs from its manifest")
    return draws


def _save(draws: list[OfficialDraw], evidence: dict) -> dict:
    _validate(draws)
    try:
        previous_manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8")) if MANIFEST_PATH.exists() else {}
    except (OSError, json.JSONDecodeError):
        previous_manifest = {}
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=FIELDS, lineterminator="\n")
    writer.writeheader()
    for draw in draws:
        row = {"period": draw.period, "draw_date": draw.draw_date, "special": draw.special, "source_id": draw.source_id}
        row.update({f"n{i}": n for i, n in enumerate(draw.main, 1)})
        writer.writerow(row)
    raw = buffer.getvalue().encode("utf-8")
    manifest = {
        "source": "香港賽馬會官方 GraphQL 已公布攪珠結果",
        "endpoint": ENDPOINT,
        "retrieved_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "count": len(draws),
        "first": draws[0].draw_date,
        "latest": draws[-1].draw_date,
        "latest_period": draws[-1].period,
        "sha256": hashlib.sha256(raw).hexdigest(),
        "evidence": evidence,
        "history_bootstrap": (evidence if evidence.get("mode") == "full_official_bootstrap"
                              else previous_manifest.get("history_bootstrap")),
        "legacy_data_used_for_model": False,
    }
    DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    temp = DATA_PATH.with_suffix(".tmp")
    temp.write_bytes(raw)
    temp.replace(DATA_PATH)
    manifest_temp = MANIFEST_PATH.with_suffix(".tmp")
    manifest_temp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    manifest_temp.replace(MANIFEST_PATH)
    return manifest


def sync_official(*, bootstrap: bool = False) -> tuple[list[OfficialDraw], dict]:
    recovery_reason = None
    try:
        existing = load_verified()
    except (ValueError, KeyError, csv.Error) as error:
        existing = []
        bootstrap = True
        recovery_reason = f"full official refetch after integrity error: {type(error).__name__}"
    today = datetime.now(timezone(timedelta(hours=8))).date()
    if bootstrap or not existing:
        official = fetch_months((2003, 1), (today.year, today.month), workers=4)
        if len(official) < 2000:
            raise RuntimeError(f"Official history unexpectedly short: {len(official)}")
        evidence = {"mode": "full_official_bootstrap", "queried_months_from": "2003-01", "queried_months_to": f"{today.year:04d}-{today.month:02d}", "recovery_reason": recovery_reason}
    else:
        first_year = today.year if today.month > 6 else today.year - 1
        first_month = today.month - 6 if today.month > 6 else today.month + 6
        recent = fetch_months((first_year, first_month), (today.year, today.month), workers=3)
        recent += fetch_recent(20)
        merged = {row.draw_date: row for row in existing}
        for draw in recent:
            previous = merged.get(draw.draw_date)
            if previous and previous != draw:
                raise RuntimeError(f"Official revision detected; manual audit required: {draw.draw_date}")
            merged[draw.draw_date] = draw
        official = sorted(merged.values(), key=lambda row: row.draw_date)
        evidence = {"mode": "official_recent_refresh", "recent_official_results": len(recent), "previously_verified": len(existing)}
    if existing:
        old = {row.draw_date: row for row in existing}
        conflicts = [row.draw_date for row in official if row.draw_date in old and row != old[row.draw_date]]
        if conflicts:
            raise RuntimeError("Official history conflict; refusing overwrite: " + ",".join(conflicts[:5]))
    manifest = _save(official, evidence)
    return official, manifest
