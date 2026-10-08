"""Fail-closed checks for official provenance, causal replay and cloud mirrors."""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone

from .data import DATA_PATH, MANIFEST_PATH, ROOT, load_verified
from .ledger import load_events
from .model import FAIR_SINGLE, replay


def verify() -> dict:
    checks: dict[str, bool] = {}
    draws = load_verified()
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    checks["official_only_source"] = manifest["endpoint"] == "https://info.cld.hkjc.com/graphql/base/" and manifest["legacy_data_used_for_model"] is False
    checks["official_row_count"] = len(draws) == manifest["count"] and len(draws) >= 3000
    checks["current_49_ball_era_only"] = draws[0].draw_date >= "2003-01-01" and all(draws[i].draw_date < draws[i + 1].draw_date for i in range(len(draws) - 1))
    checks["latest_within_five_days"] = (datetime.now(timezone(timedelta(hours=8))).date() - date.fromisoformat(draws[-1].draw_date)).days <= 5
    checks["latest_matches_manifest"] = draws[-1].period == manifest["latest_period"] and draws[-1].draw_date == manifest["latest"]
    events = load_events()
    forecasts = [event for event in events if event["kind"] == "forecast"]
    settlements = [event for event in events if event["kind"] == "settlement"]
    checks["append_only_ledger"] = len({event["based_on_period"] for event in forecasts}) == len(forecasts) and len({event["forecast_hash"] for event in settlements}) == len(settlements)
    checks["sealed_latest_basis"] = bool(forecasts) and forecasts[-1]["based_on_period"] == draws[-1].period and forecasts[-1]["based_on_date"] == draws[-1].draw_date
    analyses = [json.loads((ROOT / name / "latest_analysis.json").read_text(encoding="utf-8")) for name in ("reports", "site", "docs")]
    analysis = analyses[0]
    checks["new_schema_all_mirrors"] = all(item.get("schema") == "marksix_official_v9" and item == analysis for item in analyses)
    checks["report_latest_official"] = analysis["latest_draw"]["period"] == draws[-1].period and analysis["latest_draw"]["source_id"] == draws[-1].source_id
    next_evidence = analysis.get("next_draw_evidence")
    checks["no_fabricated_next_date"] = ((analysis["next_draw_date"] is None and "尚未" in analysis["next_draw_date_status"])
                                        or (next_evidence is not None and analysis["next_draw_date"] == next_evidence.get("date")
                                            and next_evidence.get("status") == "Defined" and next_evidence.get("source") == manifest["endpoint"]
                                            and next_evidence["date"] > draws[-1].draw_date))
    now_hkt = datetime.now(timezone(timedelta(hours=8)))
    checks["official_schedule_two_hour_freshness"] = not (next_evidence and next_evidence["date"] <= now_hkt.date().isoformat()
                                                          and (now_hkt.hour, now_hkt.minute) >= (23, 30)
                                                          and draws[-1].draw_date < next_evidence["date"])
    checks["no_fake_high_confidence"] = "高信心" not in analysis["confidence_label"]
    rerun = replay(draws)
    checks["replay_reproducible"] = analysis["model"]["selected_model"] == rerun["selected_model"] and analysis["model"]["rank"] == rerun["rank"] and analysis["model"]["models"] == rerun["models"]
    checks["fair_baseline_correct"] = analysis["model"]["fair_single_rate"] == FAIR_SINGLE
    required = ("index.html", "latest_battle_report.html", "latest_analysis.json", "version.json", "health_status.json", "self_test_report.json", "service-worker.js", "manifest.webmanifest")
    checks["cloud_mirrors_identical"] = all((ROOT / "reports" / name).read_bytes() == (ROOT / "site" / name).read_bytes() == (ROOT / "docs" / name).read_bytes() for name in required)
    model_phrase = "達統計門檻，但仍待前瞻驗證" if analysis["model"]["statistical_edge_passed"] else "未達 0.05 門檻"
    checks["html_discloses_limits"] = all(phrase in (ROOT / "reports" / "latest_battle_report.html").read_text(encoding="utf-8") for phrase in ("不是中獎機率", model_phrase, "官方已定義下一期" if next_evidence else "官方下一期日期暫未"))
    result = {"passed": all(checks.values()), "checked_at": datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds"),
              "latest_period": draws[-1].period, "latest_date": draws[-1].draw_date, "official_rows": len(draws), "checks": checks}
    if not result["passed"]:
        raise RuntimeError(json.dumps(result, ensure_ascii=False))
    return result


if __name__ == "__main__":
    print(json.dumps(verify(), ensure_ascii=False, indent=2))
