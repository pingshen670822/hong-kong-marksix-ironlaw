from __future__ import annotations

import csv, json, math, statistics
from collections import Counter
from dataclasses import dataclass
from datetime import date, timedelta
from itertools import combinations
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data" / "official_marksix.csv"
N = 49

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
        # Regime slope: recent probability versus stable background, clipped and shrunk.
        short=(y[-30:].sum(0)+base*90)/120; long=(y[-240:].sum(0)+base*180)/420
        result["regime_slope"]=normalize_probability(long+np.clip(short-long,-.025,.025),total)
    return result

def brier(p: np.ndarray,y: np.ndarray) -> float: return float(np.mean((p-y)**2))
def logloss(p: np.ndarray,y: np.ndarray) -> float:
    p=np.clip(p,1e-6,1-1e-6); return float(-np.mean(y*np.log(p)+(1-y)*np.log(1-p)))

def walk_forward(draws: list[Draw], rounds: int=520, special: bool=False) -> dict:
    start=max(360,len(draws)-rounds); names=list(model_suite(draws[:start],special))
    losses={n:[] for n in names}; hits={n:[] for n in names}; ensemble_rows=[]
    weights=np.ones(len(names))/len(names)
    for i in range(start,len(draws)):
        models=model_suite(draws[:i],special); actual=np.zeros(N)
        actual[(draws[i].special-1 if special else np.array(draws[i].main)-1)]=1
        preds=np.stack([models[n] for n in names]); k=3 if special else 12
        if losses[names[0]]:
            expected=k*(1 if special else 6)/49
            uniform_ll=logloss(np.full(N,(1 if special else 6)/N),actual)
            quality=[]
            for n in names:
                recent_hits=statistics.mean(hits[n][-120:])
                recent_loss=statistics.mean(losses[n][-120:])
                quality.append(recent_hits-expected-8*max(0,recent_loss-uniform_ll))
            q=np.array(quality); weights=np.exp(2.2*(q-q.max())); weights/=weights.sum()
            for _ in range(3):
                weights=np.minimum(weights,.30); weights/=weights.sum()
        raw_ensemble=np.average(preds,axis=0,weights=weights)
        # Lottery signals are weak: shrink aggressively toward the fair-draw prior while preserving rank.
        prior=np.full(N,(1 if special else 6)/N)
        ensemble=.20*raw_ensemble+.80*prior
        ensemble_rows.append({"period":draws[i].period,"date":draws[i].draw_date,"hit":int(actual[np.argsort(ensemble)[-k:]].sum()),"brier":brier(ensemble,actual),"logloss":logloss(ensemble,actual)})
        step=[]
        for j,n in enumerate(names):
            hit=int(actual[np.argsort(preds[j])[-k:]].sum())
            loss=logloss(preds[j],actual); losses[n].append(loss); hits[n].append(hit); step.append(loss)
    uniform=np.full(N,(1 if special else 6)/N)
    actuals=[]
    for d in draws[start:]:
        y=np.zeros(N); y[(d.special-1 if special else np.array(d.main)-1)]=1; actuals.append(y)
    uniform_loss=statistics.mean(logloss(uniform,y) for y in actuals)
    ensemble_loss=statistics.mean(r["logloss"] for r in ensemble_rows)
    return {"rounds":len(ensemble_rows),"names":names,"weights":{n:round(float(w),8) for n,w in zip(names,weights)},"model_logloss":{n:round(statistics.mean(v),8) for n,v in losses.items()},"model_avg_hits":{n:round(statistics.mean(hits[n]),4) for n in names},"ensemble_logloss":round(ensemble_loss,8),"uniform_logloss":round(uniform_loss,8),"logloss_edge":round(uniform_loss-ensemble_loss,8),"avg_hits":round(statistics.mean(r["hit"] for r in ensemble_rows),4),"rows":ensemble_rows}

def final_scores(draws: list[Draw], bt: dict, special=False) -> np.ndarray:
    models=model_suite(draws,special); names=bt["names"]
    w=np.array([bt["weights"][n] for n in names]); w/=w.sum()
    raw=np.average(np.stack([models[n] for n in names]),axis=0,weights=w)
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
    main_bt=walk_forward(draws,520,False); special_bt=walk_forward(draws,520,True)
    ms=final_scores(draws,main_bt); ss=final_scores(draws,special_bt,True)
    rank=(np.argsort(ms)[::-1]+1).tolist(); srank=(np.argsort(ss)[::-1]+1).tolist()
    # Publication gate measures calibration, not fabricated certainty.
    main_random=12*6/49; special_random=3/49
    gate=main_bt["avg_hits"]>main_random and special_bt["avg_hits"]>=special_random and main_bt["logloss_edge"]>=-0.0005 and special_bt["logloss_edge"]>=-0.0005
    return {"system":"香港六合彩新世代鐵律預測系統","engine":"marksix_cleanroom_ensemble_v3","generated_at":date.today().isoformat(),"history":{"count":len(draws),"first":draws[0].draw_date,"latest":draws[-1].draw_date,"latest_period":draws[-1].period},"latest_draw":{"period":draws[-1].period,"date":draws[-1].draw_date,"main":draws[-1].main,"special":draws[-1].special},"target_date":next_draw(draws[-1].draw_date,draws),"main_rank":[{"rank":i+1,"number":n,"probability":round(float(ms[n-1]),6)} for i,n in enumerate(rank)],"special_rank":[{"rank":i+1,"number":n,"probability":round(float(ss[n-1]),6)} for i,n in enumerate(srank)],"packs":{"最強單支":rank[:1],"二中一":rank[:2],"三中一":rank[:3],"五中二":rank[:5],"九中三":rank[:9],"主攻12碼":rank[:12],"防守18碼":rank[:18]},"special_packs":{"最強單支":srank[:1],"三碼觀察":srank[:3]},"avoid":{"五不中":sorted(rank[-5:]),"十不中":sorted(rank[-10:]),"十五不中":sorted(rank[-15:])},"suggested_sets":build_sets(ms),"rules":{"range":"1–49","main_numbers":6,"extra_numbers":1,"unit_bet_hkd":10,"prizes":{"一獎":"6個正選號碼","二獎":"5個正選號碼＋特別號","三獎":"5個正選號碼","四獎":"4個正選號碼＋特別號（固定HK$9,600）","五獎":"4個正選號碼（固定HK$640）","六獎":"3個正選號碼＋特別號（固定HK$320）","七獎":"3個正選號碼（固定HK$40）"}},"backtest":{"main":main_bt,"special":special_bt},"release_gate":{"passed":gate,"rule":"520期走步驗證須同時通過前段命中與機率校準，且不得由單一模型壟斷","main_edge":main_bt["logloss_edge"],"special_edge":special_bt["logloss_edge"],"main_avg_hits":main_bt["avg_hits"],"main_random_hits":round(main_random,4),"special_avg_hits":special_bt["avg_hits"],"special_random_hits":round(special_random,4),"max_main_weight":max(main_bt["weights"].values())},"notice":"六合彩每期開獎為獨立隨機事件；本系統只做可回測的機率排序，不保證中獎。請量力而為，未滿18歲不得投注。"}

if __name__=="__main__":
    result=analyze(load_draws())
    out=ROOT/"reports"/"latest_analysis.json"; out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({"history":result["history"],"target":result["target_date"],"gate":result["release_gate"],"packs":result["packs"]},ensure_ascii=False,indent=2))
