from __future__ import annotations
import hashlib,json,sys
from pathlib import Path
from engine import ROOT,load_draws

def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    checks=[]
    def add(name,ok,detail): checks.append({"name":name,"passed":bool(ok),"detail":detail})
    draws=load_draws(); analysis=json.loads((ROOT/"reports/latest_analysis.json").read_text(encoding="utf-8"))
    add("official_history_complete",len(draws)>=2152,f"{len(draws)} draws")
    add("official_history_latest",draws[-1].draw_date=="2026-07-14",f"{draws[-1].period} {draws[-1].draw_date}")
    add("release_gate",analysis["release_gate"]["passed"],json.dumps(analysis["release_gate"],ensure_ascii=False))
    add("walk_forward_520",analysis["backtest"]["main"]["rounds"]==520,str(analysis["backtest"]["main"]["rounds"]))
    add("main_hit_edge",analysis["release_gate"]["main_avg_hits"]>analysis["release_gate"]["main_random_hits"],f"{analysis['release_gate']['main_avg_hits']} > {analysis['release_gate']['main_random_hits']}")
    add("special_hit_edge",analysis["release_gate"]["special_avg_hits"]>analysis["release_gate"]["special_random_hits"],f"{analysis['release_gate']['special_avg_hits']} > {analysis['release_gate']['special_random_hits']}")
    add("no_model_monopoly",analysis["release_gate"]["max_main_weight"]<=.30,str(analysis["release_gate"]["max_main_weight"]))
    add("candidate_49",len(analysis["main_rank"])==49 and len(analysis["special_rank"])==49,"main/special 49")
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
