"""One official-only update, recomputation, sealed forecast and publication."""
from __future__ import annotations

import json

from .data import sync_official
from .ledger import update_ledger
from .model import replay
from .official_source import fetch_upcoming
from .report import build_report
from .verify import verify


def run() -> dict:
    draws, manifest = sync_official()
    try:
        upcoming = fetch_upcoming()
    except (OSError, ValueError, RuntimeError):
        upcoming = None
    model = replay(draws)
    ledger = update_ledger(draws, model["rank"], model["selected_model"], manifest["sha256"])
    analysis = build_report(draws, manifest, model, ledger, upcoming)
    result = verify()
    return {"period": analysis["latest_draw"]["period"], "date": analysis["latest_draw"]["date"],
            "official_rows": len(draws), "single": model["single"],
            "prospective": f"{ledger['hits']}/{ledger['settled']}", "health": result["passed"]}


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2))
