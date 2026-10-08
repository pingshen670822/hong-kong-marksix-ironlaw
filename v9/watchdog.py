"""Bounded official-only retries; never substitutes a third-party draw."""
from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone

from .data import ROOT
from .pipeline import run


def _status(payload: dict) -> None:
    raw = json.dumps(payload, ensure_ascii=False, indent=2)
    for directory in (ROOT / "reports", ROOT / "site", ROOT / "docs"):
        directory.mkdir(parents=True, exist_ok=True)
        temporary = directory / "repair_status.tmp"
        temporary.write_text(raw, encoding="utf-8")
        temporary.replace(directory / "repair_status.json")
        if payload.get("self_repair") != "passed":
            for filename, state in (
                ("health_status.json", {"healthy": False, "status": "官方資料抓取或驗證失敗", "checked_at": payload["checked_at"], "official_only": True}),
                ("self_test_report.json", {"operational_passed": False, "prediction_gate_passed": False, "status": "系統檢修中", "checked_at": payload["checked_at"]}),
            ):
                destination = directory / filename
                temp = directory / (filename + ".tmp")
                temp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
                temp.replace(destination)


def main() -> int:
    errors = []
    for attempt in range(1, 4):
        try:
            result = run()
            payload = {"self_repair": "passed", "attempt": attempt,
                       "checked_at": datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds"),
                       "official_only": True, "latest_period": result["period"], "latest_date": result["date"]}
            _status(payload)
            print(json.dumps(payload, ensure_ascii=False))
            return 0
        except Exception as error:
            errors.append(f"attempt {attempt}: {type(error).__name__}: {error}")
            _status({"self_repair": "retrying" if attempt < 3 else "failed", "attempt": attempt,
                     "checked_at": datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds"),
                     "official_only": True, "errors": errors[-3:]})
            if attempt < 3:
                time.sleep(15 * attempt)
    print(json.dumps({"self_repair": "failed", "errors": errors}, ensure_ascii=False))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
