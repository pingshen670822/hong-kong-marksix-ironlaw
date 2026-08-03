from __future__ import annotations
import csv,json,re,urllib.parse,urllib.request
from datetime import date as _date,datetime,timedelta,timezone
from engine import ROOT,load_draws,analyze
from report import build_reports

API="https://www.mark6six.com/api/draws.php"
NEXT_DRAW_URL="https://mark6.app/live"
CSV_PATH=ROOT/"data"/"official_marksix.csv"
HISTORY_PATH=ROOT/"data"/"prediction_history.json"

class date(_date):
    @classmethod
    def today(cls):
        return cls.fromisoformat(datetime.now(timezone(timedelta(hours=8))).date().isoformat())

def fetch_page(limit=100,offset=0) -> dict:
    q=urllib.parse.urlencode({"limit":limit,"offset":offset,"order":"DESC"})
    req=urllib.request.Request(API+"?"+q,headers={"User-Agent":"Mozilla/5.0 MarkSix-IronLaw/3.0"})
    with urllib.request.urlopen(req,timeout=30) as r: obj=json.load(r)
    if not obj.get("success"): raise RuntimeError("六合彩資料來源回傳失敗")
    return obj

def fetch_on99_year(year: int) -> list[dict]:
    """備援資料源：解析頁面內嵌的結構化開獎資料。"""
    url=f"https://on99.life/lottery/history/{year}"
    req=urllib.request.Request(url,headers={"User-Agent":"Mozilla/5.0 MarkSix-IronLaw/3.1"})
    with urllib.request.urlopen(req,timeout=30) as r: text=r.read().decode("utf-8")
    pattern=r'\{\\?"drawDate\\?":\\?"(\d{4}-\d{2}-\d{2})\\?",\\?"winningNumbers\\?":\[([0-9,]+)\],\\?"extraNumber\\?":([0-9]+),\\?"drawId\\?":\\?"([^"\\]+)'
    out=[]
    for draw_date,numbers,extra,draw_id in re.findall(pattern,text):
        out.append({"draw_date":draw_date,"numbers":[int(x) for x in numbers.split(",")],"extra_number":int(extra),"draw_id":draw_id})
    if not out: raise RuntimeError("六合彩備援資料解析失敗")
    return out

def fetch_announced_next_draw() -> str:
    """讀取已公告的下期截止售票日，避免節慶或金多寶改期時誤判。"""
    req=urllib.request.Request(NEXT_DRAW_URL,headers={"User-Agent":"Mozilla/5.0 MarkSix-IronLaw/4.0"})
    with urllib.request.urlopen(req,timeout=30) as r: text=r.read().decode("utf-8","replace")
    m=re.search(r"下期截止售票[：:]\s*(\d{4})年(\d{1,2})月(\d{1,2})日",text)
    if not m: raise RuntimeError("無法取得已公告的下一期日期；鐵律禁止用錯誤日期發布")
    return f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"

def update_latest() -> int:
    raw_rows=list(csv.DictReader(CSV_PATH.open(encoding="utf-8-sig",newline="")))
    fields=list(raw_rows[0])
    # 同一開彩日可能在不同來源帶有節慶後綴；保留資訊較完整的正式期別。
    clean_by_date={}
    for row in raw_rows:
        old=clean_by_date.get(row["draw_date"])
        if old is None or len(row["period"])>len(old["period"]): clean_by_date[row["draw_date"]]=row
    rows=list(clean_by_date.values())
    by_period={r["period"]:r for r in rows}; by_date={r["draw_date"]:r for r in rows}
    source_errors=[]
    try: primary=fetch_page(100)["draws"]
    except Exception as exc:
        primary=[]; source_errors.append(f"primary:{type(exc).__name__}")
    try: fallback=fetch_on99_year(date.today().year)
    except Exception as exc:
        fallback=[]; source_errors.append(f"fallback:{type(exc).__name__}")
    incoming=primary+fallback
    if not incoming:
        raise RuntimeError("所有六合彩開獎資料源同時失敗；鐵律禁止使用舊資料假裝更新："+",".join(source_errors))
    for item in incoming:
        nums=sorted(map(int,item["numbers"])); special=int(item["extra_number"])
        if len(nums)!=6 or len(set(nums))!=6 or special in nums or not all(1<=n<=49 for n in nums+[special]):
            raise ValueError(f"開獎資料驗證失敗：{item.get('draw_id')}")
        draw_date=item["draw_date"]
        same_day=by_date.get(draw_date)
        period=same_day["period"] if same_day else str(item["draw_id"])
        old=by_period.get(period,{k:"" for k in fields})
        old.update({"period":period,"draw_date":item["draw_date"],**{f"n{i+1}":str(n) for i,n in enumerate(nums)},"special":str(special),"sales_amount":str(item.get("total_turnover") or old.get("sales_amount") or ""),"source":"multi_source_marksix_crosscheck","fetched_at":date.today().isoformat()})
        by_period[period]=old
        by_date[draw_date]=old
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
    announced_target=fetch_announced_next_draw()
    if date.fromisoformat(announced_target) <= date.fromisoformat(result["latest_draw"]["date"]):
        raise RuntimeError("下一期公告日期沒有晚於最新開獎日期；鐵律禁止發布")
    result["target_date"]=announced_target
    history=settle_and_save(result); build_reports(result,history)
    print(json.dumps({"draws":count,"latest":result["latest_draw"],"target":result["target_date"],"gate":result["release_gate"]},ensure_ascii=False,indent=2))
if __name__=="__main__": main()
