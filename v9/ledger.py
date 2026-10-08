"""Append-only forecast/settlement events with a tamper-evident hash chain."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from .official_source import OfficialDraw

ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / "data" / "v9_forecast_events.jsonl"
GENESIS = "0" * 64


def _canonical(data: dict) -> bytes:
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def load_events(path: Path = LEDGER) -> list[dict]:
    if not path.exists():
        return []
    events = []
    previous = GENESIS
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        event = json.loads(line)
        digest = event.get("hash")
        body = {key: value for key, value in event.items() if key != "hash"}
        if event.get("previous_hash") != previous or hashlib.sha256(_canonical(body)).hexdigest() != digest:
            raise ValueError("Forecast ledger hash chain broken")
        previous = digest
        events.append(event)
    return events


def _append(body: dict, path: Path = LEDGER) -> dict:
    previous = load_events(path)
    body = {**body, "previous_hash": previous[-1]["hash"] if previous else GENESIS}
    event = {**body, "hash": hashlib.sha256(_canonical(body)).hexdigest()}
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
    return event


def update_ledger(draws: list[OfficialDraw], rank: list[int], model: str, source_sha256: str, *, path: Path = LEDGER) -> dict:
    if len(rank) != 49 or set(rank) != set(range(1, 50)):
        raise ValueError("Forecast ranking must contain 1..49 exactly once")
    events = load_events(path)
    by_date = {draw.draw_date: index for index, draw in enumerate(draws)}
    settled = {event["forecast_hash"] for event in events if event.get("kind") == "settlement"}
    forecasts = [event for event in events if event.get("kind") == "forecast"]
    for forecast in forecasts:
        if forecast["hash"] in settled:
            continue
        basis_index = by_date.get(forecast["based_on_date"])
        if basis_index is None or basis_index + 1 >= len(draws):
            continue
        actual = draws[basis_index + 1]
        created_date = datetime.fromisoformat(forecast["created_at_utc"]).date().isoformat()
        if created_date >= actual.draw_date:
            # A forecast first recorded on or after the draw date is not a valid
            # independent prospective result; keep it visible but do not settle.
            continue
        _append({"kind": "settlement", "forecast_hash": forecast["hash"],
                 "settled_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                 "actual_period": actual.period, "actual_date": actual.draw_date,
                 "actual_main": list(actual.main), "single_hit": int(forecast["single"] in actual.main)}, path)
        settled.add(forecast["hash"])
    latest = draws[-1]
    if not any(event["based_on_period"] == latest.period for event in forecasts):
        _append({"kind": "forecast", "created_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                 "based_on_period": latest.period, "based_on_date": latest.draw_date,
                 "model": model, "official_data_sha256": source_sha256,
                 "single": rank[0], "top9": rank[:9], "ranking": rank,
                 "target": "首次晚於依據期別的下一次官方攪珠；日期待官方公告"}, path)
    events = load_events(path)
    settlements = [event for event in events if event.get("kind") == "settlement"]
    return {"forecasts": sum(event.get("kind") == "forecast" for event in events),
            "settled": len(settlements), "hits": sum(event["single_hit"] for event in settlements),
            "latest_forecast": next(event for event in reversed(events) if event.get("kind") == "forecast"),
            "chain_tip": events[-1]["hash"]}
