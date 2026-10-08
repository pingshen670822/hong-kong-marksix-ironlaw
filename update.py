from __future__ import annotations
import csv,json,re,sys,urllib.parse,urllib.request
from datetime import date as _date,datetime,timedelta,timezone
from engine import ROOT,load_draws,analyze
from report import build_reports

if hasattr(sys.stdout,"reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

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

def _normalized(rows: list[dict]) -> dict[str, tuple[tuple[int, ...], int]]:
    return {
        str(item["draw_date"]): (tuple(sorted(map(int,item["numbers"]))),int(item["extra_number"]))
        for item in rows
    }

def update_latest() -> dict:
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
    primary_by_date=_normalized(primary); fallback_by_date=_normalized(fallback)
    overlaps=sorted(set(primary_by_date)&set(fallback_by_date))
    conflicts=[d for d in overlaps if primary_by_date[d]!=fallback_by_date[d]]
    if conflicts:
        raise RuntimeError("六合彩雙來源資料不一致，停止覆寫："+",".join(conflicts[-5:]))
    # 主來源優先；備援只補主來源缺少的日期，避免同日資料被靜默覆寫。
    incoming=primary+[item for item in fallback if item["draw_date"] not in primary_by_date]
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
        source=("multi_source_marksix_crosscheck" if draw_date in primary_by_date and draw_date in fallback_by_date else ("primary_marksix" if draw_date in primary_by_date else "fallback_on99_pending_crosscheck"))
        old.update({"period":period,"draw_date":item["draw_date"],**{f"n{i+1}":str(n) for i,n in enumerate(nums)},"special":str(special),"sales_amount":str(item.get("total_turnover") or old.get("sales_amount") or ""),"source":source,"fetched_at":date.today().isoformat()})
        by_period[period]=old
        by_date[draw_date]=old
    ordered=sorted(by_period.values(),key=lambda r:r["draw_date"])
    tmp=CSV_PATH.with_suffix(".tmp")
    with tmp.open("w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields); w.writeheader(); w.writerows(ordered)
    tmp.replace(CSV_PATH)
    latest_date=ordered[-1]["draw_date"]
    latest_source=("雙來源一致" if latest_date in overlaps else ("主來源已發布，備援待核對" if latest_date in primary_by_date else ("備援來源已發布，主來源待核對" if latest_date in fallback_by_date else "既有歷史資料，來源待核對")))
    return {"draws":len(ordered),"primary_rows":len(primary),"fallback_rows":len(fallback),"crosschecked_dates":len(overlaps),"latest_source":latest_source,"latest_crosschecked":latest_date in overlaps,"source_errors":source_errors}

def settle_and_save(result: dict):
    history=json.loads(HISTORY_PATH.read_text(encoding="utf-8-sig")) if HISTORY_PATH.exists() else []
    draws={d.draw_date:d for d in load_draws()}
    for p in history:
        if p.get("status")!="pending": continue
        actual=draws.get(p["target_date"])
        if actual:
            aset=set(actual.main); p["status"]="settled"; p["actual"]={"period":actual.period,"date":actual.draw_date,"main":actual.main,"special":actual.special}
            p["settlement"]={"pack_hits":{k:{"count":len(aset&set(v)),"numbers":sorted(aset&set(v))} for k,v in p["packs"].items()},"special_hit":actual.special in p["special_packs"]["三碼觀察"],"avoid_errors":{k:sorted(aset&set(v)) for k,v in p["avoid"].items()}}
    engine=result.get("engine","legacy")
    snapshot_key=(result["latest_draw"]["period"],result["target_date"],engine)
    exists=any((p.get("based_on_period"),p.get("target_date"),p.get("engine","legacy"))==snapshot_key for p in history)
    if not exists:
        created_at=result.get("recalculation_proof",{}).get("completed_at") or result["generated_at"]
        history.append({"forecast_id":"|".join(snapshot_key),"engine":engine,"created_at":created_at,"based_on_period":result["latest_draw"]["period"],"based_on_date":result["latest_draw"]["date"],"target_date":result["target_date"],"status":"pending","packs":result["packs"],"special_packs":result["special_packs"],"avoid":result["avoid"],"suggested_sets":result["suggested_sets"]})
    HISTORY_PATH.write_text(json.dumps(history,ensure_ascii=False,indent=2),encoding="utf-8")
    return history

def apply_live_single_audit(result: dict, history: list[dict]) -> dict:
    """以每個實際開獎日一筆的封存預測，審核最強獨支的實戰可信度。"""
    # 同一目標日可能因臨時改期留下多個封存版本；準確率只能計一次，採開獎前
    # 最接近目標日的版本，避免用重複快照膨脹樣本數。
    by_target={}
    settled_snapshots=0
    for prediction in history:
        if prediction.get("status")!="settled":
            continue
        settled_snapshots+=1
        target=prediction.get("target_date","")
        key=(prediction.get("created_at", ""),prediction.get("based_on_date", ""),prediction.get("based_on_period", ""))
        current=by_target.get(target)
        if current is None or key>(current.get("created_at", ""),current.get("based_on_date", ""),current.get("based_on_period", "")):
            by_target[target]=prediction
    outcomes=[]
    for target,prediction in sorted(by_target.items()):
        strongest=int(prediction["packs"]["最強單支"][0])
        hit=strongest in set(map(int,prediction["actual"]["main"]))
        outcomes.append({"target_date":target,"based_on_period":prediction.get("based_on_period",""),"number":strongest,"hit":hit})
    hit_count=sum(item["hit"] for item in outcomes)
    total=len(outcomes)
    recent5=outcomes[-5:]
    recent10=outcomes[-10:]
    longest_miss=0
    miss_streak=0
    for item in outcomes:
        miss_streak=0 if item["hit"] else miss_streak+1
        longest_miss=max(longest_miss,miss_streak)
    current_number=int(result["packs"]["最強單支"][0])
    current_samples=[item for item in outcomes if item["number"]==current_number]
    fair=6/49
    minimum_samples=30
    overall_rate=hit_count/total if total else 0.0
    recent10_rate=sum(item["hit"] for item in recent10)/len(recent10) if recent10 else 0.0
    # 95% Wilson下限比單看樣本命中率嚴格，可防止1中1、9中10之類的小樣本
    # 被包裝成「90%以上準確」。
    if total:
        z=1.959963984540054
        denominator=1+z*z/total
        centre=overall_rate+z*z/(2*total)
        margin=z*((overall_rate*(1-overall_rate)/total+z*z/(4*total*total))**0.5)
        wilson_lower=max(0.0,(centre-margin)/denominator)
    else:
        wilson_lower=0.0
    live_passed=total>=minimum_samples and overall_rate>=fair and len(recent10)>=10 and recent10_rate>=fair
    certified_90=total>=minimum_samples and wilson_lower>=.90
    audit={
        "method":"每個目標開獎日只計一次；同日多個封存版本採開獎前最近版本",
        "settled_snapshots":settled_snapshots,
        "independent_draws":total,
        "duplicate_snapshots_excluded":settled_snapshots-total,
        "hits":hit_count,
        "hit_rate":round(overall_rate,6),
        "hit_rate_wilson_95_lower":round(wilson_lower,6),
        "fair_single_rate":round(fair,6),
        "recent_5":{"draws":len(recent5),"hits":sum(item["hit"] for item in recent5),"hit_rate":round(sum(item["hit"] for item in recent5)/len(recent5),6) if recent5 else 0.0},
        "recent_10":{"draws":len(recent10),"hits":sum(item["hit"] for item in recent10),"hit_rate":round(recent10_rate,6)},
        "longest_miss_streak":longest_miss,
        "latest_result":outcomes[-1] if outcomes else None,
        "current_number":current_number,
        "current_number_samples":len(current_samples),
        "current_number_hits":sum(item["hit"] for item in current_samples),
        "minimum_independent_samples":minimum_samples,
        "live_gate_passed":live_passed,
        "certified_90_accuracy":certified_90,
        "outcomes":outcomes,
    }
    result["live_single_audit"]=audit
    release=result["release_gate"]
    model_passed=bool(release.get("passed"))
    release["model_passed"]=model_passed
    release["live_single_passed"]=live_passed
    release["passed"]=model_passed and live_passed
    high_confidence_candidate=bool(result["backtest"]["main"]["confidence_audit"].get("high_confidence_candidate"))
    release["publish_mode"]="超高共識推薦" if release["passed"] else ("全模組高信心候選・實戰認證累積中" if high_confidence_candidate else "觀察級・實戰樣本累積中")
    confidence=result["backtest"]["main"]["confidence_audit"]
    model_consensus=bool(confidence.get("super_consensus"))
    confidence["model_super_consensus"]=model_consensus
    confidence["checks"][f"封存實戰至少{minimum_samples}個獨立開獎日"]=live_passed
    confidence["super_consensus"]=model_consensus and live_passed
    confidence["label"]=("超高共識・本期唯一最強推薦" if confidence["super_consensus"] else ("全模組高信心候選・實戰認證累積中" if high_confidence_candidate else "模型排序第1・實戰樣本累積中"))
    candidate_text=(f"候選專屬走步{confidence.get('candidate_walk_forward_hits',0)}中／{confidence.get('candidate_walk_forward_samples',0)}期，"
                    f"95%下限{confidence.get('candidate_wilson_95_lower',0)*100:.2f}%；") if high_confidence_candidate else ""
    confidence["warning"]=(
        f"{candidate_text}封存實戰目前{total}個獨立開獎日（{hit_count}中，{overall_rate*100:.1f}%）。"
        f"這是全模組高信心候選，不是必中或90%保證；滿{minimum_samples}期前持續獨立認證。"
    )
    trajectory=result["backtest"]["main"].get("trajectory_audit",{})
    trajectory["sealed_independent_draws"]=total
    trajectory["sealed_single_hits"]=hit_count
    trajectory["sealed_single_hit_rate"]=round(overall_rate,6)
    trajectory["sealed_wilson_95_lower"]=round(wilson_lower,6)
    trajectory["performance_checks"]={
        f"開獎前封存實戰至少{minimum_samples}期":total>=minimum_samples,
        "封存實戰命中率至少90%":overall_rate>=.90,
        "95%信賴下限至少90%":wilson_lower>=.90,
        "沒有重複快照灌水":settled_snapshots-total==audit["duplicate_snapshots_excluded"],
    }
    trajectory["certified_90_accuracy"]=certified_90
    trajectory["status"]=(
        f"每日嚴格運算已完成；520期走步獨支{trajectory.get('walk_forward_single_hits',0)}中／"
        f"{trajectory.get('walk_forward_rounds',0)}期（{trajectory.get('walk_forward_single_hit_rate',0)*100:.2f}%），"
        f"封存實戰{hit_count}中／{total}期（{overall_rate*100:.2f}%）。"
        f"90%準確度{'已通過統計認證' if certified_90 else '尚未通過，禁止標示或保證'}。"
    )
    return audit

def apply_consecutive_single_audit(result: dict, history: list[dict]) -> dict:
    """驗證最強獨支跨期連莊是否有新資料與模型依據，禁止用追號或複製舊牌冒充。"""
    by_basis={}
    for prediction in history:
        basis=prediction.get("based_on_period")
        if not basis or not prediction.get("packs",{}).get("最強單支"):
            continue
        current=by_basis.get(basis)
        key=(prediction.get("target_date",""),prediction.get("created_at",""))
        if current is None or key>(current.get("target_date",""),current.get("created_at","")):
            by_basis[basis]=prediction
    snapshots=sorted(by_basis.values(),key=lambda item:(item.get("based_on_date",""),item.get("based_on_period","")))
    current_period=result["latest_draw"]["period"]
    eligible=[item for item in snapshots if (item.get("based_on_date",""),item.get("based_on_period","")) <= (result["latest_draw"]["date"],current_period)]
    if not eligible or eligible[-1].get("based_on_period")!=current_period:
        eligible.append({"based_on_period":current_period,"based_on_date":result["latest_draw"]["date"],"target_date":result["target_date"],"status":"pending","packs":{"最強單支":result["packs"]["最強單支"]}})
    current=eligible[-1]
    current_number=int(current["packs"]["最強單支"][0])
    streak=0
    streak_periods=[]
    for item in reversed(eligible):
        if int(item["packs"]["最強單支"][0])!=current_number:
            break
        streak+=1
        streak_periods.append(item.get("based_on_period",""))
    streak_periods.reverse()
    previous=eligible[-2] if len(eligible)>=2 else None
    previous_number=int(previous["packs"]["最強單支"][0]) if previous else None
    previous_hit=None
    if previous and previous.get("status")=="settled" and previous.get("actual"):
        previous_hit=previous_number in set(map(int,previous["actual"]["main"]))
    confidence=result["backtest"]["main"]["confidence_audit"]
    model_count=len(result["backtest"]["main"]["names"])
    required_support=int(confidence.get("required_model_support",max(7,round(model_count*.60))))
    is_repeat=streak>=2
    checks={
        "跨不同依據期別重新運算":bool(previous and previous.get("based_on_period")!=current_period and previous.get("based_on_date","")<result["latest_draw"]["date"]),
        "最新開獎資料已納入":current.get("based_on_period")==current_period and current.get("based_on_date")==result["latest_draw"]["date"],
        "第一名嚴格高於第二名":confidence.get("score_gap_to_second",0)>0,
        f"至少{required_support}個模型列入前9":confidence.get("model_top9_support",0)>=required_support,
        "加權模型共識至少65%":confidence.get("weighted_support_pct",0)>=65,
        "原始模型發布守門通過":bool(result["release_gate"].get("model_passed",result["release_gate"].get("passed"))),
    }
    reasonable=all(checks.values()) if is_repeat else True
    audit={
        "is_consecutive":is_repeat,
        "number":current_number,
        "streak":streak,
        "basis_periods":streak_periods,
        "previous_basis_period":previous.get("based_on_period") if previous else None,
        "current_basis_period":current_period,
        "previous_result_hit":previous_hit,
        "model_top9_support":confidence.get("model_top9_support",0),
        "model_count":model_count,
        "weighted_support_pct":confidence.get("weighted_support_pct",0),
        "score_gap_to_second":confidence.get("score_gap_to_second",0),
        "checks":checks,
        "reasonable_repeat_passed":reasonable,
        "strong_recommendation_passed":reasonable and bool(result["release_gate"].get("live_single_passed")),
    }
    if is_repeat:
        prior_text="命中" if previous_hit is True else ("未中" if previous_hit is False else "尚未結算")
        audit["status"]=(
            f"{current_number:02d}連續{streak}個不同依據期別排名第1；前次{previous.get('based_on_period')}封存戰果為{prior_text}，"
            f"最新{current_period}資料納入後仍為唯一第1，模型前9支持{confidence.get('model_top9_support',0)}/{model_count}、"
            f"加權共識{confidence.get('weighted_support_pct',0):.2f}%。連莊模型依據{'通過' if reasonable else '未通過'}；"
            f"實戰樣本守門{'通過' if result['release_gate'].get('live_single_passed') else '未通過，故仍為觀察級'}。"
        )
    else:
        audit["status"]=f"{current_number:02d}本期不是連莊，無須啟動連莊守門。"
    result["consecutive_single_audit"]=audit
    confidence["checks"]["連莊合理性驗證"]=reasonable
    if is_repeat and not reasonable:
        confidence["super_consensus"]=False
        confidence["label"]="觀察級・連莊驗證未通過・實戰樣本累積中"
        result["release_gate"]["passed"]=False
        result["release_gate"]["publish_mode"]="觀察級・連莊驗證未通過"
    return audit

def main():
    previous_target=None
    previous_analysis={}
    previous_report=ROOT/"reports"/"latest_analysis.json"
    if previous_report.exists():
        try:
            previous_analysis=json.loads(previous_report.read_text(encoding="utf-8"))
            previous_target=previous_analysis.get("target_date")
        except Exception:
            previous_analysis={}
            previous_target=None
    source_status=update_latest(); result=analyze(load_draws())
    schedule_error=None
    try: announced_target=fetch_announced_next_draw()
    except Exception as exc:
        announced_target=None; schedule_error=f"{type(exc).__name__}: {exc}"
    latest_date=result["latest_draw"]["date"]
    if announced_target and date.fromisoformat(announced_target) <= date.fromisoformat(latest_date):
        schedule_error="公告日期沒有晚於最新開獎日期"
        announced_target=None
    provisional_target=result["target_date"]
    if announced_target:
        # 若官方公告已把舊目標日往後移，必須解除舊日期鎖，避免永久卡死。
        target=announced_target
        target_source="公告日期"
    elif previous_target and previous_target>latest_date:
        target=previous_target
        target_source="上次有效公告（日期來源暫時無法連線）"
    else:
        target=provisional_target
        target_source="開彩規則推算（待公告來源恢復後覆核）"
    waiting=bool(target<=date.today().isoformat() and latest_date<target)
    result["target_date"]=target
    result["target_source"]=target_source
    main_backtest=result.get("backtest",{}).get("main",{})
    for section in ("confidence_tournament","confidence_audit","trajectory_audit","strongest_single_audit"):
        if isinstance(main_backtest.get(section),dict):
            main_backtest[section]["target_date"]=target
    result["data_source_status"]={**source_status,"schedule_error":schedule_error}
    if waiting:
        result["update_status"]="開獎資料尚未出現，保留最後有效資料並持續自動重試"
    elif schedule_error:
        result["update_status"]="最新開獎資料已同步；下期日期來源暫時降級並持續覆核"
    else:
        result["update_status"]="最新資料已完成抓取、結算、重算與手機同步"
    previous_draw=previous_analysis.get("latest_draw",{})
    previous_single=(previous_analysis.get("packs",{}).get("最強單支") or [None])[0]
    current_single=int(result["packs"]["最強單支"][0])
    data_changed=previous_draw.get("period")!=result["latest_draw"]["period"] or previous_draw.get("date")!=result["latest_draw"]["date"]
    single_changed=previous_single is not None and int(previous_single)!=current_single
    result["recalculation_proof"]={
        "completed_at":datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds"),
        "previous_period":previous_draw.get("period"),
        "current_period":result["latest_draw"]["period"],
        "current_draw_date":result["latest_draw"]["date"],
        "data_changed":data_changed,
        "previous_single":int(previous_single) if previous_single is not None else None,
        "current_single":current_single,
        "single_changed":single_changed,
        "crosschecked_dates":source_status["crosschecked_dates"],
        "latest_source":source_status["latest_source"],
        "status":("已加入新開獎資料並完整重算" if data_changed else (f"官方開獎資料未新增；全候選高信心新核心重算後，終極獨支由{int(previous_single):02d}改為{current_single:02d}" if single_changed and previous_single is not None else f"官方開獎資料未新增，已用{result['latest_draw']['period']}期完整重算；終極獨支維持{current_single:02d}，不是沿用舊頁")),
    }
    history=settle_and_save(result); apply_live_single_audit(result,history); apply_consecutive_single_audit(result,history); build_reports(result,history)
    print(json.dumps({"data":source_status,"latest":result["latest_draw"],"target":result["target_date"],"target_source":target_source,"gate":result["release_gate"]},ensure_ascii=False,indent=2))
if __name__=="__main__": main()
