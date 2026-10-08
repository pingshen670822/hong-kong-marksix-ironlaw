from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timedelta, timezone

from engine import ROOT, load_draws

HK = timezone(timedelta(hours=8))
SYNC_FILES = (
    "index.html", "latest_battle_report.html", "latest_analysis.json",
    "prediction_history.json", "version.json", "style.css", "app.js",
    "service-worker.js", "manifest.webmanifest", "self_test_report.json",
)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_all(name: str, payload: dict) -> None:
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    for base in ("reports", "site", "docs"):
        path = ROOT / base / name
        tmp = path.with_suffix(".tmp")
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(path)


def main() -> int:
    from v9.verify import verify as verify_official_v9
    return verify_official_v9()
    now = datetime.now(HK)
    checks = []

    def add(name, ok, detail):
        checks.append({"name": name, "passed": bool(ok), "detail": detail})

    draws = load_draws()
    analysis = json.loads((ROOT / "reports/latest_analysis.json").read_text(encoding="utf-8"))
    self_test = json.loads((ROOT / "reports/self_test_report.json").read_text(encoding="utf-8"))
    latest = datetime.fromisoformat(draws[-1].draw_date).date()
    target = datetime.fromisoformat(analysis["target_date"]).date()
    age = (now.date() - latest).days
    overdue = target <= now.date() and latest < target and (now.hour > 23 or (now.hour == 23 and now.minute >= 30))
    source = analysis.get("data_source_status", {})
    cloud_dirs = [ROOT / base for base in ("reports", "site", "docs")]
    json_paths = [path for directory in cloud_dirs for path in directory.glob("*.json")]
    json_errors = []
    for path in json_paths:
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            json_errors.append(f"{path.relative_to(ROOT)}: {error}")
    required_paths = [ROOT / base / name for base in ("reports", "site", "docs") for name in SYNC_FILES]
    temp_paths = [path for directory in cloud_dirs for path in directory.glob("*.tmp")]

    add("latest_draw_matches_database", analysis["latest_draw"]["date"] == draws[-1].draw_date and analysis["latest_draw"]["period"] == draws[-1].period, f"{draws[-1].period} {draws[-1].draw_date}")
    add("data_recency", 0 <= age <= 10 and not overdue, f"age={age}; overdue={overdue}; target={target}")
    add("source_fetch_available", source.get("primary_rows", 0) > 0 or source.get("fallback_rows", 0) > 0, json.dumps(source, ensure_ascii=False))
    add("operational_self_test", self_test.get("operational_passed") is True, self_test.get("status"))
    add("cloud_outputs_identical", all(sha(ROOT / "reports" / f) == sha(ROOT / "site" / f) == sha(ROOT / "docs" / f) for f in SYNC_FILES), "reports/site/docs")
    add("all_cloud_json_readable", not json_errors and bool(json_paths), "; ".join(json_errors) or f"{len(json_paths)} JSON files")
    add("required_outputs_nonempty", all(path.exists() and path.stat().st_size > 0 for path in required_paths), f"{len(required_paths)} required files")
    add("no_stale_atomic_files", not temp_paths, ", ".join(str(path.relative_to(ROOT)) for path in temp_paths) or "none")

    healthy = all(x["passed"] for x in checks)
    payload = {
        "system": analysis["system"],
        "checked_at": now.isoformat(timespec="seconds"),
        "healthy": healthy,
        "status": "系統健康" if healthy else "系統需自主修復",
        "prediction_mode": analysis["release_gate"].get("publish_mode", "未知"),
        "latest_period": draws[-1].period,
        "latest_date": draws[-1].draw_date,
        "target_date": analysis["target_date"],
        "checks": checks,
    }
    write_all("health_status.json", payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if healthy else 1


if __name__ == "__main__":
    from v9.verify import verify as verify_official_v9
    print(json.dumps(verify_official_v9(), ensure_ascii=False, indent=2))
