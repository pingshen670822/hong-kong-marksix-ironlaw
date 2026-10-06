from __future__ import annotations
import hashlib,html,json,re,shutil
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from engine import ROOT

REPORTS=ROOT/"reports"; SITE=ROOT/"site"; DOCS=ROOT/"docs"
REPORT_SCHEMA_VERSION="2026-10-06-mobile-manual-repair-v3"
def e(x): return html.escape(str(x))
def balls(nums,kind=""): return "".join(f'<span class="ball {kind}">{int(n):02d}</span>' for n in nums)
def atomic_write(path: Path,text: str):
    tmp=path.with_suffix(path.suffix+".tmp")
    tmp.write_text(text,encoding="utf-8")
    tmp.replace(path)
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
    gate_pass=bool(a["release_gate"]["passed"])
    gate_text="超高共識通過" if gate_pass else "觀察級・滾動檢修中"
    gate_class="pass" if gate_pass else "warn"
    analysis=json.dumps(a,ensure_ascii=False,indent=2)
    version={"updated_at":datetime.now().isoformat(timespec="seconds"),"latest_period":a["latest_draw"]["period"],"hash":hashlib.sha256((REPORT_SCHEMA_VERSION+analysis).encode()).hexdigest()[:16]}
    candidate_rows=[[x["rank"],balls([x["number"]]),f'{x["probability"]*100:.3f}%'] for x in cand]
    review={x["model"]:x for x in bt["main"]["module_review"]}
    model_rows=[[e(n),review[n]["latest_hit_count"],f'{review[n]["recent_30_avg_hits"]:.3f}',f'{review[n]["recent_120_avg_hits"]:.3f}',f'{review[n]["recent_360_avg_hits"]:.3f}',review[n]["failure_streak"],f'{bt["main"]["weights"][n]*100:.2f}%',e(review[n]["decision"])] for n in bt["main"]["names"]]
    rank_audit_rows=[[f"近{w}期",f'{bt["main"]["first_hit_rank_audit"][w]["within_9_rate"]*100:.1f}%',bt["main"]["first_hit_rank_audit"][w]["average_first_hit_rank"],bt["main"]["first_hit_rank_audit"][w]["outside_9_count"]] for w in ("10","30","60","120")]
    cc=bt["main"]["champion_challenger"]
    champion_rows=[["原機率集成",cc["champion"]["avg520"],cc["champion"]["recent60"],cc["champion"]["recent120"],cc["champion"]["logloss"]],["名次共識混合",cc["challenger"]["avg520"],cc["challenger"]["recent60"],cc["challenger"]["recent120"],cc["challenger"]["logloss"]]]
    low_rows=[]
    for p in reversed(history):
        if p.get("status")!="settled": continue
        err=p["settlement"]["avoid_errors"]["十不中"]
        low_rows.append([e(p["target_date"]),balls(p["avoid"]["十不中"],"avoid"),balls(err,"actual") if err else "—",len(err),"誤開號解除暫避" if err else "守住"])
    html_text=f'''<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="theme-color" content="#86151b"><meta name="report-version" content="{version['hash']}"><link rel="manifest" href="manifest.webmanifest"><link rel="stylesheet" href="style.css"><title>香港六合彩新世代鐵律戰報</title></head><body><header><h1>香港六合彩新世代鐵律戰報</h1><p>{a['history']['count']:,}期歷史基底・520期走步驗證・資料更新與模型守門雙軌分離</p></header><nav>{''.join(f'<button data-tab="{i}">{t}</button>' for i,t in [('decision','核心決策'),('verify','逐號驗算'),('packs','短包強牌'),('avoid','低機率'),('review','戰果檢討'),('models','模型回測'),('monthly','每月總結'),('iron','規則與守門')])}</nav><main>
<section id="decision" class="tab active"><section class="cloud-actions" aria-label="雲端更新與修復"><div class="action-buttons"><button type="button" id="manual-refresh" class="cloud-action refresh-action">手動更新最新</button><button type="button" id="emergency-repair" class="cloud-action repair-action">當機立即修復</button></div><p id="cloud-action-status" class="cloud-action-status" role="status" aria-live="polite">可隨時強制檢查最新資料；當機修復會清除失效快取並重新連接雲端。</p></section><div class="cards"><article><b>最新資料</b><strong>{a['latest_draw']['date']}／{a['latest_draw']['period']}</strong></article><article><b>預測目標</b><strong>{a['target_date']}</strong><small>{e(a.get('target_source',''))}</small></article><article><b>預測信心守門</b><strong class="{gate_class}">{gate_text}</strong></article><article><b>雲端雙層自修復</b><strong class="pass">監控正常</strong><small>每小時檢查・開獎後密集重試・失敗自動切換第二層救援</small></article></div><h2>明確行動牌</h2>{''.join(f'<article class="pack"><h3>{e(k)}</h3>{balls(v)}</article>' for k,v in a['packs'].items())}<article class="pack specialpack"><h3>特別號三碼觀察</h3>{balls(a['special_packs']['三碼觀察'],'specialball')}</article><h2>八組結構平衡建議</h2>{''.join(f'<article class="set"><b>第{i+1}組</b>{balls(s)}</article>' for i,s in enumerate(a['suggested_sets']))}</section>
<section id="verify" class="tab"><h2>逐號交叉驗算</h2><p>機率經80%公平開獎先驗收縮，避免將微弱歷史訊號包裝成高信心。</p>{table(['順位','號碼','校準機率'],candidate_rows)}</section>
<section id="packs" class="tab"><h2>短包強牌</h2>{''.join(f'<article class="pack"><h3>{e(k)}</h3>{balls(v)}</article>' for k,v in a['packs'].items() if k in ('最強單支','二中一','三中一','五中二','九中三'))}<h2>特別號獨立運算</h2>{''.join(f'<article class="pack specialpack"><h3>{e(k)}</h3>{balls(v,"specialball")}</article>' for k,v in a['special_packs'].items())}</section>
<section id="avoid" class="tab"><h2>下期低機率暫避</h2><p>本區只做風險排序，不代表絕對不開；與攻擊牌完全分離。</p>{''.join(f'<article class="pack low"><h3>{e(k)}</h3>{balls(v,"avoid")}</article>' for k,v in a['avoid'].items())}<h2>上期誤開檢討</h2>{table(['目標日','原十不中','誤開號','顆數','修正'],low_rows)}</section>
<section id="review" class="tab"><h2>預測對實際逐期驗算</h2><p>預測先封存，開獎後只結算，禁止回改舊牌。</p>{table(['目標日','原最強獨支','獨支戰果','原主攻12碼','實際開獎','12碼命中','命中號','特別號'],settled_rows(history))}</section>
<section id="models" class="tab"><h2>520期前9碼時間序列走步回測</h2><div class="cards"><article><b>前9碼平均命中</b><strong>{bt['main']['avg_hits']}</strong><small>隨機基準 {a['release_gate']['main_random_hits']}</small></article><article><b>近60期至少1顆進前9</b><strong>{bt['main']['first_hit_rank_audit']['60']['within_9_rate']*100:.1f}%</strong><small>隨機基準 {bt['main']['within9_random_baseline']*100:.1f}%</small></article><article><b>近120期前9碼命中</b><strong>{bt['main']['ensemble_recent_hits']['120']}</strong><small>超高共識門檻 ≥ {a['release_gate']['main_random_hits']}</small></article></div><h2>第10名後問題專項檢測</h2>{table(['窗口','至少1顆進前9比例','首顆平均名次','完全落在9名後期數'],rank_audit_rows)}<h2>前9碼三層滾動權重</h2><p>{e(bt['main']['weighting_strategy'])}</p><h2>逐模組錯誤檢討與滾動調整</h2>{table(['模型','上期前9命中','近30期','近120期','近360期','連續失誤','新權重','調整決策'],model_rows)}<h2>最強獨支運算鐵律</h2><p>所有模型以「前9碼命中」為訓練與扣權目標，依30／120／360期成績、校準誤差與連續失誤重新配權，再取校準機率唯一第1名；只使用開獎前已存在的歷史資料，嚴禁回填。</p><h2>失敗回饋規則</h2><ul><li>每期檢查所有實際號碼的預測名次</li><li>首顆命中落到第10名後即列入錯誤檢討</li><li>短期30期占60%，120期占25%，360期占15%</li><li>校準誤差及連續零命中會額外扣權</li><li>單一模型權重上限22%</li><li>未達信心門檻時禁止標示超高信心，改列觀察級；最新開獎資料仍必須同步</li></ul></section>
<section id="monthly" class="tab"><h2>每月總整理</h2>{table(['月份','結算期數','總命中','平均命中','單期最高','特別號命中'],monthly_rows(history))}</section>
<section id="iron" class="tab"><h2>最新版六合彩規則</h2><p>1至49選6個正選號碼，每注HK$10；另開1個特別號。</p>{table(['獎級','中獎條件','固定獎金'],[['一獎','6個正選','彩池制'],['二獎','5個正選＋特別號','彩池制'],['三獎','5個正選','彩池制'],['四獎','4個正選＋特別號','HK$9,600'],['五獎','4個正選','HK$640'],['六獎','3個正選＋特別號','HK$320'],['七獎','3個正選','HK$40']])}<h2>鐵律守門</h2><ol><li>資料須通過期別、日期、6個正選號碼、特別號完整驗證</li><li>預測封存後不可因開獎結果修改</li><li>回測嚴格按時間順序，禁止偷看未來</li><li>主攻、低機率、上期檢討、月結分區顯示</li><li>抓號失敗保留最後有效版本，絕不以假資料覆寫</li><li>主流程失敗自動啟動第二層雲端救援，後續每小時持續重試</li><li>臨時開彩日及金多寶一律以香港賽馬會公告為準</li></ol><h2>生命週期</h2><p>開獎資料 → 雙來源交叉驗證 → 上期結算 → 失敗回饋 → 520期重測 → 健康稽核 → 戰報生成 → 手機同步 → 失敗時第二層救援</p></section>
<p class="notice">{e(a['notice'])}</p></main><footer>資料基準 {a['latest_draw']['date']}・目標 {a['target_date']}・核心 {a['engine']}</footer><script src="app.js"></script></body></html>'''
    conf=bt["main"]["confidence_audit"]; tiers=bt["main"]["recommendation_tiers"]
    check_rows=[[e(name),"通過" if passed else "未通過"] for name,passed in conf["checks"].items()]
    action_title="強烈推薦" if conf["super_consensus"] else "本期最強排序（觀察級）"
    confidence_html=f'''<article class="hero-recommend {'approved' if conf['super_consensus'] else 'degraded'}"><span class="confidence-label">{e(conf['label'])}</span><h2>{action_title} {balls([conf['number']])}</h2><p>校準機率 {conf['calibrated_probability']*100:.3f}%・公平基準 {conf['fair_probability']*100:.3f}%・相對提升 {conf['relative_lift_pct']:.2f}%</p><p>模型前9支持 {conf['model_top9_support']}/{len(bt['main']['names'])}・加權共識 {conf['weighted_support_pct']:.2f}%</p><small>{e(conf['warning'])}</small></article><h2>多項邏輯驗證</h2>{table(['檢查項目','結果'],check_rows)}<h2>清楚分層推薦</h2><article class="pack tier-a"><h3>A級・唯一最強排序</h3>{balls(tiers['A_唯一最強'])}</article><article class="pack tier-b"><h3>B級・前三排序</h3>{balls(tiers['B_高信心前三'])}</article><article class="pack"><h3>C級・核心前九</h3>{balls(tiers['C_核心前九'])}</article><article class="pack"><h3>D級・次高防守</h3>{balls(tiers['D_次高防守'])}</article><article class="pack low"><h3>E級・低機率暫避</h3>{balls(tiers['E_低機率暫避'],'avoid')}</article>'''
    html_text=re.sub(r'<h2>明確行動牌</h2>.*?<article class="pack specialpack">',confidence_html+'<h2>特別號獨立運算</h2><article class="pack specialpack">',html_text,count=1,flags=re.S)
    research=bt["main"]["external_method_review"]
    research_html='<h2>外部預測系統方法研究</h2><h3>通過本系統驗證並採用</h3><ul>'+''.join(f'<li>{e(x)}</li>' for x in research['採用'])+'</ul><h3>拒絕直接採用</h3><ul>'+''.join(f'<li>{e(x)}</li>' for x in research['不直接採用'])+'</ul>'
    challenger_html=f'<h2>冠軍／挑戰者實測</h2><p>本期升級：{e(cc["promoted"])}。{e(cc["rule"])}</p>'+table(['版本','520期','近60期','近120期','對數損失'],champion_rows)
    html_text=html_text.replace('<h2>前9碼三層滾動權重</h2>',research_html+challenger_html+'<h2>前9碼三層滾動權重</h2>')
    css='''*{box-sizing:border-box}body{margin:0;background:#fff7ea;color:#281916;font:16px/1.55 system-ui,"Noto Sans TC",sans-serif}header{padding:26px 16px;text-align:center;color:#fff;background:linear-gradient(135deg,#611017,#b72b22)}header h1{margin:0}nav{position:sticky;top:0;z-index:5;display:flex;overflow:auto;background:#fff;box-shadow:0 3px 14px #0002}nav button{min-width:105px;flex:1;padding:14px 8px;border:0;background:#fff;font-weight:800;font-size:14px}nav button.on{color:#971923;border-bottom:4px solid #971923}main{max-width:1050px;margin:auto;padding:18px}.tab{display:none}.tab.active{display:block}.cloud-actions{margin:0 0 16px;padding:14px;border:1px solid #e0bd86;border-radius:18px;background:linear-gradient(135deg,#fff,#fff1d7);box-shadow:0 5px 20px #5d1b1014}.action-buttons{display:grid;grid-template-columns:1fr 1fr;gap:12px}.cloud-action{min-height:52px;padding:12px 16px;border:0;border-radius:14px;color:#fff;font:900 1rem/1.2 system-ui,"Noto Sans TC",sans-serif;box-shadow:0 5px 14px #3b140f28;cursor:pointer;touch-action:manipulation}.cloud-action:focus-visible{outline:4px solid #e2a82e;outline-offset:3px}.cloud-action:disabled{opacity:.62;cursor:wait}.refresh-action{background:linear-gradient(135deg,#0b6f54,#07906b)}.repair-action{background:linear-gradient(135deg,#7c151b,#bd2824)}.cloud-action-status{min-height:25px;margin:10px 2px 0;color:#634c42;font-size:.9rem}.cloud-action-status.ok{color:#087348;font-weight:800}.cloud-action-status.error{color:#a51f1f;font-weight:800}.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:12px}.cards article,.pack,.set{background:#fff;border-radius:16px;padding:16px;margin:10px 0;box-shadow:0 4px 18px #5d1b1015}.cards b,.cards strong,.cards small{display:block;margin:5px}.pass{color:#087348}.warn{color:#a55c00}.pack{border-left:6px solid #ac7a1f}.tier-a{border-color:#d4a017;background:#fff8d6}.tier-b{border-color:#a71c23}.hero-recommend{padding:22px;margin:18px 0;border:3px solid #d4a017;border-radius:20px;color:#fff;box-shadow:0 8px 28px #71111944}.hero-recommend.approved{background:linear-gradient(135deg,#711119,#b62522)}.hero-recommend.degraded{background:linear-gradient(135deg,#5d3d18,#91651e)}.hero-recommend h2{font-size:1.55rem}.hero-recommend .ball{background:#ffd34e;color:#661017;width:56px;height:56px;font-size:1.35rem}.confidence-label{display:inline-block;padding:7px 12px;border-radius:999px;background:#ffd34e;color:#661017;font-weight:900}.hero-recommend small{display:block;opacity:.95}.low{border-color:#596576}.specialpack{border-color:#d08a00}.ball{display:inline-grid;place-items:center;width:39px;height:39px;margin:4px;border-radius:50%;background:#a71c23;color:white;font-weight:900}.actual{background:#087348}.avoid{background:#596576}.specialball,.special{background:#d08a00}.special{display:inline-block;padding:8px;color:#fff;border-radius:10px}.scroll{overflow:auto}table{width:100%;border-collapse:collapse;background:#fff}th,td{padding:10px;border-bottom:1px solid #ead7c4;text-align:left}.notice,footer{text-align:center;padding:18px;color:#6b5049}@media(max-width:680px){.cards{grid-template-columns:1fr}.ball{width:34px;height:34px;margin:3px}th,td{min-width:90px;font-size:14px}.hero-recommend{padding:16px}.hero-recommend h2{font-size:1.25rem}}@media(max-width:520px){.action-buttons{grid-template-columns:1fr}.cloud-action{min-height:56px;font-size:1.05rem}}'''
    js='''document.querySelectorAll('nav button').forEach((b,i)=>{if(!i)b.classList.add('on');b.onclick=()=>{document.querySelectorAll('.tab').forEach(x=>x.classList.remove('active'));document.querySelectorAll('nav button').forEach(x=>x.classList.remove('on'));document.getElementById(b.dataset.tab).classList.add('active');b.classList.add('on')}});
const pageHash=document.querySelector('meta[name="report-version"]')?.content||'';
const refreshButton=document.getElementById('manual-refresh');
const repairButton=document.getElementById('emergency-repair');
const actionStatus=document.getElementById('cloud-action-status');
const rescueUrl='https://github.com/pingshen670822/hong-kong-marksix-ironlaw/actions/workflows/cloud-self-repair.yml';
let reportHash=pageHash;
function setStatus(message,state=''){if(!actionStatus)return;actionStatus.textContent=message;actionStatus.className='cloud-action-status'+(state?' '+state:'')}
function setBusy(busy){[refreshButton,repairButton].forEach(button=>{if(button)button.disabled=busy})}
async function cloudSnapshot(){const stamp=Date.now();const [versionResponse,analysisResponse]=await Promise.all([fetch('version.json?t='+stamp,{cache:'no-store'}),fetch('latest_analysis.json?t='+stamp,{cache:'no-store'})]);if(!versionResponse.ok||!analysisResponse.ok)throw new Error('cloud-unavailable');return {version:await versionResponse.json(),analysis:await analysisResponse.json()}}
function reloadWith(key,value){const url=new URL(location.href);url.searchParams.set(key,value);location.replace(url.toString())}
async function checkVersion(){try{const snapshot=await cloudSnapshot();reportHash=snapshot.version.hash||reportHash;if(snapshot.version.hash&&snapshot.version.hash!==pageHash){reloadWith('v',snapshot.version.hash);return snapshot}return snapshot}catch(error){return null}}
async function manualRefresh(){setBusy(true);setStatus('正在強制檢查雲端最新開獎資料…');try{const snapshot=await cloudSnapshot();reportHash=snapshot.version.hash||reportHash;if(snapshot.version.hash&&snapshot.version.hash!==pageHash){setStatus('發現新版本，正在載入…','ok');setTimeout(()=>reloadWith('v',snapshot.version.hash),250);return}const draw=snapshot.analysis.latest_draw||{};setStatus(`已是最新：${draw.date||'日期待確認'}／${draw.period||'期別待確認'}（${new Date().toLocaleTimeString('zh-TW',{hour:'2-digit',minute:'2-digit'})}檢查）`,'ok')}catch(error){setStatus('暫時無法連接雲端，請按「當機立即修復」。','error')}finally{setBusy(false)}}
async function resetClient(){if('caches'in window){const keys=await caches.keys();await Promise.all(keys.map(key=>caches.delete(key)))}if('serviceWorker'in navigator){const registrations=await navigator.serviceWorker.getRegistrations();await Promise.all(registrations.map(registration=>registration.unregister()))}}
async function emergencyRepair(){setBusy(true);setStatus('正在清除失效快取並重新連接雲端…');try{await resetClient();const snapshot=await cloudSnapshot();sessionStorage.setItem('marksix-repair-result',`當機修復完成；已重新連接 ${snapshot.analysis?.latest_draw?.period||'最新戰報'}。`);reloadWith('repair',String(Date.now()))}catch(error){sessionStorage.setItem('marksix-repair-result','本機快取已修復；雲端來源仍無法連線，已開啟第二層救援頁。');const rescue=window.open(rescueUrl,'_blank','noopener,noreferrer');if(!rescue)location.href=rescueUrl;else reloadWith('repair',String(Date.now()))}}
refreshButton?.addEventListener('click',manualRefresh);
repairButton?.addEventListener('click',emergencyRepair);
const repairResult=sessionStorage.getItem('marksix-repair-result');if(repairResult){sessionStorage.removeItem('marksix-repair-result');setStatus(repairResult,'ok')}
checkVersion();setInterval(checkVersion,60000);addEventListener('pageshow',checkVersion);addEventListener('visibilitychange',()=>{if(!document.hidden)checkVersion()});if('serviceWorker'in navigator)navigator.serviceWorker.register('service-worker.js').then(registration=>registration.update());'''
    for base in (REPORTS,SITE,DOCS):
        atomic_write(base/"index.html",html_text); atomic_write(base/"latest_battle_report.html",html_text); atomic_write(base/"latest_analysis.json",analysis); atomic_write(base/"prediction_history.json",json.dumps(history,ensure_ascii=False,indent=2)); atomic_write(base/"version.json",json.dumps(version,ensure_ascii=False,indent=2)); atomic_write(base/"style.css",css); atomic_write(base/"app.js",js); atomic_write(base/"manifest.webmanifest",json.dumps({"name":"香港六合彩新世代鐵律戰報","short_name":"六合彩戰報","start_url":"./","display":"standalone","theme_color":"#86151b","background_color":"#fff7ea"},ensure_ascii=False)); atomic_write(base/"service-worker.js",f"const C='hk-marksix-{version['hash']}';self.addEventListener('install',e=>{{self.skipWaiting();e.waitUntil(caches.open(C).then(c=>c.addAll(['./','index.html','style.css','app.js'])));}});self.addEventListener('activate',e=>e.waitUntil(caches.keys().then(ks=>Promise.all(ks.filter(k=>k!==C).map(k=>caches.delete(k))))));self.addEventListener('fetch',e=>e.respondWith(fetch(e.request,{{cache:'no-store'}}).catch(()=>caches.match(e.request))));")
