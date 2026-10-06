from __future__ import annotations

import csv
import json
import sys
from datetime import datetime, timedelta, timezone

from engine import ROOT, load_draws

HK = timezone(timedelta(hours=8))


def write_all(payload: dict) -> None:
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    for base in ("reports", "site", "docs"):
        path = ROOT / base / "daily_integrity_audit.json"
        tmp = path.with_suffix(".tmp")
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(path)


def main() -> int:
    now = datetime.now(HK)
    raw = list(csv.DictReader((ROOT / "data/official_marksix.csv").open(encoding="utf-8-sig", newline="")))
    draws = load_draws()
    history = json.loads((ROOT / "data/prediction_history.json").read_text(encoding="utf-8-sig"))
    analysis = json.loads((ROOT / "reports/latest_analysis.json").read_text(encoding="utf-8"))
    checks = []

    def add(name, ok, detail):
        checks.append({"name": name, "passed": bool(ok), "detail": detail})

    dates = [r["draw_date"] for r in raw]
    periods = [r["period"] for r in raw]
    valid_rows = True
    for row in raw:
        try:
            nums = [int(row[f"n{i}"]) for i in range(1, 7)]
            special = int(row["special"])
            valid_rows = valid_rows and len(set(nums)) == 6 and special not in nums and all(1 <= n <= 49 for n in nums + [special])
        except (KeyError, TypeError, ValueError):
            valid_rows = False
    draw_by_date = {d.draw_date: d for d in draws}
    settled_ok = True
    for pred in history:
        if pred.get("status") != "settled":
            continue
        actual = pred.get("actual", {})
        source = draw_by_date.get(pred.get("target_date"))
        if not source or actual.get("main") != list(source.main) or actual.get("special") != source.special:
            settled_ok = False
            break
    prediction_keys = [
        (prediction.get("based_on_period"), prediction.get("target_date"))
        for prediction in history
    ]

    add("row_count_consistent", len(raw) == len(draws) and len(raw) >= 2152, f"csv={len(raw)} parsed={len(draws)}")
    add("unique_draw_dates", len(dates) == len(set(dates)), f"duplicates={len(dates)-len(set(dates))}")
    add("unique_periods", len(periods) == len(set(periods)), f"duplicates={len(periods)-len(set(periods))}")
    add("chronological_order", dates == sorted(dates), f"first={dates[0]} latest={dates[-1]}")
    add("numbers_valid", valid_rows, "six unique main numbers + separate special, all 1-49")
    add("settlements_immutable_and_matched", settled_ok, f"settled={sum(p.get('status') == 'settled' for p in history)}")
    add("unique_prediction_snapshots", len(prediction_keys) == len(set(prediction_keys)), f"duplicates={len(prediction_keys)-len(set(prediction_keys))}; identity=based_on_period+target_date")
    add("analysis_based_on_latest", analysis["latest_draw"]["date"] == dates[-1], f"analysis={analysis['latest_draw']['date']} csv={dates[-1]}")
    add("prediction_snapshot_exists", any(p.get("based_on_period") == analysis["latest_draw"]["period"] for p in history), analysis["latest_draw"]["period"])

    passed = all(x["passed"] for x in checks)
    payload = {
        "system": analysis["system"],
        "checked_at": now.isoformat(timespec="seconds"),
        "passed": passed,
        "latest_period": analysis["latest_draw"]["period"],
        "latest_date": analysis["latest_draw"]["date"],
        "prediction_gate_passed": analysis["release_gate"]["passed"],
        "checks": checks,
    }
    write_all(payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
