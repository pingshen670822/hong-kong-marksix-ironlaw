"""Fail-open freshness gate for the independent cloud repair schedule."""

import json
import os
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MAX_AGE_MINUTES = 75


def should_repair(event_name, version, health, self_test, now=None):
    """Repair if explicitly requested, primary failed, or its report is stale."""
    if event_name != "schedule":
        return True
    try:
        if version.get("schema") != "marksix_official_v9":
            return True
        period, draw_date = version["latest_period"], version["latest_date"]
        if not period or not draw_date:
            return True
        if health.get("healthy") is not True or self_test.get("operational_passed") is not True:
            return True
        if (health.get("latest_period"), health.get("latest_date")) != (period, draw_date):
            return True
        if (self_test.get("latest_period"), self_test.get("latest_date")) != (period, draw_date):
            return True
        stamp = datetime.fromisoformat(version["updated_at"])
        if stamp.tzinfo is None:
            return True
        current = now or datetime.now(timezone.utc)
        age_seconds = (current - stamp).total_seconds()
        return age_seconds > MAX_AGE_MINUTES * 60 or age_seconds < -5 * 60
    except (AttributeError, KeyError, TypeError, ValueError):
        return True


def main():
    def read_json(name):
        try:
            return json.loads((ROOT / "reports" / name).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    version = read_json("version.json")
    health = read_json("health_status.json")
    self_test = read_json("self_test_report.json")
    event_name = os.environ.get("EVENT_NAME", "schedule")
    run_repair = should_repair(event_name, version, health, self_test)
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with open(output, "a", encoding="utf-8") as stream:
            stream.write(f"run_repair={str(run_repair).lower()}\n")
    print(json.dumps({"event": event_name, "run_repair": run_repair,
                      "last_report_at": version.get("updated_at")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
