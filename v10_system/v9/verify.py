"""Fail-closed checks for official provenance, causal replay and cloud mirrors."""
from __future__ import annotations

import json
from collections import Counter
from datetime import date, datetime, timedelta, timezone

from .data import DATA_PATH, MANIFEST_PATH, ROOT, load_verified
from .ledger import load_events
from .model import FAIR_SINGLE, as_matrix, candidate_scores, rank, replay


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
    checks["sealed_latest_input_sha"] = bool(forecasts) and forecasts[-1]["official_data_sha256"] == manifest["sha256"]
    analyses = [json.loads((ROOT / name / "latest_analysis.json").read_text(encoding="utf-8")) for name in ("reports", "site", "docs")]
    analysis = analyses[0]
    checks["new_schema_all_mirrors"] = all(item.get("schema") == "marksix_official_v9" and item == analysis for item in analyses)
    checks["report_latest_official"] = analysis["latest_draw"]["period"] == draws[-1].period and analysis["latest_draw"]["source_id"] == draws[-1].source_id
    update_state = analysis.get("update_state", {})
    prior_period = update_state.get("previous_report_period")
    checks["update_state_honest"] = (update_state.get("current_period") == draws[-1].period
                                    and update_state.get("new_draw_since_previous_report") is (prior_period is not None and prior_period != draws[-1].period))
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
    checks["sealed_latest_matches_calculation"] = bool(forecasts) and all(
        forecasts[-1].get(sealed_key) == rerun[model_key]
        for sealed_key, model_key in (("model", "selected_model"), ("single", "single"),
                                      ("top9", "top9"), ("ranking", "rank"))
    )
    checks["report_preserves_sealed_forecast"] = bool(forecasts) and analysis.get("sealed_forecast") == {
        key: value for key, value in forecasts[-1].items() if key != "ranking"
    }
    trace = analysis.get("calculation_trace", {})
    counts = Counter(number for draw in draws[-60:] for number in draw.main)
    previous_counts = Counter(number for draw in draws[-61:-1] for number in draw.main)
    previous_rank = rank(candidate_scores(as_matrix(draws[:-1]))[rerun["selected_model"]])
    checks["calculation_trace_reproducible"] = (
        trace.get("input_sha256") == manifest["sha256"]
        and trace.get("based_on_period") == draws[-1].period
        and trace.get("current_first") == rerun["single"]
        and trace.get("previous_same_model_first") == previous_rank[0]
        and trace.get("last60_main_counts_top9") == {str(number): counts[number] for number in rerun["top9"]}
        and trace.get("previous_first_last60_count") == previous_counts[rerun["single"]]
    )
    audit_claim = analysis.get("full_official_audit", {})
    audit_files = [ROOT / name / "full_official_audit.json" for name in ("reports", "site", "docs")]
    if audit_claim.get("current"):
        audit = json.loads(audit_files[0].read_text(encoding="utf-8"))
        checks["full_official_claim_supported"] = (
            all(path.read_bytes() == audit_files[0].read_bytes() for path in audit_files[1:])
            and audit.get("matched") is True
            and audit.get("stored_csv_sha256") == manifest["sha256"]
            and audit.get("matched_count") == len(draws)
            and audit_claim.get("matched_count") == len(draws)
            and audit_claim.get("checked_at") == audit.get("checked_at")
        )
    else:
        checks["full_official_claim_supported"] = "現版資料尚未完成全量重新抓取比對" in (ROOT / "reports" / "latest_battle_report.html").read_text(encoding="utf-8")
    checks["fair_baseline_correct"] = analysis["model"]["fair_single_rate"] == FAIR_SINGLE
    required = ("index.html", "latest_battle_report.html", "latest_analysis.json", "version.json", "health_status.json", "self_test_report.json", "service-worker.js", "manifest.webmanifest")
    checks["cloud_mirrors_identical"] = all((ROOT / "reports" / name).read_bytes() == (ROOT / "site" / name).read_bytes() == (ROOT / "docs" / name).read_bytes() for name in required)
    model_phrase = "達統計門檻，但仍待前瞻驗證" if analysis["model"]["statistical_edge_passed"] else "未達 0.05 門檻"
    version = json.loads((ROOT / "reports" / "version.json").read_text(encoding="utf-8"))
    from html.parser import HTMLParser
    class ReportMetadata(HTMLParser):
        def __init__(self):
            super().__init__()
            self.values = {}
        def handle_starttag(self, tag, attrs):
            values = dict(attrs)
            if tag == "meta" and values.get("name"):
                self.values[values["name"]] = values.get("content")
    parsed = ReportMetadata()
    parsed.feed((ROOT / "reports" / "latest_battle_report.html").read_text(encoding="utf-8"))
    checks["report_fallback_identity"] = (
        parsed.values.get("marksix-report-version") == version["hash"]
        and parsed.values.get("marksix-report-period") == version["latest_period"]
        and version["updated_at"] == analysis["generated_at"]
    )
    checks["html_discloses_limits"] = all(phrase in (ROOT / "reports" / "latest_battle_report.html").read_text(encoding="utf-8") for phrase in ("不是中獎機率", model_phrase, "官方已定義下一期" if next_evidence else "官方下一期日期暫未"))
    result = {"passed": all(checks.values()), "checked_at": datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds"),
              "latest_period": draws[-1].period, "latest_date": draws[-1].draw_date, "official_rows": len(draws), "checks": checks}
    if not result["passed"]:
        raise RuntimeError(json.dumps(result, ensure_ascii=False))
    return result


if __name__ == "__main__":
    print(json.dumps(verify(), ensure_ascii=False, indent=2))
