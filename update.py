from __future__ import annotations
import csv,json,urllib.parse,urllib.request
from datetime import date
from engine import ROOT,load_draws,analyze
from report import build_reports

API="https://www.mark6six.com/api/draws.php"
CSV_PATH=ROOT/"data"/"official_marksix.csv"
HISTORY_PATH=ROOT/"data"/"prediction_history.json"

def fetch_page(limit=100,offset=0) -> dict:
    q=urllib.parse.urlencode({"limit":limit,"offset":offset,"order":"DESC"})
    req=urllib.request.Request(API+"?"+q,headers={"User-Agent":"Mozilla/5.0 MarkSix-IronLaw/3.0"})
    with urllib.request.urlopen(req,timeout=30) as r: obj=json.load(r)
    if not obj.get("success"): raise RuntimeError("六合彩資料來源回傳失敗")
    return obj

def update_latest() -> int:
    rows=list(csv.DictReader(CSV_PATH.open(encoding="utf-8-sig",newline="")))
    fields=list(rows[0]); by_period={r["period"]:r for r in rows}
    for item in fetch_page(100)["draws"]:
        nums=sorted(map(int,item["numbers"])); special=int(item["extra_number"])
        if len(nums)!=6 or len(set(nums))!=6 or special in nums or not all(1<=n<=49 for n in nums+[special]):
            raise ValueError(f"開獎資料驗證失敗：{item.get('draw_id')}")
        period=str(item["draw_id"]); old=by_period.get(period,{k:"" for k in fields})
        old.update({"period":period,"draw_date":item["draw_date"],**{f"n{i+1}":str(n) for i,n in enumerate(nums)},"special":str(special),"sales_amount":str(item.get("total_turnover") or ""),"source":"mark6six_archive_crosscheck_hkjc","fetched_at":date.today().isoformat()})
        by_period[period]=old
    ordered=sorted(by_period.values(),key=lambda r:r["draw_date"])
    tmp=CSV_PATH.with_suffix(".tmp")
    with tmp.open("w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields); w.writeheader(); w.writerows(ordered)
    tmp.replace(CSV_PATH); return len(ordered)

def settle_and_save(result: dict):
    history=json.loads(HISTORY_PATH.read_text(encoding="utf-8-sig")) if HISTORY_PATH.exists() else []
    draws={d.draw_date:d for d in load_draws()}
    for p in history:
        if p.get("status")!="pending": continue
        actual=draws.get(p["target_date"])
        if actual:
            aset=set(actual.main); p["status"]="settled"; p["actual"]={"period":actual.period,"date":actual.draw_date,"main":actual.main,"special":actual.special}
            p["settlement"]={"pack_hits":{k:{"count":len(aset&set(v)),"numbers":sorted(aset&set(v))} for k,v in p["packs"].items()},"special_hit":actual.special in p["special_packs"]["三碼觀察"],"avoid_errors":{k:sorted(aset&set(v)) for k,v in p["avoid"].items()}}
    if not any(p["based_on_period"]==result["latest_draw"]["period"] for p in history):
        history.append({"created_at":result["generated_at"],"based_on_period":result["latest_draw"]["period"],"based_on_date":result["latest_draw"]["date"],"target_date":result["target_date"],"status":"pending","packs":result["packs"],"special_packs":result["special_packs"],"avoid":result["avoid"],"suggested_sets":result["suggested_sets"]})
    HISTORY_PATH.write_text(json.dumps(history,ensure_ascii=False,indent=2),encoding="utf-8")
    return history

def main():
    count=update_latest(); result=analyze(load_draws())
    history=settle_and_save(result); build_reports(result,history)
    print(json.dumps({"draws":count,"latest":result["latest_draw"],"target":result["target_date"],"gate":result["release_gate"]},ensure_ascii=False,indent=2))
if __name__=="__main__": main()
