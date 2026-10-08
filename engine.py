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
        # 前一期「兩個錨號同現」對下一期的條件率；不能把同一期共現
        # 當成預測下一期的證據。稀疏配對以強先驗收縮。
        transitions=y[-900:]
        previous=transitions[:-1]
        following=transitions[1:]
        next_marginal=following.mean(0)
        latest_anchors=np.flatnonzero(y[-1]>0)
        pair_rates=[]
        for first,second in combinations(latest_anchors,2):
            triggered=previous[:,first]*previous[:,second]
            count=float(triggered.sum())
            pair_rates.append(((triggered[:,None]*following).sum(0)+160*next_marginal)/(count+160))
        result["conditional_pair"]=normalize_probability(np.mean(pair_rates,axis=0) if pair_rates else next_marginal,total)
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
    losses={n:[] for n in names}; hits={n:[] for n in names}; single_hits={n:[] for n in names}; ensemble_rows=[]; trace=[]
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
        if not special: trace.append((preds,weights.copy(),ensemble.copy()))
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
    return {"rounds":len(ensemble_rows),"names":names,"weighting_strategy":"三層滾動權重v4：30期50%＋120期30%＋360期20%，另加校準誤差與連續失誤懲罰，單模型上限22%","weights":{n:round(float(w),8) for n,w in zip(names,weights)},"model_logloss":{n:round(statistics.mean(v),8) for n,v in losses.items()},"model_avg_hits":{n:round(statistics.mean(hits[n]),4) for n in names},"model_single_hit_rate":{n:round(statistics.mean(single_hits[n]),6) for n in names},"model_recent_30_hits":{n:round(statistics.mean(hits[n][-30:]),4) for n in names},"model_recent_120_hits":{n:round(statistics.mean(hits[n][-120:]),4) for n in names},"model_recent_360_hits":{n:round(statistics.mean(hits[n][-360:]),4) for n in names},"model_failure_streak":{n:trailing_zero_streak(hits[n]) for n in names},"ensemble_recent_hits":recent_windows,"single_hit_rate":round(statistics.mean(r["single_hit"] for r in ensemble_rows),6),"single_recent_hit_rate":single_recent,"ensemble_logloss":round(ensemble_loss,8),"uniform_logloss":round(uniform_loss,8),"logloss_edge":round(uniform_loss-ensemble_loss,8),"avg_hits":round(statistics.mean(r["hit"] for r in ensemble_rows),4),"rows":ensemble_rows,"_trace":trace}

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

def wilson_lower(hits: int, samples: int, z: float=1.959963984540054) -> float:
    """二項比例的95% Wilson下限，避免小樣本高命中被誤標高信心。"""
    if samples<=0:
        return 0.0
    rate=hits/samples
    denominator=1+z*z/samples
    centre=rate+z*z/(2*samples)
    margin=z*math.sqrt(rate*(1-rate)/samples+z*z/(4*samples*samples))
    return max(0.0,(centre-margin)/denominator)

def rank_all_candidates(scores: np.ndarray, model_predictions: np.ndarray, weights: np.ndarray,
                        names: list[str], prior_decisions: list[dict]) -> dict:
    """同一選號規則供歷史逐期重播與本期決策使用，歷史只讀當期以前。"""
    fair=6/49
    probability_rank=(np.argsort(scores)[::-1]+1).tolist()
    positions={number:index+1 for index,number in enumerate(probability_rank)}
    model_orders=np.argsort(model_predictions,axis=1)[:,::-1]
    model_ranks=np.empty_like(model_orders)
    for row,order in enumerate(model_orders): model_ranks[row,order]=np.arange(1,N+1)
    samples=np.zeros(N,dtype=int); hits=np.zeros(N,dtype=int)
    for row in prior_decisions:
        number=int(row["single_number"])-1
        samples[number]+=1; hits[number]+=int(row["single_hit"])
    minimum_samples=20
    required_top9=max(7,math.ceil(len(names)*.60))
    required_top3=math.ceil(len(names)*.50)
    floor=float(np.min(scores)); span=max(1e-12,float(np.max(scores))-floor)
    candidates=[]
    for number in range(1,N+1):
        ranks=model_ranks[:,number-1]
        top9=ranks<=9; top3=ranks<=3
        weighted_top9=float(weights[top9].sum()); weighted_top3=float(weights[top3].sum())
        count=int(samples[number-1]); hit=int(hits[number-1]); lower=wilson_lower(hit,count)
        checks={
            "模型估計高於公平基準":float(scores[number-1])>fair,
            f"至少{required_top9}個模型列入前9":int(top9.sum())>=required_top9,
            "加權模型前9共識至少65%":weighted_top9>=.65,
            f"至少{required_top3}個模型列入前3":int(top3.sum())>=required_top3,
            f"候選專屬走步樣本至少{minimum_samples}期":count>=minimum_samples,
            "候選走步95%下限高於公平基準":lower>fair,
        }
        probability_strength=(float(scores[number-1])-floor)/span
        rank_stability=max(0.0,1-(float(np.mean(ranks))-1)/48)
        # 極少次歷史入選不能因偶然全中取得完整證據權重。
        evidence_strength=min(1.0,lower/fair)*min(1.0,count/minimum_samples)
        decision_score=100*(.30*probability_strength+.25*weighted_top9+.20*weighted_top3+.15*rank_stability+.10*evidence_strength)
        candidates.append({
            "number":number,"probability_rank":positions[number],
            "calibrated_probability":round(float(scores[number-1]),6),
            "model_top9_support":int(top9.sum()),"weighted_top9_support_pct":round(weighted_top9*100,2),
            "model_top3_support":int(top3.sum()),"weighted_top3_support_pct":round(weighted_top3*100,2),
            "average_model_rank":round(float(np.mean(ranks)),2),
            "walk_forward_samples":count,"walk_forward_hits":hit,
            "walk_forward_hit_rate":round(hit/count,6) if count else 0.0,
            "walk_forward_wilson_95_lower":round(lower,6),
            "decision_score":round(decision_score,6),"checks":checks,
            "high_confidence_passed":all(checks.values()),
        })
    ordered=sorted(candidates,key=lambda item:(item["high_confidence_passed"],item["decision_score"],item["calibrated_probability"]),reverse=True)
    eligible=[item for item in ordered if item["high_confidence_passed"]]
    pool=eligible if eligible else ordered
    score_gap=pool[0]["decision_score"]-pool[1]["decision_score"] if len(pool)>1 else 1.0
    return {"ordered":ordered,"eligible":eligible,"winner":ordered[0],"score_gap":score_gap,
            "probability_rank":probability_rank,"required_top9":required_top9,
            "required_top3":required_top3,"minimum_samples":minimum_samples}

def summarize_decision_replay(rows: list[dict]) -> dict:
    evaluation=rows[-120:]
    hits=sum(int(row["single_hit"]) for row in rows)
    evaluation_hits=sum(int(row["single_hit"]) for row in evaluation)
    return {
        "method":"每期只用當期以前資料，重播實際發佈的單號與前9碼；最後120期單列評估",
        "rounds":len(rows),"single_hits":hits,"single_hit_rate":round(hits/len(rows),6),
        "top9_avg_hits":round(statistics.mean(row["top9_hits"] for row in rows),4),
        "top9_within_rate":round(statistics.mean(row["within_9"] for row in rows),6),
        "evaluation_rounds":len(evaluation),"evaluation_hits":evaluation_hits,
        "evaluation_hit_rate":round(evaluation_hits/len(evaluation),6),
        "evaluation_top9_avg_hits":round(statistics.mean(row["top9_hits"] for row in evaluation),4),
        "evaluation_top9_within_rate":round(statistics.mean(row["within_9"] for row in evaluation),6),
        "evaluation_wilson_95_lower":round(wilson_lower(evaluation_hits,len(evaluation)),6),
        "fair_single_rate":round(6/49,6),"rows":rows,
    }

def analyze(draws: list[Draw]) -> dict:
    champion=walk_forward(draws,520,False,(.60,.25,.15,4.0,.07),0.0)
    challenger=walk_forward(draws,520,False,(.60,.25,.15,4.0,.07),0.65)
    # 模型選擇只看較早的400期；最後120期僅用來評估，不能再反向挑選冠軍。
    def segment(rows: list[dict]) -> dict:
        return {"rounds":len(rows),"avg_hits":round(statistics.mean(row["hit"] for row in rows),4),
                "single_hits":sum(row["single_hit"] for row in rows),
                "single_rate":round(statistics.mean(row["single_hit"] for row in rows),6),
                "logloss":round(statistics.mean(row["logloss"] for row in rows),8)}
    champion_dev=segment(champion["rows"][:400]); challenger_dev=segment(challenger["rows"][:400])
    champion_holdout=segment(champion["rows"][400:]); challenger_holdout=segment(challenger["rows"][400:])
    promote=(challenger_dev["avg_hits"]>=champion_dev["avg_hits"] and
             challenger_dev["single_rate"]>=champion_dev["single_rate"] and
             challenger_dev["logloss"]<=champion_dev["logloss"]+.00015)
    main_bt=challenger if promote else champion
    trace=main_bt.pop("_trace")
    (champion if promote else challenger).pop("_trace")
    main_bt["rank_mix"]=0.65 if promote else 0.0
    main_bt["champion_challenger"]={"promoted":"獨支名次共識混合" if promote else "原機率集成","rule":"前400期選模型，後120期固定模型評估；評估段結果不得回頭決定晉級","selection_rounds":400,"evaluation_rounds":120,"development":{"champion":champion_dev,"challenger":challenger_dev},"evaluation":{"champion":champion_holdout,"challenger":challenger_holdout},"champion":{"avg520":champion["avg_hits"],"recent60":champion["ensemble_recent_hits"]["60"],"recent120":champion["ensemble_recent_hits"]["120"],"single520":champion["single_hit_rate"],"single120":champion["single_recent_hit_rate"]["120"],"logloss":champion["ensemble_logloss"]},"challenger":{"avg520":challenger["avg_hits"],"recent60":challenger["ensemble_recent_hits"]["60"],"recent120":challenger["ensemble_recent_hits"]["120"],"single520":challenger["single_hit_rate"],"single120":challenger["single_recent_hit_rate"]["120"],"logloss":challenger["ensemble_logloss"]}}
    main_bt["external_method_review"]={"採用":["多窗口熱冷頻率","遺漏與經驗危險率","前一期雙錨對下一期的條件轉移","跨期單錨拖牌轉移","間隔週期核平滑","2至36期滯後軌跡","近期狀態漂移","跨模型名次共識","同規則逐期走步重播"],"不直接採用":["宣稱必中AI","把逾期號視為必出","同一期共現冒充下一期訊號","以增加注數冒充提高單號機率","用前9覆蓋率冒充獨支準確率"]}
    special_bt=walk_forward(draws,520,True)
    special_bt.pop("_trace",None)
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
    probability_rank=rank[:]
    probability_champion=probability_rank[0]
    current_models=model_suite(draws,False)
    fair_probability=6/49
    # 真正重播「全候選決策」本身：每一期只用先前的決策與開獎結果。
    replay_rows=[]
    for draw,(predictions,step_weights,step_scores) in zip(draws[-len(trace):],trace):
        decision=rank_all_candidates(step_scores,predictions,step_weights,main_bt["names"],replay_rows)
        number=int(decision["winner"]["number"])
        ranked=[item["number"] for item in decision["ordered"]]
        actual=set(draw.main)
        first_rank=next(index+1 for index,candidate in enumerate(ranked) if candidate in actual)
        replay_rows.append({"period":draw.period,"date":draw.draw_date,"single_number":number,
                            "single_hit":int(number in actual),"top9_hits":len(actual.intersection(ranked[:9])),
                            "first_hit_rank":first_rank,"within_9":first_rank<=9,
                            "eligible_count":len(decision["eligible"]),
                            "observation_only":not bool(decision["eligible"])})
    candidate_replay=summarize_decision_replay(replay_rows)
    # 固定比較幾條事先定義的選號規則，發展段選擇，評估段不參與挑選。
    policy_rows={"probability_top":[],"candidate_tournament":replay_rows,
                 "exclude_previous_draw":[],"avoid_three_draw_streak":[]}
    for index,(predictions,step_weights,step_scores) in enumerate(trace):
        draw=draws[-len(trace)+index]
        prior=draws[-len(trace)+index-1]
        probability_order=(np.argsort(step_scores)[::-1]+1).tolist()
        last_three=draws[-len(trace)+index-3:-len(trace)+index]
        picks={
            "probability_top":probability_order[0],
            "candidate_tournament":replay_rows[index]["single_number"],
            "exclude_previous_draw":next(number for number in probability_order if number not in prior.main),
            "avoid_three_draw_streak":next(number for number in probability_order if not all(number in past.main for past in last_three)),
        }
        actual=set(draw.main)
        for name,number in picks.items():
            if name=="candidate_tournament": continue
            ranked=[number]+[candidate for candidate in probability_order if candidate!=number]
            first_rank=next(position+1 for position,candidate in enumerate(ranked) if candidate in actual)
            policy_rows[name].append({"period":draw.period,"date":draw.draw_date,
                                      "single_number":number,"single_hit":int(number in actual),
                                      "top9_hits":len(actual.intersection(ranked[:9])),
                                      "first_hit_rank":first_rank,"within_9":first_rank<=9})
    policy_review={name:{"development_hits":sum(row["single_hit"] for row in rows[:400]),"development_rounds":400,
                         "evaluation_hits":sum(row["single_hit"] for row in rows[400:]),"evaluation_rounds":120,
                         "total_hits":sum(row["single_hit"] for row in rows),"total_rounds":len(rows)}
                   for name,rows in policy_rows.items()}
    selected_policy=max(policy_rows,key=lambda name:policy_review[name]["development_hits"])
    published_rows=policy_rows[selected_policy]
    main_bt["candidate_tournament_replay"]={key:value for key,value in candidate_replay.items() if key!="rows"}
    main_bt["decision_replay"]=summarize_decision_replay(published_rows)
    main_bt["policy_review"]={"selection_rule":"僅以前400期命中選規則；最後120期只做固定規則評估",
                              "selected":selected_policy,"policies":policy_review}
    replay_rows=published_rows
    main_bt["baseline_first_hit_rank_audit"]=main_bt["first_hit_rank_audit"]
    main_bt["first_hit_rank_audit"]={str(window):{
        "within_9_rate":round(statistics.mean(row["within_9"] for row in replay_rows[-window:]),4),
        "average_first_hit_rank":round(statistics.mean(row["first_hit_rank"] for row in replay_rows[-window:]),4),
        "outside_9_count":sum(not row["within_9"] for row in replay_rows[-window:]),
    } for window in (10,30,60,120)}
    main_bt["published_top9_avg_hits"]=main_bt["decision_replay"]["top9_avg_hits"]
    main_bt["published_top9_recent_hits"]={str(window):round(statistics.mean(row["top9_hits"] for row in replay_rows[-window:]),4) for window in (10,30,60,120)}
    # 發布門檻看實際使用的決策，並要求末段單號下限高於公平基準。
    gate=(gate and main_bt["decision_replay"]["top9_avg_hits"]>main_random and
          main_bt["decision_replay"]["evaluation_top9_avg_hits"]>=main_random and
          main_bt["decision_replay"]["evaluation_wilson_95_lower"]>fair_probability)
    weights=np.array([main_bt["weights"][name] for name in main_bt["names"]],dtype=float)
    weights/=weights.sum()
    current_decision=rank_all_candidates(ms,np.stack([current_models[name] for name in main_bt["names"]]),weights,main_bt["names"],replay_rows)
    ordered_candidates=current_decision["ordered"]
    eligible=current_decision["eligible"] if selected_policy=="candidate_tournament" else []
    if selected_policy=="candidate_tournament":
        decision_rank=[item["number"] for item in ordered_candidates]
    elif selected_policy=="exclude_previous_draw":
        chosen=next(number for number in probability_rank if number not in draws[-1].main)
        decision_rank=[chosen]+[number for number in probability_rank if number!=chosen]
    elif selected_policy=="avoid_three_draw_streak":
        chosen=next(number for number in probability_rank if not all(number in draw.main for draw in draws[-3:]))
        decision_rank=[chosen]+[number for number in probability_rank if number!=chosen]
    else:
        decision_rank=probability_rank[:]
    strongest=decision_rank[0]
    strongest_evidence=next(item for item in ordered_candidates if item["number"]==strongest)
    required_model_support=current_decision["required_top9"]
    required_top3_support=current_decision["required_top3"]
    minimum_candidate_samples=current_decision["minimum_samples"]
    probability_positions={number:index+1 for index,number in enumerate(probability_rank)}
    top9_support=[name for name in main_bt["names"] if strongest in (np.argsort(current_models[name])[::-1]+1)[:9]]
    top3_support=[name for name in main_bt["names"] if strongest in (np.argsort(current_models[name])[::-1]+1)[:3]]
    weighted_support=sum(main_bt["weights"][name] for name in top9_support)
    score_gap=(current_decision["score_gap"] if selected_policy=="candidate_tournament" else
               float(ms[decision_rank[0]-1]-ms[decision_rank[1]-1]))
    main_bt["confidence_tournament"]={
        "rule":"49碼接受14模組現況共識及同規則520期逐期重播；最終選號策略僅由前400期決定，後120期單列評估",
        "probability_champion":probability_champion,
        "confidence_champion":strongest if eligible else None,
        "high_confidence_found":bool(eligible),
        "fallback_used":not bool(eligible),
        "selection_basis":selected_policy,
        "candidate_count":len(ordered_candidates),
        "passed_numbers":[item["number"] for item in eligible],
        "minimum_candidate_samples":minimum_candidate_samples,
        "required_top9_models":required_model_support,
        "required_top3_models":required_top3_support,
        "winner":strongest_evidence,
        "top_candidates":[strongest_evidence]+[item for item in ordered_candidates if item["number"]!=strongest][:8],
    }
    confidence_checks={
        **strongest_evidence["checks"],
        "發佈策略首位嚴格高於第二名":score_gap>0,
        "整體模型發布守門通過":gate,
    }
    high_confidence_candidate=bool(selected_policy=="candidate_tournament" and strongest_evidence["high_confidence_passed"] and score_gap>0)
    super_consensus=high_confidence_candidate and gate
    label=("超高共識・本期唯一最強推薦" if super_consensus else ("全模組高信心候選・實戰認證累積中" if high_confidence_candidate else "觀察級・本期唯一最強排序（未達高信心守門）"))
    main_bt["confidence_audit"]={"number":strongest,"label":label,"high_confidence_candidate":high_confidence_candidate,"super_consensus":super_consensus,"calibrated_probability":round(float(ms[strongest-1]),6),"fair_probability":round(fair_probability,6),"relative_lift_pct":round((float(ms[strongest-1])/fair_probability-1)*100,2),"score_gap_to_second":round(score_gap,6),"probability_champion":probability_champion,"probability_rank":probability_positions[strongest],"model_top9_support":len(top9_support),"required_model_support":required_model_support,"model_top3_support":len(top3_support),"weighted_support_pct":round(weighted_support*100,2),"candidate_walk_forward_samples":strongest_evidence["walk_forward_samples"],"candidate_walk_forward_hits":strongest_evidence["walk_forward_hits"],"candidate_walk_forward_hit_rate":strongest_evidence["walk_forward_hit_rate"],"candidate_wilson_95_lower":strongest_evidence["walk_forward_wilson_95_lower"],"checks":confidence_checks,"warning":"高信心表示全49碼候選競賽的模型共識與候選專屬走步證據通過，不代表必中；單號公平基準仍約12.24%，實戰認證必須繼續累積。"}

    model_groups={
        "長短期頻率":["bayes_24","bayes_60","bayes_150","bayes_360"],
        "近期軌跡":["ewma_8","ewma_21","ewma_55","ewma_144","regime_slope"],
        "遺漏與間隔週期":["empirical_hazard","interval_cycle"],
        "跨期雙錨與單錨拖牌":["conditional_pair","lagged_drag"],
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
        "每期只使用當時以前資料":all(row["date"]==draws[len(draws)-len(replay_rows)+i].draw_date for i,row in enumerate(replay_rows)),
        "候選號碼1至49完整排序":len(decision_rank)==49 and len(set(decision_rank))==49,
        "發佈策略首位嚴格高於第二名":score_gap>0,
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
        "walk_forward_rounds":len(replay_rows),
        "walk_forward_single_hits":main_bt["decision_replay"]["single_hits"],
        "walk_forward_single_hit_rate":main_bt["decision_replay"]["single_hit_rate"],
        "walk_forward_single_recent":{str(window):round(statistics.mean(row["single_hit"] for row in replay_rows[-window:]),6) for window in (10,30,60,120)},
        "fair_single_rate":round(fair_probability,6),
        "target_accuracy_pct":90.0,
        "certified_90_accuracy":False,
        "certification_rule":"只承認開獎前封存且逐期獨立結算的命中率；不得用前九、回填或重複快照冒充獨支90%準確率",
    }
    main_bt["recommendation_tiers"]={"A_唯一最強":[strongest],"B_高信心前三":decision_rank[:3],"C_核心前九":decision_rank[:9],"D_次高防守":decision_rank[9:18],"E_低機率暫避":sorted(probability_rank[-10:])}
    provisional_target=next_draw(draws[-1].draw_date,draws)
    main_bt["confidence_tournament"]["target_date"]=provisional_target
    main_bt["confidence_audit"]["target_date"]=provisional_target
    main_bt["trajectory_audit"]["target_date"]=provisional_target
    main_bt["strongest_single_audit"]={"number":strongest,"calibrated_probability":round(float(ms[strongest-1]),6),"selection_rule":f"前400期比較固定策略、後120期單列評估；本期採用{selected_policy}，所有候選均列出守門結果","based_on_period":draws[-1].period,"based_on_date":draws[-1].draw_date,"target_date":provisional_target,"probability_champion":probability_champion}
    return {"system":"香港六合彩新世代鐵律預測系統","engine":"marksix_cleanroom_ensemble_v8_replayed_decision","generated_at":date.today().isoformat(),"history":{"count":len(draws),"first":draws[0].draw_date,"latest":draws[-1].draw_date,"latest_period":draws[-1].period},"latest_draw":{"period":draws[-1].period,"date":draws[-1].draw_date,"main":draws[-1].main,"special":draws[-1].special},"target_date":provisional_target,"main_rank":[{"rank":i+1,"number":n,"probability":round(float(ms[n-1]),6)} for i,n in enumerate(probability_rank)],"decision_rank":[{"rank":i+1,"number":n,"probability":round(float(ms[n-1]),6),"candidate_evidence_score":next(item["decision_score"] for item in ordered_candidates if item["number"]==n),"selection_basis":selected_policy} for i,n in enumerate(decision_rank)],"special_rank":[{"rank":i+1,"number":n,"probability":round(float(ss[n-1]),6)} for i,n in enumerate(srank)],"packs":{"最強單支":[strongest],"機率排序第1":[probability_champion],"二中一":decision_rank[:2],"三中一":decision_rank[:3],"五中二":decision_rank[:5],"九中三":decision_rank[:9],"主攻12碼":decision_rank[:12],"防守18碼":decision_rank[:18]},"special_packs":{"最強單支":srank[:1],"三碼觀察":srank[:3]},"avoid":{"五不中":sorted(probability_rank[-5:]),"十不中":sorted(probability_rank[-10:]),"十五不中":sorted(probability_rank[-15:])},"suggested_sets":build_sets(ms),"rules":{"range":"1–49","main_numbers":6,"extra_numbers":1,"unit_bet_hkd":10,"prizes":{"一獎":"6個正選號碼","二獎":"5個正選號碼＋特別號","三獎":"5個正選號碼","四獎":"4個正選號碼＋特別號（固定HK$9,600）","五獎":"4個正選號碼（固定HK$640）","六獎":"3個正選號碼＋特別號（固定HK$320）","七獎":"3個正選號碼（固定HK$40）"}},"backtest":{"main":main_bt,"special":special_bt},"release_gate":{"passed":gate,"publish_mode":"超高共識推薦" if gate else ("全模組高信心候選・實戰認證累積中" if high_confidence_candidate else "觀察級排序"),"rule":"預測信心守門與開獎資料同步分離；未達門檻只降級標示，絕不可阻斷最新資料更新","main_edge":main_bt["logloss_edge"],"special_edge":special_bt["logloss_edge"],"main_avg_hits":main_bt["published_top9_avg_hits"],"main_random_hits":round(main_random,4),"special_avg_hits":special_bt["avg_hits"],"special_random_hits":round(special_random,4),"max_main_weight":max(main_bt["weights"].values())},"operational_policy":{"data_sync_independent":True,"model_gate_blocks_data":False,"failed_gate_action":"保留最新資料、降級標示、啟動滾動檢討"},"notice":"歷史資料可用來檢測偏差與比較模型，但不能把未通過獨立封存驗證的軌跡宣稱為確定規律。本系統只發布可稽核的機率排序，不保證中獎。請量力而為，未滿18歲不得投注。"}

if __name__=="__main__":
    result=analyze(load_draws())
    out=ROOT/"reports"/"latest_analysis.json"; out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({"history":result["history"],"target":result["target_date"],"gate":result["release_gate"],"packs":result["packs"]},ensure_ascii=False,indent=2))
