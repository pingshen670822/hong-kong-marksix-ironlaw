from __future__ import annotations
import hashlib,json,sys
from datetime import date as _date,datetime,timedelta,timezone
from pathlib import Path
from engine import ROOT,load_draws

if hasattr(sys.stdout,"reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

class date(_date):
    @classmethod
    def today(cls):
        return cls.fromisoformat(datetime.now(timezone(timedelta(hours=8))).date().isoformat())

def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    checks=[]
    def add(name,ok,detail,severity="critical"): checks.append({"name":name,"passed":bool(ok),"severity":severity,"detail":detail})
    draws=load_draws(); analysis=json.loads((ROOT/"reports/latest_analysis.json").read_text(encoding="utf-8"))
    add("official_history_complete",len(draws)>=2152,f"{len(draws)} draws")
    latest_age=(date.today()-date.fromisoformat(draws[-1].draw_date)).days
    add("history_latest_recent",0<=latest_age<=10,f"{draws[-1].period} {draws[-1].draw_date}; age={latest_age} days")
    target=date.fromisoformat(analysis["target_date"])
    add("announced_target_after_latest",target>date.fromisoformat(draws[-1].draw_date),f"{analysis['target_date']} > {draws[-1].draw_date}")
    add("target_not_stale",target>=date.today(),f"target={analysis['target_date']}; today={date.today().isoformat()}")
    add("release_gate",analysis["release_gate"]["passed"],json.dumps(analysis["release_gate"],ensure_ascii=False),"advisory")
    add("walk_forward_520",analysis["backtest"]["main"]["rounds"]==520,str(analysis["backtest"]["main"]["rounds"]))
    add("main_hit_edge",analysis["release_gate"]["main_avg_hits"]>analysis["release_gate"]["main_random_hits"],f"{analysis['release_gate']['main_avg_hits']} > {analysis['release_gate']['main_random_hits']}","advisory")
    recent=analysis["backtest"]["main"]["ensemble_recent_hits"]
    within9_60=analysis["backtest"]["main"]["first_hit_rank_audit"]["60"]["within_9_rate"]
    within9_random=analysis["backtest"]["main"]["within9_random_baseline"]
    add("recent_60_within9_edge",within9_60>=within9_random,f"{within9_60} >= {within9_random}","advisory")
    add("recent_120_hit_edge",recent["120"]>=analysis["release_gate"]["main_random_hits"],f"{recent['120']} >= {analysis['release_gate']['main_random_hits']}","advisory")
    add("new_weighting_v5",analysis["backtest"]["main"].get("weighting_strategy","").startswith("前9碼三層滾動權重v5"),analysis["backtest"]["main"].get("weighting_strategy","missing"))
    rank_audit=analysis["backtest"]["main"].get("first_hit_rank_audit",{})
    add("top9_rank_audit",analysis["backtest"]["main"].get("ranking_target")=="主號前9碼" and all(x in rank_audit for x in ("10","30","60","120")),json.dumps(rank_audit,ensure_ascii=False))
    cc=analysis["backtest"]["main"].get("champion_challenger",{})
    add("champion_challenger_gate",cc.get("promoted") in ("獨支名次共識混合","原機率集成") and "champion" in cc and "challenger" in cc and all("single520" in cc[x] and "single120" in cc[x] for x in ("champion","challenger")),json.dumps(cc,ensure_ascii=False))
    add("rank_consensus_selected",analysis["backtest"]["main"].get("rank_mix") in (0.0,0.65),str(analysis["backtest"]["main"].get("rank_mix")))
    add("special_hit_edge",analysis["release_gate"]["special_avg_hits"]>analysis["release_gate"]["special_random_hits"],f"{analysis['release_gate']['special_avg_hits']} > {analysis['release_gate']['special_random_hits']}","advisory")
    add("no_model_monopoly",analysis["release_gate"]["max_main_weight"]<=.22,str(analysis["release_gate"]["max_main_weight"]),"advisory")
    add("candidate_49",len(analysis["main_rank"])==49 and len(analysis["special_rank"])==49,"main/special 49")
    audit=analysis["backtest"]["main"].get("module_review",[])
    strongest=analysis["backtest"]["main"].get("strongest_single_audit",{})
    add("all_modules_rolling_reviewed",len(audit)==len(analysis["backtest"]["main"]["names"]) and all("decision" in x and "recent_120_avg_hits" in x for x in audit),f"{len(audit)} modules reviewed")
    tournament=analysis["backtest"]["main"].get("confidence_tournament",{})
    winner=tournament.get("winner",{})
    add("all_candidate_confidence_tournament",tournament.get("candidate_count")==49 and tournament.get("confidence_champion")==analysis["packs"]["最強單支"][0] and winner.get("number")==analysis["packs"]["最強單支"][0] and isinstance(winner.get("checks"),dict) and len(winner.get("checks",{}))>=6,json.dumps(tournament,ensure_ascii=False))
    add("strongest_single_unique",strongest.get("number")==analysis["packs"]["最強單支"][0] and strongest.get("target_date")==analysis["target_date"] and analysis.get("decision_rank",[])[0].get("number")==analysis["packs"]["最強單支"][0] and analysis.get("decision_rank",[])[0].get("decision_score",0)>0,json.dumps(strongest,ensure_ascii=False))
    confidence=analysis["backtest"]["main"].get("confidence_audit",{})
    add("strongest_multi_logic_audit",confidence.get("number")==analysis["packs"]["最強單支"][0] and len(confidence.get("checks",{}))>=7 and all(isinstance(v,bool) for v in confidence.get("checks",{}).values()),json.dumps(confidence,ensure_ascii=False))
    trajectory=analysis["backtest"]["main"].get("trajectory_audit",{})
    required_models={"lagged_drag","interval_cycle","lag_trace"}
    required_trajectory_checks=("完整歷史資料至少4000期","520期逐期向前走步驗證","頻率軌跡週期拖牌模組全部執行","每期只使用當時以前資料","候選號碼1至49完整排序")
    trajectory_checks=trajectory.get("checks",{})
    add("daily_single_trajectory_audit",trajectory.get("daily_strongest")==analysis["packs"]["最強單支"][0] and trajectory.get("target_date")==analysis["target_date"] and trajectory.get("walk_forward_rounds")==520 and required_models.issubset(set(analysis["backtest"]["main"].get("names",[]))) and len(trajectory.get("module_groups",[]))==5 and all(trajectory_checks.get(name) is True for name in required_trajectory_checks),json.dumps(trajectory,ensure_ascii=False))
    add("trajectory_confidence_gate",trajectory.get("strict_computation_passed") is True,json.dumps({"unique_candidate":trajectory_checks.get("全候選競賽決策分數唯一第1"),"model_weight_limit":trajectory_checks.get("單一模型權重不超過22%")},ensure_ascii=False),"advisory")
    add("single_accuracy_not_inflated",trajectory.get("walk_forward_single_hits")==sum(int(row.get("single_hit",0)) for row in analysis["backtest"]["main"]["rows"]) and trajectory.get("certified_90_accuracy")==bool(trajectory.get("sealed_independent_draws",0)>=30 and trajectory.get("sealed_wilson_95_lower",0)>=.90),json.dumps({"single_rate":trajectory.get("walk_forward_single_hit_rate"),"sealed_rate":trajectory.get("sealed_single_hit_rate"),"wilson_lower":trajectory.get("sealed_wilson_95_lower"),"certified_90":trajectory.get("certified_90_accuracy")},ensure_ascii=False))
    live=analysis.get("live_single_audit",{})
    add("live_single_accuracy_audit",live.get("independent_draws",0)>0 and live.get("settled_snapshots",0)>=live.get("independent_draws",0) and live.get("duplicate_snapshots_excluded",0)==live.get("settled_snapshots",0)-live.get("independent_draws",0),json.dumps(live,ensure_ascii=False))
    insufficient=live.get("independent_draws",0)<live.get("minimum_independent_samples",30)
    scoped_high_confidence=confidence.get("high_confidence_candidate") is True and "高信心候選" in confidence.get("label","") and "實戰認證累積中" in confidence.get("label","") and trajectory.get("certified_90_accuracy") is False
    add("no_overconfident_single_label",not insufficient or (not confidence.get("super_consensus") and ("樣本累積中" in confidence.get("label","") or scoped_high_confidence)),f"independent={live.get('independent_draws')}; label={confidence.get('label')}")
    proof=analysis.get("recalculation_proof",{})
    add("recalculation_proof",proof.get("current_period")==analysis["latest_draw"]["period"] and proof.get("current_single")==analysis["packs"]["最強單支"][0] and bool(proof.get("completed_at")) and isinstance(proof.get("data_changed"),bool) and isinstance(proof.get("single_changed"),bool),json.dumps(proof,ensure_ascii=False))
    repeat=analysis.get("consecutive_single_audit",{})
    repeat_required=repeat.get("is_consecutive") is True
    repeat_downgraded=(repeat.get("reasonable_repeat_passed") is True or (analysis["release_gate"].get("passed") is False and "連莊驗證未通過" in analysis["release_gate"].get("publish_mode","")))
    add("consecutive_single_rationality",repeat.get("number")==analysis["packs"]["最強單支"][0] and isinstance(repeat.get("reasonable_repeat_passed"),bool) and len(repeat.get("checks",{}))>=6 and (not repeat_required or repeat_downgraded),json.dumps(repeat,ensure_ascii=False))
    add("recommendation_tiers_clear",set(analysis["backtest"]["main"].get("recommendation_tiers",{}))=={"A_唯一最強","B_高信心前三","C_核心前九","D_次高防守","E_低機率暫避"},"A-E tiers")
    add("suggested_sets",len(analysis["suggested_sets"])==8 and all(len(set(x))==6 for x in analysis["suggested_sets"]),"8 valid sets")
    required=["index.html","latest_battle_report.html","latest_analysis.json","prediction_history.json","version.json","style.css","app.js","service-worker.js","manifest.webmanifest"]
    add("artifacts_complete",all((ROOT/base/x).exists() for base in ("reports","site","docs") for x in required),"all report and cloud files")
    add("report_cloud_sync",all(sha(ROOT/"reports"/x)==sha(ROOT/"site"/x)==sha(ROOT/"docs"/x) for x in required),"byte-identical")
    app=(ROOT/"site/app.js").read_text(encoding="utf-8")
    page=(ROOT/"site/index.html").read_text(encoding="utf-8")
    version=json.loads((ROOT/"site/version.json").read_text(encoding="utf-8"))
    workflow=(ROOT/".github/workflows/update.yml").read_text(encoding="utf-8")
    add("mobile_live_refresh",all(x in app for x in ("version.json","no-store","visibilitychange","pageHash","pageGeneratedAt","cloudVersionIsNewer","location.replace")) and f'content="{version["hash"]}"' in page and f'content="{version["updated_at"]}"' in page,"page fingerprint + monotonic timestamp guard + cache-busting reload + 60-second polling + resume refresh")
    add("mobile_manual_controls",all(x in page for x in ('id="manual-refresh"','id="emergency-repair"','id="secure-cloud-update"','id="cloud-action-status"','id="last-manual-update"','actions/workflows/update.yml','更新與重算證據','獨支重算比較','id="proof-completed"','id="proof-comparison"','id="proof-status"')) and all(x in app for x in ("manualRefresh","emergencyRepair","resetClient","cloudSnapshot","latestWorkflowRun","hydrateLatestProof","renderProof","self_test_report.json","prediction_history.json","operational_passed===true","recalculation_proof","重算後維持","cloud-self-repair.yml","localStorage","marksix-last-manual-update","Asia/Taipei","已重抓4個雲端檔")),"cache purge + four accessible cloud files + live recomputation comparison hydration + workflow status + persistent completion time + secure primary/recovery workflow entries")
    navigation=("本期預測","回測驗證","開獎檢討","歷史封存","模型說明","系統健康")
    css=(ROOT/"site/style.css").read_text(encoding="utf-8")
    service_worker=(ROOT/"site/service-worker.js").read_text(encoding="utf-8")
    add("interface_539_spec",all(label in page for label in navigation) and 'class="band strong' in page and 'class="report-details"' in page and all(marker in css for marker in ("#f3f4f6","#7f1017","repeat(6,minmax(0,1fr))",".report-details")),"six 539 categories + red header/nav + band cards + collapsible full calculations")
    target=analysis["target_date"]
    add("ultimate_single_date_bound",all(x in page for x in (f"終極獨支・適用開獎日 {target}",f"{target} 開獎・",f"{target} 終極獨支・全系統守門證據",f"本期終極獨支・{target}",f"{target} 清楚分層推薦")) and all(section.get("target_date")==target for section in (strongest,confidence,trajectory,tournament)),"every current ultimate single carries target draw date and basis")
    add("next_draw_prediction_first",all(x in page for x in ("下期正式預測",f"目標開獎日：{target}",f"終極獨支・適用開獎日 {target}","下期前三排序","下期核心前九","下期主攻12碼","連莊合理性驗證","軌跡・週期・拖牌多重驗證","90%準確度認證","49碼全候選競賽")) and page.index("下期正式預測")<page.index("更新與重算證據") and page.index("下期正式預測")<page.index("封存實戰準確度"),"next target, dated ultimate single, all-candidate audit, basis and main packs are the first prediction block")
    add("version_timezone_explicit",version.get("timezone")=="Asia/Taipei" and "+08:00" in version.get("updated_at","") and "雲端戰報產生" in page,"cloud generation time is explicit Asia/Taipei")
    add("resilient_service_worker","Promise.allSettled" in service_worker and ".addAll(" not in service_worker and "request.method!=='GET'" in service_worker,"one failed asset cannot abort service-worker installation")
    add("version_poll_decoupled","async function fetchVersion" in app and "async function checkVersion(){try{const version=await fetchVersion()" in app,"background version polling does not depend on analysis fetch")
    add("dual_track_governance",analysis.get("operational_policy",{}).get("model_gate_blocks_data") is False,"data sync independent from model gate")
    recovery=ROOT/".github/workflows/cloud-self-repair.yml"
    recovery_text=recovery.read_text(encoding="utf-8")
    add("autonomous_repair",all((ROOT/x).exists() for x in ("watchdog.py","health_check.py","daily_integrity_audit.py")) and recovery.exists() and "watchdog.py" in workflow and "health_check.py" in workflow and "workflow_run" in recovery_text,"primary retry + failure diagnostics + second-layer cloud recovery + integrity audit + health check")
    add("workflow_runtime_current",all(marker in workflow+recovery_text for marker in ("actions/checkout@v7","actions/setup-python@v7")) and "@v4" not in workflow+recovery_text and "@v5" not in workflow+recovery_text,"GitHub Actions use current Node 24 runtime actions")
    banned=["天天樂","tiantianle","Fantasy","California"]
    files=[ROOT/"engine.py",ROOT/"update.py",ROOT/"report.py",ROOT/"README.md",ROOT/"site/index.html",ROOT/"reports/latest_analysis.json"]
    found={term:[str(p.relative_to(ROOT)) for p in files if p.exists() and term.lower() in p.read_text(encoding="utf-8").lower()] for term in banned}
    found={k:v for k,v in found.items() if v}; add("independent_branding",not found,json.dumps(found,ensure_ascii=False))
    critical_passed=all(x["passed"] for x in checks if x["severity"]=="critical")
    prediction_gate_passed=all(x["passed"] for x in checks if x["severity"]=="advisory")
    mode_status=("健康" if prediction_gate_passed else ("系統正常・全模組高信心候選・實戰認證累積中" if confidence.get("high_confidence_candidate") else "系統正常・預測觀察級"))
    report={"system":analysis["system"],"generated_at":analysis["generated_at"],"passed":critical_passed,"operational_passed":critical_passed,"prediction_gate_passed":prediction_gate_passed,"status":mode_status if critical_passed else "系統故障","latest_period":draws[-1].period,"latest_date":draws[-1].draw_date,"target_date":analysis["target_date"],"checks":checks}
    text=json.dumps(report,ensure_ascii=False,indent=2)
    for base in ("reports","site","docs"): (ROOT/base/"self_test_report.json").write_text(text,encoding="utf-8")
    print(text); return 0 if critical_passed else 1
if __name__=="__main__": sys.exit(main())
