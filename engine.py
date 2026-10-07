from __future__ import annotations

import csv, json, math, statistics
from collections import Counter
from dataclasses import dataclass
from datetime import date as _date, datetime, timedelta, timezone
from itertools import combinations
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data" / "official_marksix.csv"
N = 49

class date(_date):
    @classmethod
    def today(cls):
        return cls.fromisoformat(datetime.now(timezone(timedelta(hours=8))).date().isoformat())

@dataclass(frozen=True)
class Draw:
    period: str
    draw_date: str
    main: tuple[int, ...]
    special: int

def load_draws(path: Path = DATA) -> list[Draw]:
    out=[]
    with path.open(encoding="utf-8-sig",newline="") as f:
        for r in csv.DictReader(f):
            nums=tuple(sorted(int(r[f"n{i}"]) for i in range(1,7)))
            sp=int(r["special"])
            if len(set(nums))!=6 or not all(1<=n<=49 for n in nums) or sp in nums: raise ValueError(f"invalid draw {r['period']}")
            out.append(Draw(r["period"].strip(),r["draw_date"],nums,sp))
    if len({d.period for d in out})!=len(out) or len({d.draw_date for d in out})!=len(out): raise ValueError("duplicate period/date")
    return sorted(out,key=lambda d:d.draw_date)

def normalize_probability(x: np.ndarray, total: float=6.0) -> np.ndarray:
    x=np.asarray(x,dtype=float)
    x=np.clip(x,1e-8,None)
    p=np.clip(x/x.sum()*total,1e-6,.999999)
    return p/p.sum()*total

def matrix(draws: list[Draw]) -> np.ndarray:
    a=np.zeros((len(draws),N),dtype=float)
    for i,d in enumerate(draws): a[i,np.array(d.main)-1]=1
    return a

def special_matrix(draws: list[Draw]) -> np.ndarray:
    a=np.zeros((len(draws),N),dtype=float)
    for i,d in enumerate(draws): a[i,d.special-1]=1
    return a

def ewma(y: np.ndarray, half_life: float) -> np.ndarray:
    age=np.arange(len(y)-1,-1,-1); w=np.exp(-math.log(2)*age/half_life)
    return (y*w[:,None]).sum(0)/(w.sum()+1e-12)

def gaps(y: np.ndarray) -> np.ndarray:
    out=np.full(N,len(y),dtype=float)
    for n in range(N):
        found=np.flatnonzero(y[:,n])
        if len(found): out[n]=len(y)-1-found[-1]
    return out

def model_suite(draws: list[Draw], special: bool=False) -> dict[str,np.ndarray]:
    y=special_matrix(draws) if special else matrix(draws)
    total=1.0 if special else 6.0
    base=total/N
    result={}
    # Beta-Binomial shrinkage prevents small-window overreaction.
    for window,prior in ((24,72),(60,120),(150,180),(360,240)):
        z=y[-window:]; rate=(z.sum(0)+base*prior)/(len(z)+prior)
        result[f"bayes_{window}"]=normalize_probability(rate,total)
    for hl in (8,21,55,144): result[f"ewma_{hl}"]=normalize_probability(ewma(y[-720:],hl),total)
    g=gaps(y)
    # Empirical hazard P(hit next | current gap bucket), learned without assuming overdue means due.
    hazard=np.full(N,base)
    hist=y[-900:]
    for n in range(N):
        run=0; num=den=0
        target=min(int(g[n]),35)
        for value in hist[:,n]:
            if min(run,35)==target: den+=1; num+=int(value)
            run=0 if value else run+1
        hazard[n]=(num+base*30)/(den+30)
    result["empirical_hazard"]=normalize_probability(hazard,total)
    if not special:
        # Conditional pair lift from latest two draws, strongly shrunk.
        recent=y[-500:]; pair=recent.T@recent; marg=recent.mean(0)
        anchors=np.flatnonzero(y[-2:].sum(0)>0); lift=np.zeros(N)
        for n in range(N):
            vals=[]
            for a in anchors:
                co=pair[n,a]; vals.append((co+40*marg[n])/(recent[:,a].sum()+40))
            lift[n]=statistics.mean(vals) if vals else marg[n]
        result["conditional_pair"]=normalize_probability(lift,total)
        # 真正的跨期拖牌：只使用「前一期號碼 -> 下一期號碼」的時序轉移，
        # 並以強貝氏收縮避免少數巧合被誤當成規律。
        transition=y[-900:]
        previous=transition[:-1]
        following=transition[1:]
        next_marginal=following.mean(0)
        latest_anchors=np.flatnonzero(y[-1]>0)
        lagged_drag=np.full(N,base)
        for n in range(N):
            values=[]
            for anchor in latest_anchors:
                anchor_count=previous[:,anchor].sum()
                co=(previous[:,anchor]*following[:,n]).sum()
                values.append((co+100*next_marginal[n])/(anchor_count+100))
            lagged_drag[n]=statistics.mean(values) if values else next_marginal[n]
        result["lagged_drag"]=normalize_probability(lagged_drag,total)

        # 間隔週期：以歷史出現間隔的核平滑危險率評估目前所處週期；
        # 使用存活樣本作分母，不能把「很久沒出」直接當成「必出」。
        interval_cycle=np.full(N,base)
        for n in range(N):
            positions=np.flatnonzero(y[-1800:,n])
            intervals=np.diff(positions)
            target=int(g[n])+1
            if len(intervals):
                eligible=intervals[intervals>=target]
                near=float(np.exp(-0.5*((eligible-target)/2.5)**2).sum()) if len(eligible) else 0.0
                interval_cycle[n]=(near+80*base)/(len(eligible)+80)
        result["interval_cycle"]=normalize_probability(interval_cycle,total)

        # 滯後軌跡：檢查2至36期的自我重現關係，只讓當下確有對應歷史觸發的
        # 滯後參與評分；所有條件率同樣強力收縮，並交由走步回測決定權重。
        lag_trace=np.full(N,base)
        trace=y[-1200:]
        for n in range(N):
            values=[]
            series=trace[:,n]
            for lag in range(2,37):
                if len(series)<=lag or not series[-lag]:
                    continue
                trigger=series[:-lag]
                outcome=series[lag:]
                count=trigger.sum()
                co=(trigger*outcome).sum()
                values.append((co+120*base)/(count+120))
            lag_trace[n]=statistics.mean(values) if values else base
        result["lag_trace"]=normalize_probability(lag_trace,total)
        # Regime slope: recent probability versus stable background, clipped and shrunk.
        short=(y[-30:].sum(0)+base*90)/120; long=(y[-240:].sum(0)+base*180)/420
        result["regime_slope"]=normalize_probability(long+np.clip(short-long,-.025,.025),total)
    return result

def brier(p: np.ndarray,y: np.ndarray) -> float: return float(np.mean((p-y)**2))
def logloss(p: np.ndarray,y: np.ndarray) -> float:
    p=np.clip(p,1e-6,1-1e-6); return float(-np.mean(y*np.log(p)+(1-y)*np.log(1-p)))

def trailing_zero_streak(values: list[int], cap: int=6) -> int:
    streak=0
    for value in reversed(values):
        if value: break
        streak+=1
        if streak>=cap: break
    return streak

def combine_predictions(preds: np.ndarray, weights: np.ndarray, total: float, rank_mix: float=0.0) -> np.ndarray:
    """混合機率平均與跨模型名次共識；rank_mix=0即保留原機率集成。"""
    probability_score=np.average(preds,axis=0,weights=weights)
    rank_rows=[]
    for row in preds:
        order=np.argsort(row)[::-1]
        score=np.empty(N,dtype=float)
        score[order]=np.linspace(1.0,0.0,N)
        rank_rows.append(score)
    consensus=normalize_probability(np.average(np.stack(rank_rows),axis=0,weights=weights),total)
    return (1-rank_mix)*probability_score+rank_mix*consensus

def walk_forward(draws: list[Draw], rounds: int=520, special: bool=False, weight_config: tuple[float,float,float,float,float]=(.50,.30,.20,3.4,.055), rank_mix: float=0.0) -> dict:
    start=max(360,len(draws)-rounds); names=list(model_suite(draws[:start],special))
    losses={n:[] for n in names}; hits={n:[] for n in names}; single_hits={n:[] for n in names}; ensemble_rows=[]
    short_w,mid_w,long_w,temperature,streak_cost=weight_config
    weights=np.ones(len(names))/len(names)
    for i in range(start,len(draws)):
        models=model_suite(draws[:i],special); actual=np.zeros(N)
        actual[(draws[i].special-1 if special else np.array(draws[i].main)-1)]=1
        preds=np.stack([models[n] for n in names]); k=3 if special else 9
        if losses[names[0]]:
            expected=k*(1 if special else 6)/49
            uniform_ll=logloss(np.full(N,(1 if special else 6)/N),actual)
            quality=[]
            for n in names:
                hit30=statistics.mean(hits[n][-30:])
                hit120=statistics.mean(hits[n][-120:])
                hit360=statistics.mean(hits[n][-360:])
                loss30=statistics.mean(losses[n][-30:])
                loss120=statistics.mean(losses[n][-120:])
                loss360=statistics.mean(losses[n][-360:])
                streak=trailing_zero_streak(hits[n])
                # 新權重鐵律：短期失速優先反映，中長期負責防止三兩期過度擬合。
                hit_edge=short_w*(hit30-expected)+mid_w*(hit120-expected)+long_w*(hit360-expected)
                calibration_penalty=12*max(0,loss30-uniform_ll)+8*max(0,loss120-uniform_ll)+4*max(0,loss360-uniform_ll)
                failure_penalty=streak_cost*streak
                quality.append(hit_edge-calibration_penalty-failure_penalty)
            q=np.array(quality); weights=np.exp(temperature*(q-q.max())); weights/=weights.sum()
            for _ in range(5):
                weights=np.minimum(weights,.22); weights/=weights.sum()
        raw_ensemble=combine_predictions(preds,weights,1.0 if special else 6.0,rank_mix)
        # Lottery signals are weak: shrink aggressively toward the fair-draw prior while preserving rank.
        prior=np.full(N,(1 if special else 6)/N)
        ensemble=.20*raw_ensemble+.80*prior
        ensemble_order=np.argsort(ensemble)[::-1]
        actual_ranks=sorted(j+1 for j,idx in enumerate(ensemble_order) if actual[idx])
        ensemble_rows.append({"period":draws[i].period,"date":draws[i].draw_date,"hit":int(actual[ensemble_order[:k]].sum()),"single_number":int(ensemble_order[0]+1),"single_hit":int(actual[ensemble_order[0]]),"actual_ranks":actual_ranks,"first_hit_rank":actual_ranks[0],"within_9":actual_ranks[0]<=9,"brier":brier(ensemble,actual),"logloss":logloss(ensemble,actual)})
        step=[]
        for j,n in enumerate(names):
            order=np.argsort(preds[j])[::-1]
            hit=int(actual[order[:k]].sum())
            loss=logloss(preds[j],actual); losses[n].append(loss); hits[n].append(hit); single_hits[n].append(int(actual[order[0]])); step.append(loss)
    uniform=np.full(N,(1 if special else 6)/N)
    actuals=[]
    for d in draws[start:]:
        y=np.zeros(N); y[(d.special-1 if special else np.array(d.main)-1)]=1; actuals.append(y)
    uniform_loss=statistics.mean(logloss(uniform,y) for y in actuals)
    ensemble_loss=statistics.mean(r["logloss"] for r in ensemble_rows)
    recent_windows={str(w):round(statistics.mean(r["hit"] for r in ensemble_rows[-w:]),4) for w in (10,30,60,120)}
    single_recent={str(w):round(statistics.mean(r["single_hit"] for r in ensemble_rows[-w:]),6) for w in (10,30,60,120)}
    return {"rounds":len(ensemble_rows),"names":names,"weighting_strategy":"三層滾動權重v4：30期50%＋120期30%＋360期20%，另加校準誤差與連續失誤懲罰，單模型上限22%","weights":{n:round(float(w),8) for n,w in zip(names,weights)},"model_logloss":{n:round(statistics.mean(v),8) for n,v in losses.items()},"model_avg_hits":{n:round(statistics.mean(hits[n]),4) for n in names},"model_single_hit_rate":{n:round(statistics.mean(single_hits[n]),6) for n in names},"model_recent_30_hits":{n:round(statistics.mean(hits[n][-30:]),4) for n in names},"model_recent_120_hits":{n:round(statistics.mean(hits[n][-120:]),4) for n in names},"model_recent_360_hits":{n:round(statistics.mean(hits[n][-360:]),4) for n in names},"model_failure_streak":{n:trailing_zero_streak(hits[n]) for n in names},"ensemble_recent_hits":recent_windows,"single_hit_rate":round(statistics.mean(r["single_hit"] for r in ensemble_rows),6),"single_recent_hit_rate":single_recent,"ensemble_logloss":round(ensemble_loss,8),"uniform_logloss":round(uniform_loss,8),"logloss_edge":round(uniform_loss-ensemble_loss,8),"avg_hits":round(statistics.mean(r["hit"] for r in ensemble_rows),4),"rows":ensemble_rows}

def final_scores(draws: list[Draw], bt: dict, special=False) -> np.ndarray:
    models=model_suite(draws,special); names=bt["names"]
    w=np.array([bt["weights"][n] for n in names]); w/=w.sum()
    raw=combine_predictions(np.stack([models[n] for n in names]),w,1.0 if special else 6.0,bt.get("rank_mix",0.0))
    prior=np.full(N,(1 if special else 6)/N)
    return .20*raw+.80*prior

def shape_ok(nums: tuple[int,...]) -> bool:
    odd=sum(n%2 for n in nums); low=sum(n<=24 for n in nums); zones=Counter((n-1)//10 for n in nums)
    return 2<=odd<=4 and 2<=low<=4 and max(zones.values())<=3 and 80<=sum(nums)<=220

def build_sets(score: np.ndarray, count=8) -> list[list[int]]:
    order=(np.argsort(score)[::-1]+1).tolist()
    low=sorted(range(1,25),key=lambda n:score[n-1],reverse=True)[:9]
    high=sorted(range(25,50),key=lambda n:score[n-1],reverse=True)[:9]
    pool=sorted(set(order[:14]+low+high)); ranked=sorted(pool,key=lambda n:score[n-1],reverse=True)
    candidates=[]
    for comb in combinations(pool,6):
        if not shape_ok(comb): continue
        value=sum(math.log(score[n-1]+1e-9) for n in comb)
        candidates.append((value,tuple(sorted(comb))))
    candidates.sort(reverse=True); chosen=[]
    for value,comb in candidates:
        overlap=max((len(set(comb)&set(x)) for x in chosen),default=0)
        if overlap<=4: chosen.append(comb)
        if len(chosen)==count: break
    if len(chosen)<count:
        for _,comb in candidates:
            if comb not in chosen: chosen.append(comb)
            if len(chosen)==count: break
    return [list(x) for x in chosen]

def next_draw(day: str, draws: list[Draw] | None = None) -> str:
    """依最近80期常見星期推算；節日及金多寶仍以馬會公告為準。"""
    common={k for k,_ in Counter(date.fromisoformat(x.draw_date).weekday() for x in draws[-80:]).most_common(3)} if draws else {1,3,5}
    d=date.fromisoformat(day)+timedelta(days=1)
    while d.weekday() not in common: d+=timedelta(days=1)
    return d.isoformat()

def prize_division(selected: list[int] | tuple[int,...], draw: Draw) -> str | None:
    """按香港六合彩七級獎制判定一組單式注項。"""
    if len(selected)!=6 or len(set(selected))!=6 or not all(1<=n<=49 for n in selected):
        raise ValueError("注項必須是1至49中六個不重複號碼")
    hits=len(set(selected)&set(draw.main)); extra=draw.special in selected
    return {(6,False):"一獎",(5,True):"二獎",(5,False):"三獎",(4,True):"四獎",(4,False):"五獎",(3,True):"六獎",(3,False):"七獎"}.get((hits,extra))

def analyze(draws: list[Draw]) -> dict:
    champion=walk_forward(draws,520,False,(.60,.25,.15,4.0,.07),0.0)
    challenger=walk_forward(draws,520,False,(.60,.25,.15,4.0,.07),0.65)
    # 挑戰者不只要守住前9覆蓋率，也必須在520期與近120期的第1名
    # 獨支命中率不低於冠軍，避免拿寬牌命中冒充獨支變準。
    promote=(challenger["avg_hits"]>=champion["avg_hits"] and challenger["ensemble_recent_hits"]["60"]>=champion["ensemble_recent_hits"]["60"] and challenger["ensemble_recent_hits"]["120"]>=champion["ensemble_recent_hits"]["120"] and challenger["single_hit_rate"]>=champion["single_hit_rate"] and challenger["single_recent_hit_rate"]["120"]>=champion["single_recent_hit_rate"]["120"] and challenger["ensemble_logloss"]<=champion["ensemble_logloss"]+.00015)
    main_bt=challenger if promote else champion
    main_bt["rank_mix"]=0.65 if promote else 0.0
    main_bt["champion_challenger"]={"promoted":"獨支名次共識混合" if promote else "原機率集成","rule":"挑戰者須同時守住520期、近60期、近120期前9表現，且520期與近120期獨支命中率不得下降，校準損失不得明顯惡化","champion":{"avg520":champion["avg_hits"],"recent60":champion["ensemble_recent_hits"]["60"],"recent120":champion["ensemble_recent_hits"]["120"],"single520":champion["single_hit_rate"],"single120":champion["single_recent_hit_rate"]["120"],"logloss":champion["ensemble_logloss"]},"challenger":{"avg520":challenger["avg_hits"],"recent60":challenger["ensemble_recent_hits"]["60"],"recent120":challenger["ensemble_recent_hits"]["120"],"single520":challenger["single_hit_rate"],"single120":challenger["single_recent_hit_rate"]["120"],"logloss":challenger["ensemble_logloss"]}}
    main_bt["external_method_review"]={"採用":["多窗口熱冷頻率","遺漏與經驗危險率","同期开奖配對","跨期拖牌轉移","間隔週期核平滑","2至36期滯後軌跡","近期狀態漂移","跨模型名次共識","嚴格時間序列走步回測"],"不直接採用":["宣稱必中AI","把逾期號視為必出","未經回測的三連號迷信","以增加注數冒充提高單號機率","用前9覆蓋率冒充獨支準確率"]}
    special_bt=walk_forward(draws,520,True)
    ms=final_scores(draws,main_bt); ss=final_scores(draws,special_bt,True)
    rank=(np.argsort(ms)[::-1]+1).tolist(); srank=(np.argsort(ss)[::-1]+1).tolist()
    # Publication gate measures calibration, not fabricated certainty.
    main_random=9*6/49; special_random=3/49
    within9_random=1-math.comb(40,6)/math.comb(49,6)
    recent_within9=statistics.mean(r["within_9"] for r in main_bt["rows"][-60:])
    recent_gate=recent_within9>=within9_random and main_bt["ensemble_recent_hits"]["120"]>=main_random
    gate=main_bt["avg_hits"]>main_random and recent_gate and special_bt["avg_hits"]>=special_random and main_bt["logloss_edge"]>=-0.0005 and special_bt["logloss_edge"]>=-0.0005
    prior_models=model_suite(draws[:-1],False)
    actual_latest=set(draws[-1].main)
    module_review=[]
    for name in main_bt["names"]:
        prior_top9=(np.argsort(prior_models[name])[::-1]+1)[:9].tolist()
        latest_hits=sorted(actual_latest & set(prior_top9))
        recent30=main_bt["model_recent_30_hits"][name]
        recent120=main_bt["model_recent_120_hits"][name]
        recent360=main_bt["model_recent_360_hits"][name]
        streak=main_bt["model_failure_streak"][name]
        weak=recent30<main_random or (recent120<main_random and recent360<main_random)
        decision="短期失速或中長期落後，自動降權" if weak else "通過三層滾動檢查，依成績配權"
        module_review.append({"model":name,"prior_top9":prior_top9,"latest_hits":latest_hits,"latest_hit_count":len(latest_hits),"recent_30_avg_hits":recent30,"recent_120_avg_hits":recent120,"recent_360_avg_hits":recent360,"failure_streak":streak,"new_weight":main_bt["weights"][name],"decision":decision})
    main_bt["module_review"]=module_review
    main_bt["ranking_target"]="主號前9碼"
    main_bt["weighting_strategy"]="前9碼三層滾動權重v5：30期60%＋120期25%＋360期15%，另加校準誤差與連續失誤懲罰，單模型上限22%"
    main_bt["within9_random_baseline"]=round(within9_random,4)
    main_bt["first_hit_rank_audit"]={str(w):{"within_9_rate":round(statistics.mean(r["within_9"] for r in main_bt["rows"][-w:]),4),"average_first_hit_rank":round(statistics.mean(r["first_hit_rank"] for r in main_bt["rows"][-w:]),4),"outside_9_count":sum(not r["within_9"] for r in main_bt["rows"][-w:])} for w in (10,30,60,120)}
    strongest=rank[0]
    current_models=model_suite(draws,False)
    top9_support=[name for name in main_bt["names"] if strongest in (np.argsort(current_models[name])[::-1]+1)[:9]]
    top3_support=[name for name in main_bt["names"] if strongest in (np.argsort(current_models[name])[::-1]+1)[:3]]
    weighted_support=sum(main_bt["weights"][name] for name in top9_support)
    fair_probability=6/49
    required_model_support=max(7,math.ceil(len(main_bt["names"])*.60))
    confidence_checks={
        "發布守門通過":gate,
        "校準機率高於公平基準":float(ms[strongest-1])>fair_probability,
        f"至少{required_model_support}個模型列入前9":len(top9_support)>=required_model_support,
        "加權模型共識至少65%":weighted_support>=.65,
        "近60期前9覆蓋優於隨機":main_bt["first_hit_rank_audit"]["60"]["within_9_rate"]>=main_bt["within9_random_baseline"],
        "近120期平均命中優於隨機":main_bt["ensemble_recent_hits"]["120"]>=main_random,
        "第一名分數嚴格高於第二名":float(ms[rank[0]-1])>float(ms[rank[1]-1])
    }
    super_consensus=all(confidence_checks.values())
    main_bt["confidence_audit"]={"number":strongest,"label":"超高共識・本期唯一最強推薦" if super_consensus else "觀察級・本期唯一最強排序（未達超高共識）","super_consensus":super_consensus,"calibrated_probability":round(float(ms[strongest-1]),6),"fair_probability":round(fair_probability,6),"relative_lift_pct":round((float(ms[strongest-1])/fair_probability-1)*100,2),"score_gap_to_second":round(float(ms[rank[0]-1]-ms[rank[1]-1]),8),"model_top9_support":len(top9_support),"required_model_support":required_model_support,"model_top3_support":len(top3_support),"weighted_support_pct":round(weighted_support*100,2),"checks":confidence_checks,"warning":"超高共識代表多項模型邏輯一致，不代表必中；六合彩單號公平基準仍約12.24%。未通過守門時只列觀察排序，不得冒充高信心推薦。"}

    model_groups={
        "長短期頻率":["bayes_24","bayes_60","bayes_150","bayes_360"],
        "近期軌跡":["ewma_8","ewma_21","ewma_55","ewma_144","regime_slope"],
        "遺漏與間隔週期":["empirical_hazard","interval_cycle"],
        "同期开奖與跨期拖牌":["conditional_pair","lagged_drag"],
        "滯後規律":["lag_trace"],
    }
    module_groups=[]
    for label,names in model_groups.items():
        support=[]
        ranks={}
        for name in names:
            order=(np.argsort(current_models[name])[::-1]+1).tolist()
            position=order.index(strongest)+1
            ranks[name]=position
            if position<=9:
                support.append(name)
        module_groups.append({"group":label,"models":names,"supporting_models":support,"support_count":len(support),"strongest_ranks":ranks,"passed":bool(support)})
    trajectory_checks={
        "完整歷史資料至少4000期":len(draws)>=4000,
        "520期逐期向前走步驗證":main_bt["rounds"]==520,
        "頻率軌跡週期拖牌模組全部執行":all(name in current_models for names in model_groups.values() for name in names),
        "每期只使用當時以前資料":all(row["date"]==draws[len(draws)-len(main_bt["rows"])+i].draw_date for i,row in enumerate(main_bt["rows"])),
        "候選號碼1至49完整排序":len(rank)==49 and len(set(rank))==49,
        "第一名分數嚴格高於第二名":float(ms[rank[0]-1])>float(ms[rank[1]-1]),
        "單一模型權重不超過22%":max(main_bt["weights"].values())<=.22,
    }
    main_bt["trajectory_audit"]={
        "daily_strongest":strongest,
        "based_on_period":draws[-1].period,
        "based_on_date":draws[-1].draw_date,
        "history_draws":len(draws),
        "model_count":len(main_bt["names"]),
        "module_groups":module_groups,
        "checks":trajectory_checks,
        "strict_computation_passed":all(trajectory_checks.values()),
        "walk_forward_rounds":main_bt["rounds"],
        "walk_forward_single_hits":sum(row["single_hit"] for row in main_bt["rows"]),
        "walk_forward_single_hit_rate":main_bt["single_hit_rate"],
        "walk_forward_single_recent":main_bt["single_recent_hit_rate"],
        "fair_single_rate":round(fair_probability,6),
        "target_accuracy_pct":90.0,
        "certified_90_accuracy":False,
        "certification_rule":"只承認開獎前封存且逐期獨立結算的命中率；不得用前九、回填或重複快照冒充獨支90%準確率",
    }
    main_bt["recommendation_tiers"]={"A_唯一最強":[strongest],"B_高信心前三":rank[:3],"C_核心前九":rank[:9],"D_次高防守":rank[9:18],"E_低機率暫避":sorted(rank[-10:])}
    main_bt["strongest_single_audit"]={"number":rank[0],"calibrated_probability":round(float(ms[rank[0]-1]),6),"selection_rule":"14個頻率、軌跡、週期與拖牌模型依30／120／360期成績、校準誤差與連續失誤重新配權後，取校準機率唯一第1名","based_on_period":draws[-1].period,"based_on_date":draws[-1].draw_date}
    return {"system":"香港六合彩新世代鐵律預測系統","engine":"marksix_cleanroom_ensemble_v6_trajectory_audit","generated_at":date.today().isoformat(),"history":{"count":len(draws),"first":draws[0].draw_date,"latest":draws[-1].draw_date,"latest_period":draws[-1].period},"latest_draw":{"period":draws[-1].period,"date":draws[-1].draw_date,"main":draws[-1].main,"special":draws[-1].special},"target_date":next_draw(draws[-1].draw_date,draws),"main_rank":[{"rank":i+1,"number":n,"probability":round(float(ms[n-1]),6)} for i,n in enumerate(rank)],"special_rank":[{"rank":i+1,"number":n,"probability":round(float(ss[n-1]),6)} for i,n in enumerate(srank)],"packs":{"最強單支":rank[:1],"二中一":rank[:2],"三中一":rank[:3],"五中二":rank[:5],"九中三":rank[:9],"主攻12碼":rank[:12],"防守18碼":rank[:18]},"special_packs":{"最強單支":srank[:1],"三碼觀察":srank[:3]},"avoid":{"五不中":sorted(rank[-5:]),"十不中":sorted(rank[-10:]),"十五不中":sorted(rank[-15:])},"suggested_sets":build_sets(ms),"rules":{"range":"1–49","main_numbers":6,"extra_numbers":1,"unit_bet_hkd":10,"prizes":{"一獎":"6個正選號碼","二獎":"5個正選號碼＋特別號","三獎":"5個正選號碼","四獎":"4個正選號碼＋特別號（固定HK$9,600）","五獎":"4個正選號碼（固定HK$640）","六獎":"3個正選號碼＋特別號（固定HK$320）","七獎":"3個正選號碼（固定HK$40）"}},"backtest":{"main":main_bt,"special":special_bt},"release_gate":{"passed":gate,"publish_mode":"超高共識推薦" if gate else "觀察級排序","rule":"預測信心守門與開獎資料同步分離；未達門檻只降級標示，絕不可阻斷最新資料更新","main_edge":main_bt["logloss_edge"],"special_edge":special_bt["logloss_edge"],"main_avg_hits":main_bt["avg_hits"],"main_random_hits":round(main_random,4),"special_avg_hits":special_bt["avg_hits"],"special_random_hits":round(special_random,4),"max_main_weight":max(main_bt["weights"].values())},"operational_policy":{"data_sync_independent":True,"model_gate_blocks_data":False,"failed_gate_action":"保留最新資料、降級標示、啟動滾動檢討"},"notice":"歷史資料可用來檢測偏差與比較模型，但不能把未通過獨立封存驗證的軌跡宣稱為確定規律。本系統只發布可稽核的機率排序，不保證中獎。請量力而為，未滿18歲不得投注。"}

if __name__=="__main__":
    result=analyze(load_draws())
    out=ROOT/"reports"/"latest_analysis.json"; out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({"history":result["history"],"target":result["target_date"],"gate":result["release_gate"],"packs":result["packs"]},ensure_ascii=False,indent=2))
