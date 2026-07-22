from __future__ import annotations
import hashlib,html,json,shutil
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from engine import ROOT

REPORTS=ROOT/"reports"; SITE=ROOT/"site"; DOCS=ROOT/"docs"
def e(x): return html.escape(str(x))
def balls(nums,kind=""): return "".join(f'<span class="ball {kind}">{int(n):02d}</span>' for n in nums)
def table(head,rows,empty="目前沒有已結算資料"):
    body="".join("<tr>"+"".join(f"<td>{x}</td>" for x in row)+"</tr>" for row in rows) or f'<tr><td colspan="{len(head)}">{empty}</td></tr>'
    return '<div class="scroll"><table><tr>'+''.join(f'<th>{e(x)}</th>' for x in head)+f'</tr>{body}</table></div>'

def settled_rows(history):
    out=[]
    for p in reversed(history):
        if p.get("status")!="settled": continue
        s=p["settlement"]; a=p["actual"]; aset=set(a["main"])
        hit_numbers="、".join(map(str,s["pack_hits"]["主攻12碼"]["numbers"])) or "—"
        strongest=p["packs"]["最強單支"][0]
        strongest_hit=strongest in aset
        out.append([e(p["target_date"]),balls([strongest]),"命中" if strongest_hit else "未中",balls(p["packs"]["主攻12碼"]),balls(a["main"],"actual")+f'<span class="special">特 {a["special"]:02d}</span>',e(s["pack_hits"]["主攻12碼"]["count"]),e(hit_numbers),"命中" if s["special_hit"] else "未中"])
    return out

def monthly_rows(history):
    g=defaultdict(list)
    for p in history:
        if p.get("status")=="settled": g[p["target_date"][:7]].append(p)
    out=[]
    for month,items in sorted(g.items(),reverse=True):
        hits=[p["settlement"]["pack_hits"]["主攻12碼"]["count"] for p in items]
        out.append([month,len(items),sum(hits),f"{sum(hits)/len(hits):.2f}",max(hits),sum(p["settlement"]["special_hit"] for p in items)])
    return out

def build_reports(a,history):
    REPORTS.mkdir(exist_ok=True); SITE.mkdir(exist_ok=True); DOCS.mkdir(exist_ok=True)
    cand=a["main_rank"][:18]; bt=a["backtest"]
    candidate_rows=[[x["rank"],balls([x["number"]]),f'{x["probability"]*100:.3f}%'] for x in cand]
    review={x["model"]:x for x in bt["main"]["module_review"]}
    model_rows=[[e(n),review[n]["latest_hit_count"],f'{review[n]["recent_120_avg_hits"]:.3f}',f'{bt["main"]["weights"][n]*100:.2f}%',e(review[n]["decision"])] for n in bt["main"]["names"]]
    low_rows=[]
    for p in reversed(history):
        if p.get("status")!="settled": continue
        err=p["settlement"]["avoid_errors"]["十不中"]
        low_rows.append([e(p["target_date"]),balls(p["avoid"]["十不中"],"avoid"),balls(err,"actual") if err else "—",len(err),"誤開號解除暫避" if err else "守住"])
    html_text=f'''<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="theme-color" content="#86151b"><link rel="manifest" href="manifest.webmanifest"><link rel="stylesheet" href="style.css"><title>香港六合彩新世代鐵律戰報</title></head><body><header><h1>香港六合彩新世代鐵律戰報</h1><p>4,364期歷史基底・520期走步驗證・正選號碼與特別號分離</p></header><nav>{''.join(f'<button data-tab="{i}">{t}</button>' for i,t in [('decision','核心決策'),('verify','逐號驗算'),('packs','短包強牌'),('avoid','低機率'),('review','戰果檢討'),('models','模型回測'),('monthly','每月總結'),('iron','規則與守門')])}</nav><main>
<section id="decision" class="tab active"><div class="cards"><article><b>最新資料</b><strong>{a['latest_draw']['date']}／{a['latest_draw']['period']}</strong></article><article><b>預測目標</b><strong>{a['target_date']}</strong></article><article><b>發布門檻</b><strong class="pass">通過</strong></article></div><h2>明確行動牌</h2>{''.join(f'<article class="pack"><h3>{e(k)}</h3>{balls(v)}</article>' for k,v in a['packs'].items())}<article class="pack specialpack"><h3>特別號三碼觀察</h3>{balls(a['special_packs']['三碼觀察'],'specialball')}</article><h2>八組結構平衡建議</h2>{''.join(f'<article class="set"><b>第{i+1}組</b>{balls(s)}</article>' for i,s in enumerate(a['suggested_sets']))}</section>
<section id="verify" class="tab"><h2>逐號交叉驗算</h2><p>機率經80%公平開獎先驗收縮，避免將微弱歷史訊號包裝成高信心。</p>{table(['順位','號碼','校準機率'],candidate_rows)}</section>
<section id="packs" class="tab"><h2>短包強牌</h2>{''.join(f'<article class="pack"><h3>{e(k)}</h3>{balls(v)}</article>' for k,v in a['packs'].items() if k in ('最強單支','二中一','三中一','五中二','九中三'))}<h2>特別號獨立運算</h2>{''.join(f'<article class="pack specialpack"><h3>{e(k)}</h3>{balls(v,"specialball")}</article>' for k,v in a['special_packs'].items())}</section>
<section id="avoid" class="tab"><h2>下期低機率暫避</h2><p>本區只做風險排序，不代表絕對不開；與攻擊牌完全分離。</p>{''.join(f'<article class="pack low"><h3>{e(k)}</h3>{balls(v,"avoid")}</article>' for k,v in a['avoid'].items())}<h2>上期誤開檢討</h2>{table(['目標日','原十不中','誤開號','顆數','修正'],low_rows)}</section>
<section id="review" class="tab"><h2>預測對實際逐期驗算</h2><p>預測先封存，開獎後只結算，禁止回改舊牌。</p>{table(['目標日','原最強獨支','獨支戰果','原主攻12碼','實際開獎','12碼命中','命中號','特別號'],settled_rows(history))}</section>
<section id="models" class="tab"><h2>520期時間序列走步回測</h2><div class="cards"><article><b>主號12碼平均命中</b><strong>{bt['main']['avg_hits']}</strong><small>隨機基準 1.4694</small></article><article><b>特別號3碼命中</b><strong>{bt['special']['avg_hits']}</strong><small>隨機基準 0.0612</small></article><article><b>最大模型權重</b><strong>{a['release_gate']['max_main_weight']*100:.1f}%</strong></article></div><h2>逐模組錯誤檢討與滾動調整</h2>{table(['模型','上期12碼命中','近120期平均','新權重','調整決策'],model_rows)}<h2>最強獨支運算鐵律</h2><p>所有合格模型依近120期成績重新配權，再取校準機率唯一第1名；只使用開獎前已存在的歷史資料，嚴禁回填或用上期結果冒充預測。</p><h2>失敗回饋規則</h2><ul><li>每期權重只能使用之前120期成績</li><li>落後隨機基準的模型自動降權</li><li>單一模型權重上限30%</li><li>主號與特別號完全分開校準</li></ul></section>
<section id="monthly" class="tab"><h2>每月總整理</h2>{table(['月份','結算期數','總命中','平均命中','單期最高','特別號命中'],monthly_rows(history))}</section>
<section id="iron" class="tab"><h2>最新版六合彩規則</h2><p>1至49選6個正選號碼，每注HK$10；另開1個特別號。</p>{table(['獎級','中獎條件','固定獎金'],[['一獎','6個正選','彩池制'],['二獎','5個正選＋特別號','彩池制'],['三獎','5個正選','彩池制'],['四獎','4個正選＋特別號','HK$9,600'],['五獎','4個正選','HK$640'],['六獎','3個正選＋特別號','HK$320'],['七獎','3個正選','HK$40']])}<h2>鐵律守門</h2><ol><li>資料須通過期別、日期、6個正選號碼、特別號完整驗證</li><li>預測封存後不可因開獎結果修改</li><li>回測嚴格按時間順序，禁止偷看未來</li><li>主攻、低機率、上期檢討、月結分區顯示</li><li>抓號失敗保留最後有效版本</li><li>臨時開彩日及金多寶一律以香港賽馬會公告為準</li></ol><h2>生命週期</h2><p>開獎資料 → 完整性驗證 → 上期結算 → 失敗回饋 → 520期重測 → 新預測封存 → 戰報生成 → 手機同步</p></section>
<p class="notice">{e(a['notice'])}</p></main><footer>資料基準 {a['latest_draw']['date']}・目標 {a['target_date']}・核心 {a['engine']}</footer><script src="app.js"></script></body></html>'''
    css='''*{box-sizing:border-box}body{margin:0;background:#fff7ea;color:#281916;font-family:system-ui,"Noto Sans TC",sans-serif}header{padding:30px 16px;text-align:center;color:#fff;background:linear-gradient(135deg,#611017,#b72b22)}header h1{margin:0}nav{position:sticky;top:0;z-index:5;display:flex;overflow:auto;background:#fff;box-shadow:0 3px 14px #0002}nav button{min-width:105px;flex:1;padding:14px 8px;border:0;background:#fff;font-weight:800}nav button.on{color:#971923;border-bottom:4px solid #971923}main{max-width:1050px;margin:auto;padding:18px}.tab{display:none}.tab.active{display:block}.cards{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}.cards article,.pack,.set{background:#fff;border-radius:16px;padding:16px;margin:10px 0;box-shadow:0 4px 18px #5d1b1015}.cards b,.cards strong,.cards small{display:block;margin:5px}.pass{color:#087348}.pack{border-left:6px solid #ac7a1f}.low{border-color:#596576}.specialpack{border-color:#d08a00}.ball{display:inline-grid;place-items:center;width:39px;height:39px;margin:4px;border-radius:50%;background:#a71c23;color:white;font-weight:900}.actual{background:#087348}.avoid{background:#596576}.specialball,.special{background:#d08a00}.special{display:inline-block;padding:8px;color:#fff;border-radius:10px}.scroll{overflow:auto}table{width:100%;border-collapse:collapse;background:#fff}th,td{padding:10px;border-bottom:1px solid #ead7c4;text-align:left}.notice,footer{text-align:center;padding:18px;color:#6b5049}@media(max-width:680px){.cards{grid-template-columns:1fr}.ball{width:34px;height:34px;margin:3px}th,td{min-width:90px;font-size:14px}}'''
    js='''document.querySelectorAll('nav button').forEach((b,i)=>{if(!i)b.classList.add('on');b.onclick=()=>{document.querySelectorAll('.tab').forEach(x=>x.classList.remove('active'));document.querySelectorAll('nav button').forEach(x=>x.classList.remove('on'));document.getElementById(b.dataset.tab).classList.add('active');b.classList.add('on')}});if('serviceWorker'in navigator)navigator.serviceWorker.register('service-worker.js');'''
    analysis=json.dumps(a,ensure_ascii=False,indent=2); version={"updated_at":datetime.now().isoformat(timespec="seconds"),"latest_period":a["latest_draw"]["period"],"hash":hashlib.sha256(analysis.encode()).hexdigest()[:16]}
    for base in (REPORTS,SITE,DOCS):
        (base/"index.html").write_text(html_text,encoding="utf-8"); (base/"latest_battle_report.html").write_text(html_text,encoding="utf-8"); (base/"latest_analysis.json").write_text(analysis,encoding="utf-8"); (base/"prediction_history.json").write_text(json.dumps(history,ensure_ascii=False,indent=2),encoding="utf-8"); (base/"version.json").write_text(json.dumps(version,ensure_ascii=False,indent=2),encoding="utf-8"); (base/"style.css").write_text(css,encoding="utf-8"); (base/"app.js").write_text(js,encoding="utf-8"); (base/"manifest.webmanifest").write_text(json.dumps({"name":"香港六合彩新世代鐵律戰報","short_name":"六合彩戰報","start_url":"./","display":"standalone","theme_color":"#86151b","background_color":"#fff7ea"},ensure_ascii=False),encoding="utf-8"); (base/"service-worker.js").write_text("const C='hk-marksix-v3';self.addEventListener('install',e=>e.waitUntil(caches.open(C).then(c=>c.addAll(['./','index.html','style.css','app.js']))));self.addEventListener('fetch',e=>e.respondWith(fetch(e.request).catch(()=>caches.match(e.request))))",encoding="utf-8")
