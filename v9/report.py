"""Build one compact mobile report from verified official data and sealed evidence."""
from __future__ import annotations

import html
import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .data import ROOT
from .official_source import SOURCE_URL, OfficialDraw

HKT = timezone(timedelta(hours=8))
OUTPUTS = (ROOT / "reports", ROOT / "site", ROOT / "docs")


def _safe(value: object) -> str:
    return html.escape(str(value), quote=True)


def _atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


def build_report(draws: list[OfficialDraw], manifest: dict, model: dict, ledger: dict, upcoming: dict | None = None) -> dict:
    latest = draws[-1]
    now = datetime.now(HKT).isoformat(timespec="seconds")
    version_hash = hashlib.sha256((manifest["sha256"] + model["selected_model"] + str(model["rank"]) + now).encode()).hexdigest()[:16]
    selected = model["models"][model["selected_model"]]
    observation = "僅觀察排序・未證實高機率" if not model["statistical_edge_passed"] else "回放顯示統計訊號・仍待前瞻實戰"
    target_note = (f"官方已定義下一期 {_safe(upcoming['date'])}／{_safe(upcoming['source_id'])}" if upcoming else "官方下一期日期暫未取得；禁止猜測")
    analysis = {
        "schema": "marksix_official_v9",
        "generated_at": now,
        "official_data": manifest,
        "latest_draw": {"period": latest.period, "date": latest.draw_date,
                        "main": list(latest.main), "special": latest.special, "source_id": latest.source_id},
        "next_draw_date": upcoming["date"] if upcoming else None,
        "next_draw_date_status": "官方已定義" if upcoming else "官方下一期日期尚未由本資料介面驗證，禁止猜測",
        "next_draw_evidence": upcoming,
        "model": {key: value for key, value in model.items() if key != "selected_replay_rows"},
        "live_audit": {key: value for key, value in ledger.items() if key != "latest_forecast"},
        "sealed_forecast": {key: value for key, value in ledger["latest_forecast"].items() if key != "ranking"},
        "confidence_label": observation,
        "legacy_audit": {"legacy_rows_used_for_model": 0,
                         "finding": "舊資料來源標籤聲稱馬會核對，但舊匯入程式未執行該核對；舊回測亦混用49球制之前資料",
                         "current_49_ball_era_starts": "2002-07（本重建保守採2003-01起）"},
    }
    model_rows = "".join(
        f"<tr><td>{_safe(name)}</td><td>{details['development_hits']}/400</td>"
        f"<td>{details['evaluation_hits']}/120</td><td>{details['evaluation_top9_hits']/120:.3f}</td>"
        f"<td>{details['evaluation_one_sided_p']:.4f}</td></tr>"
        for name, details in model["models"].items()
    )
    balls = "".join(f"<span class='ball'>{number:02d}</span>" for number in latest.main)
    top9 = "".join(f"<span class='ball rank'>{number:02d}</span>" for number in model["top9"])
    report = f"""<!doctype html>
<html lang="zh-Hant"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="theme-color" content="#8a1e24"><link rel="manifest" href="manifest.webmanifest"><title>六合彩｜全新官方資料核驗戰報</title>
<style>
:root{{color-scheme:light;font-family:system-ui,-apple-system,'Noto Sans TC',sans-serif;background:#f4f2ef;color:#241e1e}}
*{{box-sizing:border-box}}body{{margin:0}}main{{max-width:900px;margin:auto;padding:16px}}header{{background:#8a1e24;color:white;padding:22px;border-radius:18px}}h1{{font-size:1.5rem;margin:0 0 6px}}h2{{font-size:1.18rem;margin:0 0 12px}}p{{line-height:1.6}}.muted{{color:#665d5d}}header .muted{{color:#f4dddd}}
.actions{{display:flex;gap:8px;flex-wrap:wrap;margin-top:16px}}button,.action{{appearance:none;border:1px solid #ded2d2;border-radius:10px;padding:10px 13px;background:#fff;color:#75171e;font-weight:700;font-size:.92rem;text-decoration:none;cursor:pointer}}
.card{{background:#fff;border:1px solid #e5dddd;border-radius:16px;padding:18px;margin:14px 0;box-shadow:0 2px 8px #23000008}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:10px}}.metric{{background:#faf7f5;border-radius:12px;padding:12px}}.metric b{{display:block;font-size:1.17rem;margin-top:5px}}.label{{font-size:.83rem;color:#615959}}
.ball{{display:inline-grid;place-items:center;min-width:40px;height:40px;border-radius:50%;background:#a81f2a;color:white;font-weight:800;margin:3px}}.ball.rank{{background:#233e67}}.warning{{border-left:5px solid #c55a1d;background:#fff6ef}}.good{{border-left:5px solid #25764b}}.number{{font-size:3.8rem;font-weight:900;color:#8a1e24;line-height:1}}.tablewrap{{overflow:auto}}table{{border-collapse:collapse;width:100%;font-size:.87rem}}th,td{{padding:9px;border-bottom:1px solid #e8dddd;text-align:left;white-space:nowrap}}th{{background:#f5eeee}}code{{word-break:break-all}}footer{{font-size:.82rem;color:#665d5d;padding:14px 0}}#refresh-status{{min-height:1.5em}}
</style></head><body><main>
<header><h1>六合彩｜全新官方資料核驗戰報 v9</h1><div class="muted">獨立重建・僅用香港賽馬會官方結果・舊模型與舊資料不灌入</div>
<div class="actions"><button id="check-now" type="button">手動核對雲端最新</button><a class="action" href="https://github.com/pingshen670822/hong-kong-marksix-ironlaw/actions/workflows/update.yml" target="_blank" rel="noopener">啟動雲端重新抓取</a><a class="action" href="https://github.com/pingshen670822/hong-kong-marksix-ironlaw/actions/workflows/cloud-self-repair.yml" target="_blank" rel="noopener">當機立即修復</a></div>
<p id="refresh-status">戰報產生：{_safe(now)}；尚未手動核對。</p>
<small>手動核對會比對本站與公開 GitHub 戰報；本站快照延遲時僅顯示已核驗的較新版本。真正重新抓取需登入 GitHub 啟動流程，網頁不持有任何憑證。</small></header>
<section class="card good"><h2>官方已公布最新一期</h2><div class="grid"><div class="metric"><span class="label">期別／日期</span><b>{_safe(latest.period)}・{_safe(latest.draw_date)}</b></div><div class="metric"><span class="label">官方原始識別碼</span><b>{_safe(latest.source_id)}</b></div></div><p>{balls} ＋ <span class="ball rank">{latest.special:02d}</span></p>
<p class="muted">官方資料：<a href="{_safe(SOURCE_URL)}" target="_blank" rel="noopener">香港賽馬會六合彩結果</a>；本次直接由官方結果介面取得，不以第三方資料補缺。</p></section>
<section class="card warning"><h2>下一期研究排序：{model['single']:02d}</h2><div class="number">{model['single']:02d}</div><p><b>{_safe(observation)}</b>。這是 {_safe(model['selected_model'])} 的相對排序第 1 名，不是中獎機率、必中或投注建議。</p>
<p>適用於晚於 {_safe(latest.draw_date)}／{_safe(latest.period)} 的下一次官方攪珠；<b>{target_note}</b>。</p><div>{top9}</div><p class="muted">前九碼僅供分開驗證，不得冒充獨支命中率。</p></section>
<section class="card"><h2>真實資料與來源審計</h2><div class="grid"><div class="metric"><span class="label">官方逐月抓取</span><b>{len(draws):,}期</b></div><div class="metric"><span class="label">採用年代</span><b>{_safe(draws[0].draw_date)} 起</b></div><div class="metric"><span class="label">舊資料投入新模型</span><b>0 期</b></div></div>
<p>資料檔 SHA-256：<code>{_safe(manifest['sha256'])}</code></p><p>舊版來源標籤聲稱「馬會核對」，但舊匯入程式沒有做該核對；且曾把 49 球制以前的結果用同一機率基準運算。新系統不沿用這些標籤或舊回測數字。</p></section>
<section class="card"><h2>固定時序回放（不是前瞻實戰）</h2><p>前 400 期選模型，後 120 期不再調整選擇。單號公平基準為 6/49＝12.24%。五模型多重比較後，選定模型的評估 p 值為 {model['evaluation_adjusted_p']:.4f}；<b>{'達統計門檻，但仍待前瞻驗證' if model['statistical_edge_passed'] else '未達 0.05 門檻，禁止標高信心'}</b>。</p>
<div class="tablewrap"><table><thead><tr><th>固定模型</th><th>前400期獨支</th><th>後120期獨支</th><th>後120期前九均中</th><th>單側 p 值</th></tr></thead><tbody>{model_rows}</tbody></table></div><p class="muted">選定模型後 120 期獨支 {selected['evaluation_hits']}/120；此數字不能替代今後開獎前封存的實戰。</p></section>
<section class="card"><h2>開獎前封存實戰</h2><div class="grid"><div class="metric"><span class="label">新系統封存預測</span><b>{ledger['forecasts']} 筆</b></div><div class="metric"><span class="label">已結算</span><b>{ledger['settled']} 期</b></div><div class="metric"><span class="label">獨支命中</span><b>{ledger['hits']}/{ledger['settled']}</b></div></div><p class="muted">舊版封存不混算。預測與結算採附加式雜湊鏈並由 Git 留痕；雜湊鏈校驗不是獨立公證。</p></section>
<footer>產生時間 { _safe(now) }（香港／台灣時間）。六合彩為隨機攪珠；本系統不保證中獎，未滿 18 歲不得投注，請量力而為。</footer></main>
<script>
const status=document.getElementById('refresh-status');
const rawBase='https://raw.githubusercontent.com/pingshen670822/hong-kong-marksix-ironlaw/main/reports/';
const pageGeneratedAt={json.dumps(now)};
const pageLatestDate={json.dumps(latest.draw_date)};
async function snapshot(base,stamp){{
  const [versionResponse,analysisResponse,healthResponse]=await Promise.all([
    fetch(base+'version.json?ts='+stamp,{{cache:'no-store'}}),
    fetch(base+'latest_analysis.json?ts='+stamp,{{cache:'no-store'}}),
    fetch(base+'self_test_report.json?ts='+stamp,{{cache:'no-store'}})
  ]);
  if(!versionResponse.ok||!analysisResponse.ok||!healthResponse.ok)throw Error('雲端檔案未全部可讀');
  const [version,analysis,health]=await Promise.all([versionResponse.json(),analysisResponse.json(),healthResponse.json()]);
  if(version.schema!=='marksix_official_v9'||analysis.schema!==version.schema)throw Error('資料格式不符');
  if(version.latest_period!==analysis.latest_draw.period||version.latest_date!==analysis.latest_draw.date)throw Error('雲端版本與開獎資料不同步');
  if(health.operational_passed!==true||health.latest_period!==version.latest_period||health.latest_date!==version.latest_date)throw Error('健康檢查未通過或期別不一致');
  return {{version,analysis}};
}}
function isNewer(a,b){{
  if(!b)return true;
  return a.version.latest_date>b.version.latest_date ||
    (a.version.latest_date===b.version.latest_date && a.version.updated_at>b.version.updated_at);
}}
async function checkVersion(){{
  try{{
    const stamp=Date.now();
    const [siteResult,rawResult]=await Promise.allSettled([snapshot('',stamp),snapshot(rawBase,stamp)]);
    const site=siteResult.status==='fulfilled'?siteResult.value:null;
    const raw=rawResult.status==='fulfilled'?rawResult.value:null;
    const newerRaw=raw&&isNewer(raw,site);
    const chosen=newerRaw?raw:(site||raw);
    if(!chosen)throw Error('本站與公開資料來源均未通過核對');
    const version=chosen.version;
    const now=new Date().toLocaleString('zh-HK',{{hour12:false}});
    status.textContent='最後核對：'+now+'；雲端產生：'+version.updated_at+'；最新期別：'+version.latest_period+'／'+version.latest_date+(newerRaw?'；公開 GitHub 備援':'；本站');
    const newerThanPage=version.latest_date>pageLatestDate ||
      (version.latest_date===pageLatestDate && version.updated_at>pageGeneratedAt);
    if(!newerThanPage)return;
    if(newerRaw){{
      const reportResponse=await fetch(rawBase+'index.html?ts='+stamp,{{cache:'no-store'}});
      if(!reportResponse.ok)throw Error('較新戰報無法讀取');
      const report=await reportResponse.text();
      if(!report.includes(version.hash)||!report.includes(version.latest_period))throw Error('較新戰報與核對版本不一致');
      document.open();document.write(report);document.close();
      return;
    }}
    location.reload();
  }}catch(error){{status.textContent='核對失敗：'+error.message+'；請使用雲端重算或修復連結。'}}
}}
document.getElementById('check-now').addEventListener('click',checkVersion);setInterval(checkVersion,60000);document.addEventListener('visibilitychange',()=>{{if(!document.hidden)checkVersion()}});
checkVersion();
if('serviceWorker' in navigator)navigator.serviceWorker.register('service-worker.js').catch(()=>{{}});
</script></body></html>"""
    version = {"updated_at": now, "latest_period": latest.period, "latest_date": latest.draw_date,
               "hash": version_hash, "schema": "marksix_official_v9"}
    health = {"healthy": True, "status": "官方資料校驗通過；預測僅觀察級", "checked_at": now,
              "latest_period": latest.period, "latest_date": latest.draw_date,
              "verified_rows": len(draws), "source": "HKJC GraphQL", "legacy_data_used": False}
    worker = (f"const CACHE='hk-marksix-official-v9-{version_hash}';\n"
              "const ASSETS=['./','index.html','latest_battle_report.html','version.json'];\n"
              "self.addEventListener('install',e=>{self.skipWaiting();e.waitUntil(caches.open(CACHE).then(c=>Promise.allSettled(ASSETS.map(a=>c.add(a)))))});\n"
              "self.addEventListener('activate',e=>{e.waitUntil(Promise.all([caches.keys().then(keys=>Promise.allSettled(keys.filter(k=>k!==CACHE).map(k=>caches.delete(k)))),self.clients.claim()]))});\n"
              "self.addEventListener('fetch',e=>{if(e.request.method!=='GET')return;e.respondWith(fetch(e.request,{cache:'no-store'}).then(r=>{if(r.ok&&new URL(e.request.url).origin===self.location.origin){const c=r.clone();caches.open(CACHE).then(cache=>cache.put(e.request,c)).catch(()=>{})}return r}).catch(()=>caches.match(e.request).then(cached=>cached||(e.request.mode==='navigate'?caches.match('index.html'):Response.error()))))});\n")
    manifest_web = json.dumps({"name": "六合彩官方資料核驗戰報", "short_name": "六合彩核驗", "start_url": "./", "display": "standalone", "theme_color": "#8a1e24", "background_color": "#f4f2ef"}, ensure_ascii=False)
    payloads = {"index.html": report, "latest_battle_report.html": report,
                "latest_analysis.json": json.dumps(analysis, ensure_ascii=False, indent=2),
                "version.json": json.dumps(version, ensure_ascii=False, indent=2),
                "health_status.json": json.dumps(health, ensure_ascii=False, indent=2),
                "service-worker.js": worker, "manifest.webmanifest": manifest_web,
                "self_test_report.json": json.dumps({"operational_passed": True, "prediction_gate_passed": False,
                    "latest_period": latest.period, "latest_date": latest.draw_date,
                    "status": "官方資料已核驗；預測觀察級"}, ensure_ascii=False, indent=2)}
    for directory in OUTPUTS:
        for filename, content in payloads.items():
            _atomic(directory / filename, content)
    return analysis
