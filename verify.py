from __future__ import annotations
import hashlib,json,sys
from datetime import date as _date,datetime,timedelta,timezone
from pathlib import Path
from engine import ROOT,load_draws

class date(_date):
    @classmethod
    def today(cls):
        return cls.fromisoformat(datetime.now(timezone(timedelta(hours=8))).date().isoformat())

def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    checks=[]
    def add(name,ok,detail): checks.append({"name":name,"passed":bool(ok),"detail":detail})
    draws=load_draws(); analysis=json.loads((ROOT/"reports/latest_analysis.json").read_text(encoding="utf-8"))
    add("official_history_complete",len(draws)>=2152,f"{len(draws)} draws")
    latest_age=(date.today()-date.fromisoformat(draws[-1].draw_date)).days
    add("history_latest_recent",0<=latest_age<=10,f"{draws[-1].period} {draws[-1].draw_date}; age={latest_age} days")
    target=date.fromisoformat(analysis["target_date"])
    add("announced_target_after_latest",target>date.fromisoformat(draws[-1].draw_date),f"{analysis['target_date']} > {draws[-1].draw_date}")
    add("target_not_stale",target>=date.today(),f"target={analysis['target_date']}; today={date.today().isoformat()}")
    add("release_gate",analysis["release_gate"]["passed"],json.dumps(analysis["release_gate"],ensure_ascii=False))
    add("walk_forward_520",analysis["backtest"]["main"]["rounds"]==520,str(analysis["backtest"]["main"]["rounds"]))
    add("main_hit_edge",analysis["release_gate"]["main_avg_hits"]>analysis["release_gate"]["main_random_hits"],f"{analysis['release_gate']['main_avg_hits']} > {analysis['release_gate']['main_random_hits']}")
    recent=analysis["backtest"]["main"]["ensemble_recent_hits"]
    within9_60=analysis["backtest"]["main"]["first_hit_rank_audit"]["60"]["within_9_rate"]
    within9_random=analysis["backtest"]["main"]["within9_random_baseline"]
    add("recent_60_within9_edge",within9_60>=within9_random,f"{within9_60} >= {within9_random}")
    add("recent_120_hit_edge",recent["120"]>=analysis["release_gate"]["main_random_hits"],f"{recent['120']} >= {analysis['release_gate']['main_random_hits']}")
    add("new_weighting_v5",analysis["backtest"]["main"].get("weighting_strategy","").startswith("前9碼三層滾動權重v5"),analysis["backtest"]["main"].get("weighting_strategy","missing"))
    rank_audit=analysis["backtest"]["main"].get("first_hit_rank_audit",{})
    add("top9_rank_audit",analysis["backtest"]["main"].get("ranking_target")=="主號前9碼" and all(x in rank_audit for x in ("10","30","60","120")),json.dumps(rank_audit,ensure_ascii=False))
    cc=analysis["backtest"]["main"].get("champion_challenger",{})
    add("champion_challenger_gate",cc.get("promoted") in ("名次共識混合","原機率集成") and "champion" in cc and "challenger" in cc,json.dumps(cc,ensure_ascii=False))
    add("rank_consensus_selected",analysis["backtest"]["main"].get("rank_mix") in (0.0,0.5),str(analysis["backtest"]["main"].get("rank_mix")))
    add("special_hit_edge",analysis["release_gate"]["special_avg_hits"]>analysis["release_gate"]["special_random_hits"],f"{analysis['release_gate']['special_avg_hits']} > {analysis['release_gate']['special_random_hits']}")
    add("no_model_monopoly",analysis["release_gate"]["max_main_weight"]<=.22,str(analysis["release_gate"]["max_main_weight"]))
    add("candidate_49",len(analysis["main_rank"])==49 and len(analysis["special_rank"])==49,"main/special 49")
    audit=analysis["backtest"]["main"].get("module_review",[])
    strongest=analysis["backtest"]["main"].get("strongest_single_audit",{})
    add("all_modules_rolling_reviewed",len(audit)==len(analysis["backtest"]["main"]["names"]) and all("decision" in x and "recent_120_avg_hits" in x for x in audit),f"{len(audit)} modules reviewed")
    add("strongest_single_unique",strongest.get("number")==analysis["packs"]["最強單支"][0] and analysis["main_rank"][0]["probability"]>analysis["main_rank"][1]["probability"],json.dumps(strongest,ensure_ascii=False))
    add("suggested_sets",len(analysis["suggested_sets"])==8 and all(len(set(x))==6 for x in analysis["suggested_sets"]),"8 valid sets")
    required=["index.html","latest_battle_report.html","latest_analysis.json","prediction_history.json","version.json","style.css","app.js","service-worker.js","manifest.webmanifest"]
    add("artifacts_complete",all((ROOT/base/x).exists() for base in ("reports","site","docs") for x in required),"all report and cloud files")
    add("report_cloud_sync",all(sha(ROOT/"reports"/x)==sha(ROOT/"site"/x)==sha(ROOT/"docs"/x) for x in required),"byte-identical")
    banned=["天天樂","tiantianle","Fantasy","California"]
    files=[ROOT/"engine.py",ROOT/"update.py",ROOT/"report.py",ROOT/"README.md",ROOT/"site/index.html",ROOT/"reports/latest_analysis.json"]
    found={term:[str(p.relative_to(ROOT)) for p in files if p.exists() and term.lower() in p.read_text(encoding="utf-8").lower()] for term in banned}
    found={k:v for k,v in found.items() if v}; add("independent_branding",not found,json.dumps(found,ensure_ascii=False))
    report={"system":analysis["system"],"generated_at":analysis["generated_at"],"passed":all(x["passed"] for x in checks),"latest_period":draws[-1].period,"latest_date":draws[-1].draw_date,"target_date":analysis["target_date"],"checks":checks}
    text=json.dumps(report,ensure_ascii=False,indent=2)
    for base in ("reports","site","docs"): (ROOT/base/"self_test_report.json").write_text(text,encoding="utf-8")
    print(text); return 0 if report["passed"] else 1
if __name__=="__main__": sys.exit(main())
