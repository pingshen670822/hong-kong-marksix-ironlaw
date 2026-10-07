from __future__ import annotations

import hashlib
import html
import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from engine import ROOT


REPORTS = ROOT / "reports"
SITE = ROOT / "site"
DOCS = ROOT / "docs"
HK = timezone(timedelta(hours=8))
REPORT_SCHEMA_VERSION = "2026-10-07-next-draw-repeat-audit-v8"


def e(value):
    return html.escape(str(value))


def balls(numbers, kind=""):
    return "".join(f'<span class="ball {kind}">{int(number):02d}</span>' for number in numbers)


def atomic_write(path: Path, text: str):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def table(headings, rows, empty="目前沒有已結算資料"):
    body = "".join(
        "<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>"
        for row in rows
    ) or f'<tr><td colspan="{len(headings)}" class="empty">{e(empty)}</td></tr>'
    return (
        '<div class="table-wrap"><table><thead><tr>'
        + "".join(f"<th>{e(heading)}</th>" for heading in headings)
        + f"</tr></thead><tbody>{body}</tbody></table></div>"
    )


def settled_rows(history):
    rows = []
    for prediction in reversed(history):
        if prediction.get("status") != "settled":
            continue
        settlement = prediction["settlement"]
        actual = prediction["actual"]
        actual_main = set(actual["main"])
        hit_numbers = "、".join(map(str, settlement["pack_hits"]["主攻12碼"]["numbers"])) or "—"
        strongest = prediction["packs"]["最強單支"][0]
        rows.append([
            e(prediction["target_date"]),
            e(prediction.get("based_on_period", "—")),
            balls([strongest]),
            "命中" if strongest in actual_main else "未中",
            balls(prediction["packs"]["主攻12碼"]),
            balls(actual["main"], "actual") + f'<span class="special">特 {actual["special"]:02d}</span>',
            e(settlement["pack_hits"]["主攻12碼"]["count"]),
            e(hit_numbers),
            "命中" if settlement["special_hit"] else "未中",
        ])
    return rows


def monthly_rows(history):
    grouped = defaultdict(list)
    for prediction in history:
        if prediction.get("status") == "settled":
            grouped[prediction["target_date"][:7]].append(prediction)
    rows = []
    for month, items in sorted(grouped.items(), reverse=True):
        hits = [item["settlement"]["pack_hits"]["主攻12碼"]["count"] for item in items]
        rows.append([month, len(items), sum(hits), f"{sum(hits) / len(hits):.2f}", max(hits), sum(item["settlement"]["special_hit"] for item in items)])
    return rows


def build_reports(analysis_data, history):
    for directory in (REPORTS, SITE, DOCS):
        directory.mkdir(exist_ok=True)

    candidates = analysis_data["main_rank"][:18]
    backtest = analysis_data["backtest"]
    main_test = backtest["main"]
    gate_passed = bool(analysis_data["release_gate"]["passed"])
    gate_text = "超高共識通過" if gate_passed else "觀察級・未達強推薦門檻"
    gate_class = "ok" if gate_passed else "bad"
    analysis_json = json.dumps(analysis_data, ensure_ascii=False, indent=2)
    generated_at = datetime.now(HK).isoformat(timespec="seconds")
    version = {
        "updated_at": generated_at,
        "timezone": "Asia/Taipei",
        "latest_period": analysis_data["latest_draw"]["period"],
        "latest_date": analysis_data["latest_draw"]["date"],
        "hash": hashlib.sha256((REPORT_SCHEMA_VERSION + analysis_json).encode()).hexdigest()[:16],
    }

    candidate_rows = [[candidate["rank"], balls([candidate["number"]]), f'{candidate["probability"] * 100:.3f}%'] for candidate in candidates]
    module_review = {item["model"]: item for item in main_test["module_review"]}
    model_rows = [[
        e(name),
        module_review[name]["latest_hit_count"],
        f'{module_review[name]["recent_30_avg_hits"]:.3f}',
        f'{module_review[name]["recent_120_avg_hits"]:.3f}',
        f'{module_review[name]["recent_360_avg_hits"]:.3f}',
        module_review[name]["failure_streak"],
        f'{main_test["weights"][name] * 100:.2f}%',
        e(module_review[name]["decision"]),
    ] for name in main_test["names"]]
    rank_audit_rows = [[
        f"近{window}期",
        f'{main_test["first_hit_rank_audit"][window]["within_9_rate"] * 100:.1f}%',
        main_test["first_hit_rank_audit"][window]["average_first_hit_rank"],
        main_test["first_hit_rank_audit"][window]["outside_9_count"],
    ] for window in ("10", "30", "60", "120")]
    champion = main_test["champion_challenger"]
    champion_rows = [
        ["原機率集成", champion["champion"]["avg520"], champion["champion"]["recent60"], champion["champion"]["recent120"], champion["champion"]["logloss"]],
        ["名次共識混合", champion["challenger"]["avg520"], champion["challenger"]["recent60"], champion["challenger"]["recent120"], champion["challenger"]["logloss"]],
    ]
    low_rows = []
    for prediction in reversed(history):
        if prediction.get("status") != "settled":
            continue
        errors = prediction["settlement"]["avoid_errors"]["十不中"]
        low_rows.append([
            e(prediction["target_date"]),
            e(prediction.get("based_on_period", "—")),
            balls(prediction["avoid"]["十不中"], "avoid"),
            balls(errors, "actual") if errors else "—",
            len(errors),
            "誤開號解除暫避" if errors else "守住",
        ])

    confidence = main_test["confidence_audit"]
    tiers = main_test["recommendation_tiers"]
    live = analysis_data.get("live_single_audit", {})
    live_total = int(live.get("independent_draws", 0))
    live_hits = int(live.get("hits", 0))
    live_minimum = int(live.get("minimum_independent_samples", 30))
    recent5 = live.get("recent_5", {})
    recent10 = live.get("recent_10", {})
    latest_live = live.get("latest_result") or {}
    proof = analysis_data.get("recalculation_proof", {})
    proof_previous = proof.get("previous_single")
    proof_current = int(proof.get("current_single", confidence["number"]))
    repeat = analysis_data.get("consecutive_single_audit", {})
    repeat_rows = [[e(name), "通過" if passed else "未通過"] for name, passed in repeat.get("checks", {}).items()]
    check_rows = [[e(name), "通過" if passed else "未通過"] for name, passed in confidence["checks"].items()]
    action_title = "強烈推薦・最強獨支" if confidence["super_consensus"] else "本期最強獨支排序（觀察級）"
    confidence_block = f'''
<div class="band strong {'approved' if confidence['super_consensus'] else 'warning'}">
  <div class="badge">{e(confidence['label'])}</div>
  <h2>{action_title}</h2>
  <div class="number">{int(confidence['number']):02d}</div>
  <div class="validation-seals"><span>校準機率 {confidence['calibrated_probability'] * 100:.3f}%</span><span>公平基準 {confidence['fair_probability'] * 100:.3f}%</span><span>模型前9支持 {confidence['model_top9_support']}/{len(main_test['names'])}</span><span>加權共識 {confidence['weighted_support_pct']:.2f}%</span></div>
  <p><b>{e(confidence['warning'])}</b></p>
</div>'''
    recalculation_block = f'''
<div class="band recompute-proof">
  <div class="badge proof-badge">本次確已重新運算</div>
  <h2>更新與重算證據</h2>
  <div class="grid"><div class="card"><div class="label">完整重算完成時間</div><div id="proof-completed" class="value">{e(proof.get('completed_at','—'))}</div></div><div class="card"><div class="label">本次資料依據</div><div id="proof-basis" class="value">{e(proof.get('current_draw_date','—'))}／{e(proof.get('current_period','—'))}</div></div><div class="card"><div class="label">開獎資料是否新增</div><div id="proof-data-change" class="value">{'有新資料' if proof.get('data_changed') else '沒有新開獎'}</div></div><div class="card"><div class="label">獨支重算比較</div><div id="proof-comparison" class="value">{f'{int(proof_previous):02d}' if proof_previous is not None else '首次'} → {proof_current:02d}</div><div id="proof-compare-note" class="note">{'號碼已改變' if proof.get('single_changed') else '重算後維持相同'}</div></div><div class="card"><div class="label">雙來源交叉核對</div><div id="proof-crosscheck" class="value">{int(proof.get('crosschecked_dates',0))}個日期</div></div></div>
  <p><b id="proof-status">{e(proof.get('status','重算狀態待確認'))}</b></p><p class="note">號碼是否改變取決於正式開獎輸入與模型結果；沒有新開獎時不會為了製造更新假象而強行換號。</p>
</div>'''
    next_prediction_block = f'''
<div class="band next-prediction">
  <div class="badge next-badge">下期正式預測</div>
  <h2>目標開獎日：{e(analysis_data['target_date'])}</h2>
  <div class="next-meta">依據最新開獎 {e(analysis_data['latest_draw']['date'])}／{e(analysis_data['latest_draw']['period'])}・{e(analysis_data['target_source'])}</div>
  <div class="grid next-grid"><div class="card next-single"><div class="label">終極獨支</div><div class="number">{int(confidence['number']):02d}</div><div class="note">{e(confidence['label'])}</div></div><div class="card"><div class="label">下期前三排序</div><div class="number-line">{balls(tiers['B_高信心前三'])}</div></div><div class="card"><div class="label">下期核心前九</div><div class="number-line">{balls(tiers['C_核心前九'])}</div></div><div class="card"><div class="label">下期主攻12碼</div><div class="number-line">{balls(analysis_data['packs']['主攻12碼'])}</div></div></div>
  <p class="note">以上全部是 {e(analysis_data['target_date'])} 下期預測，不是上期號碼；開獎資料未新增時，完整重算可能維持同一順位。</p>
  <div class="repeat-audit {'repeat-ok' if repeat.get('reasonable_repeat_passed') else 'repeat-bad'}"><h3>連莊合理性驗證：{'通過' if repeat.get('reasonable_repeat_passed') else '未通過'}</h3><div class="grid"><div class="card"><div class="label">目前連莊</div><div class="value">{int(repeat.get('number',confidence['number'])):02d}・連續{int(repeat.get('streak',1))}期</div></div><div class="card"><div class="label">跨期依據</div><div class="value">{e(repeat.get('previous_basis_period','—'))} → {e(repeat.get('current_basis_period','—'))}</div></div><div class="card"><div class="label">前次封存戰果</div><div class="value">{'命中' if repeat.get('previous_result_hit') is True else ('未中' if repeat.get('previous_result_hit') is False else '尚未結算')}</div></div><div class="card"><div class="label">模型支持</div><div class="value">{int(repeat.get('model_top9_support',0))}/{int(repeat.get('model_count',0))}・{float(repeat.get('weighted_support_pct',0)):.2f}%</div></div></div><p><b>{e(repeat.get('status','連莊驗證待完成'))}</b></p>{table(['連莊守門條件','結果'], repeat_rows)}</div>
</div>'''
    live_accuracy_block = f'''
<div class="band live-audit">
  <h2>終極獨支・封存實戰準確度</h2>
  <div class="grid"><div class="card"><div class="label">獨立開獎日</div><div class="value">{live_total}期</div><div class="note">強推薦門檻 {live_minimum}期</div></div><div class="card"><div class="label">實戰命中</div><div class="value">{live_hits}/{live_total}（{float(live.get('hit_rate', 0))*100:.1f}%）</div><div class="note">單號公平基準 {float(live.get('fair_single_rate', 6/49))*100:.2f}%</div></div><div class="card"><div class="label">近5期</div><div class="value">{int(recent5.get('hits',0))}/{int(recent5.get('draws',0))}（{float(recent5.get('hit_rate',0))*100:.1f}%）</div></div><div class="card"><div class="label">近10期</div><div class="value">{int(recent10.get('hits',0))}/{int(recent10.get('draws',0))}（{float(recent10.get('hit_rate',0))*100:.1f}%）</div></div><div class="card"><div class="label">最長連續未中</div><div class="value">{int(live.get('longest_miss_streak',0))}期</div></div><div class="card"><div class="label">最新封存結果</div><div class="value">{e(latest_live.get('target_date','—'))}・{int(latest_live.get('number',0)):02d} {'命中' if latest_live.get('hit') else '未中'}</div></div></div>
  <p><b>結論：</b>歷史封存的原始快照共 {int(live.get('settled_snapshots',0))} 筆；同一目標日重複快照排除 {int(live.get('duplicate_snapshots_excluded',0))} 筆，僅按 {live_total} 個獨立開獎日計算。現行獨支 {int(live.get('current_number',confidence['number'])):02d} 的獨立實戰樣本只有 {int(live.get('current_number_samples',0))} 期／{int(live.get('current_number_hits',0))} 中，樣本不足，不能把單次命中包裝成已證實高準確。</p>
  <div class="sample-meter"><span style="width:{min(100,live_total/live_minimum*100) if live_minimum else 0:.1f}%"></span></div><p class="note">實戰樣本進度 {live_total}/{live_minimum}。達門檻前保留唯一第1名排序，但一律降級為觀察級；不追號、不回改封存預測。</p>
</div>'''

    research = main_test["external_method_review"]
    research_html = (
        '<div class="band"><h2>外部預測系統方法研究</h2><h3>通過本系統驗證並採用</h3><ul>'
        + "".join(f"<li>{e(item)}</li>" for item in research["採用"])
        + "</ul><h3>拒絕直接採用</h3><ul>"
        + "".join(f"<li>{e(item)}</li>" for item in research["不直接採用"])
        + "</ul></div>"
    )

    html_text = f'''<!doctype html>
<html lang="zh-Hant"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="theme-color" content="#7f1017"><meta name="report-version" content="{version['hash']}"><meta name="report-generated-at" content="{e(generated_at)}"><link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'%3E%3Ccircle cx='32' cy='32' r='30' fill='%23a71c23'/%3E%3Ctext x='32' y='42' text-anchor='middle' font-size='28' fill='white'%3E6%3C/text%3E%3C/svg%3E"><link rel="manifest" href="manifest.webmanifest"><link rel="stylesheet" href="style.css"><title>香港六合彩新世代鐵律戰報</title></head>
<body><main>
<header><h1>香港六合彩・本期戰報</h1><div>{analysis_data['history']['count']:,}期歷史基底・520期走步驗證・資料更新與模型守門雙軌分離</div>
<div class="app-actions"><button type="button" id="manual-refresh" class="cloud-button update-button">清快取並核對最新</button><button type="button" id="emergency-repair" class="cloud-button repair-button">當機立即修復</button><a id="secure-cloud-update" class="cloud-button workflow-button" href="https://github.com/pingshen670822/hong-kong-marksix-ironlaw/actions/workflows/update.yml" target="_blank" rel="noopener noreferrer">啟動雲端主更新</a></div>
<div class="cloud-control-note">「核對最新」會清除手機舊快取、重抓戰報／資料／健康檔並顯示證據；真正重跑雲端主機請用「啟動雲端主更新」，登入 GitHub 後執行。網頁不存放任何密碼或憑證。</div>
<div class="update-times"><span>雲端戰報產生：<strong id="cloud-generated-time">{e(generated_at)}</strong></span><span>最後核對完成：<strong id="last-manual-update">尚未手動核對</strong></span></div>
<div id="cloud-action-status" class="cloud-action-status" role="status" aria-live="polite">目前資料：{e(analysis_data['latest_draw']['date'])}／{e(analysis_data['latest_draw']['period'])}</div></header>
<nav aria-label="戰報分類">{''.join(f'<button type="button" data-tab="{tab}">{label}</button>' for tab, label in [('decision','本期預測'),('models','回測驗證'),('review','開獎檢討'),('monthly','歷史封存'),('verify','模型說明'),('iron','系統健康')])}</nav>

<section id="decision" class="tab active">
{next_prediction_block}
{confidence_block}
{recalculation_block}
{live_accuracy_block}
<div class="band ironlaw-numbers"><h2>本期其他鐵律號碼</h2>{table(['類型','正式號碼'], [[e(name), balls(numbers)] for name, numbers in analysis_data['packs'].items()])}<h3>特別號獨立運算</h3>{table(['類型','正式號碼'], [[e(name), balls(numbers, 'specialball')] for name, numbers in analysis_data['special_packs'].items()])}<p class="note">所有號碼均依同一次正式運算產生；未達超高信心門檻時只標示觀察級，不會阻斷最新開獎資料同步。</p></div>
<details class="report-details"><summary>查看獨支強烈驗證與完整運算</summary>
<div class="band"><h2>多項邏輯驗證</h2>{table(['檢查項目','結果'], check_rows)}</div>
<div class="band"><h2>清楚分層推薦</h2><div class="grid"><div class="card primary"><div class="label">A級・唯一最強排序</div><div class="number-line">{balls(tiers['A_唯一最強'])}</div></div><div class="card"><div class="label">B級・前三排序</div><div class="number-line">{balls(tiers['B_高信心前三'])}</div></div><div class="card"><div class="label">C級・核心前九</div><div class="number-line">{balls(tiers['C_核心前九'])}</div></div><div class="card"><div class="label">D級・次高防守</div><div class="number-line">{balls(tiers['D_次高防守'])}</div></div><div class="card low"><div class="label">E級・低機率暫避</div><div class="number-line">{balls(tiers['E_低機率暫避'], 'avoid')}</div></div></div></div>
</details>
<details class="report-details"><summary>查看資料、排名與完整牌組</summary>
<div class="band"><h2>本期資料</h2><div class="grid"><div class="card"><div class="label">預測目標日</div><div class="value">{e(analysis_data['target_date'])}</div></div><div class="card"><div class="label">歷史資料截止日</div><div class="value">{e(analysis_data['latest_draw']['date'])}</div></div><div class="card"><div class="label">依據期別</div><div class="value">{e(analysis_data['latest_draw']['period'])}</div></div><div class="card"><div class="label">使用歷史期數</div><div class="value">{analysis_data['history']['count']:,}期</div></div><div class="card"><div class="label">戰報產生時間</div><div class="value">{e(generated_at)}</div></div></div></div>
<div class="band"><h2>內部前18名診斷</h2><p class="note">此表為運算順位與校準值，不代表中獎保證。</p>{table(['順位','號碼','校準機率'], candidate_rows)}</div>
<div class="band"><h2>八組結構平衡建議</h2><div class="grid">{''.join(f'<div class="card"><div class="label">第{index + 1}組</div><div class="number-line">{balls(group)}</div></div>' for index, group in enumerate(analysis_data['suggested_sets']))}</div></div>
<div class="band warning"><h2>下期低機率暫避</h2><p class="note">只做風險排序，不代表絕對不開；與攻擊牌完全分離。</p><div class="grid">{''.join(f'<div class="card low"><div class="label">{e(name)}</div><div class="number-line">{balls(numbers, "avoid")}</div></div>' for name, numbers in analysis_data['avoid'].items())}</div></div>
</details>
</section>

<section id="models" class="tab"><div class="band"><h2>520期前9碼時間序列走步回測</h2><div class="grid"><div class="card"><div class="label">前9碼平均命中</div><div class="value">{main_test['avg_hits']}</div><div class="note">隨機基準 {analysis_data['release_gate']['main_random_hits']}</div></div><div class="card"><div class="label">近60期至少1顆進前9</div><div class="value">{main_test['first_hit_rank_audit']['60']['within_9_rate'] * 100:.1f}%</div><div class="note">隨機基準 {main_test['within9_random_baseline'] * 100:.1f}%</div></div><div class="card"><div class="label">近120期前9碼命中</div><div class="value">{main_test['ensemble_recent_hits']['120']}</div><div class="note">超高共識門檻 ≥ {analysis_data['release_gate']['main_random_hits']}</div></div></div></div>
<div class="band"><h2>第10名後問題專項檢測</h2>{table(['窗口','至少1顆進前9比例','首顆平均名次','完全落在9名後期數'], rank_audit_rows)}</div>
<details class="report-details"><summary>查看逐模組錯誤檢討與滾動調整</summary><div class="band"><h2>前9碼三層滾動權重</h2><p>{e(main_test['weighting_strategy'])}</p>{table(['模型','上期前9命中','近30期','近120期','近360期','連續失誤','新權重','調整決策'], model_rows)}</div><div class="band"><h2>冠軍／挑戰者實測</h2><p>本期升級：{e(champion['promoted'])}。{e(champion['rule'])}</p>{table(['版本','520期','近60期','近120期','對數損失'], champion_rows)}</div>{research_html}</details></section>

<section id="review" class="tab">{live_accuracy_block}<div class="band"><h2>預測對實際逐期驗算</h2><p>預測先封存，開獎後只結算，禁止回改舊牌。同一開獎日若曾在不同依據期別產生預測，會分列保存而不覆蓋；但上方準確率每個實際開獎日只計一次，避免重複灌水。</p>{table(['目標日','依據期別','原最強獨支','獨支戰果','原主攻12碼','實際開獎','12碼命中','命中號','特別號'], settled_rows(history))}</div><details class="report-details"><summary>查看低機率號碼誤開檢討</summary><div class="band">{table(['目標日','依據期別','原十不中','誤開號','顆數','修正'], low_rows)}</div></details></section>

<section id="monthly" class="tab"><div class="band"><h2>歷史封存與每月總整理</h2><p>每一筆依開獎前的「依據期別＋目標日」獨立封存；同日多次預測不合併、不回改。</p>{table(['月份','封存結算筆數','總命中','平均命中','單筆最高','特別號命中'], monthly_rows(history))}</div></section>

<section id="verify" class="tab"><div class="band"><h2>模型說明</h2><p>所有模型以「前9碼命中」為訓練與扣權目標，依30／120／360期成績、校準誤差與連續失誤重新配權，再取校準機率唯一第1名。只使用開獎前已存在的歷史資料，嚴禁回填。</p><h3>失敗回饋規則</h3><ul><li>每期檢查所有實際號碼的預測名次</li><li>首顆命中落到第10名後即列入錯誤檢討</li><li>短期30期占60%，120期占25%，360期占15%</li><li>校準誤差及連續零命中會額外扣權</li><li>單一模型權重上限22%</li><li>未達信心門檻時禁止標示超高信心，改列觀察級；最新開獎資料仍必須同步</li></ul></div>{research_html}</section>

<section id="iron" class="tab"><div class="band"><h2>系統健康</h2><div class="grid"><div class="card"><div class="label">資料日期／期別</div><div class="value">{e(analysis_data['latest_draw']['date'])}／{e(analysis_data['latest_draw']['period'])}</div></div><div class="card"><div class="label">預測守門</div><div class="value {gate_class}">{gate_text}</div></div><div class="card"><div class="label">雲端主更新</div><div class="value ok">每小時＋開獎後密集檢查</div></div><div class="card"><div class="label">第二層自主修復</div><div class="value ok">主流程失敗時自動啟動</div></div></div></div>
<div class="band"><h2>最新版六合彩規則</h2><p>1至49選6個正選號碼，每注HK$10；另開1個特別號。</p>{table(['獎級','中獎條件','固定獎金'], [['一獎','6個正選','彩池制'],['二獎','5個正選＋特別號','彩池制'],['三獎','5個正選','彩池制'],['四獎','4個正選＋特別號','HK$9,600'],['五獎','4個正選','HK$640'],['六獎','3個正選＋特別號','HK$320'],['七獎','3個正選','HK$40']])}</div>
<div class="band"><h2>鐵律守門</h2><ol><li>資料須通過期別、日期、6個正選號碼、特別號完整驗證</li><li>預測封存後不可因開獎結果修改</li><li>回測嚴格按時間順序，禁止偷看未來</li><li>主攻、低機率、上期檢討、月結分區顯示</li><li>抓號失敗保留最後有效版本，絕不以假資料覆寫</li><li>主流程失敗自動啟動第二層雲端救援，後續每小時持續重試</li><li>臨時開彩日及金多寶一律以香港賽馬會公告為準</li></ol><h3>生命週期</h3><p>開獎資料 → 雙來源交叉驗證 → 上期結算 → 失敗回饋 → 520期重測 → 健康稽核 → 戰報生成 → 手機同步 → 失敗時第二層救援</p></div></section>

<div class="band warning notice">{e(analysis_data['notice'])}</div><footer>資料基準 {e(analysis_data['latest_draw']['date'])}・目標 {e(analysis_data['target_date'])}・核心 {e(analysis_data['engine'])}</footer>
</main><script src="app.js"></script></body></html>'''

    css = '''*{box-sizing:border-box}[hidden]{display:none!important}body{margin:0;background:#f3f4f6;color:#172033;font-family:system-ui,"Microsoft JhengHei",sans-serif;line-height:1.55}main{max-width:1180px;margin:auto;padding:18px}header{background:linear-gradient(135deg,#7f1017,#d1242f);color:#fff;padding:24px;border-radius:14px}h1{margin:0 0 5px;font-size:28px}h2{border-left:6px solid #c1121f;padding-left:10px;color:#7f1017;margin:0 0 16px}h3{color:#7f1017;margin:24px 0 10px}nav{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:8px;margin:14px 0}nav button{display:flex;align-items:center;justify-content:center;min-height:44px;background:#fff;border:1px solid #d1d5db;border-radius:9px;padding:8px;color:#7f1017;font:800 15px system-ui,"Microsoft JhengHei",sans-serif;text-align:center;cursor:pointer}nav button.on{background:#7f1017;color:#fff;border-color:#7f1017}.tab{display:none}.tab.active{display:block}.app-actions{display:flex;align-items:center;gap:9px;flex-wrap:wrap;margin-top:14px}.cloud-button{display:inline-flex;align-items:center;justify-content:center;min-height:44px;border:2px solid #fff;border-radius:999px;padding:8px 18px;color:#fff;font:900 16px system-ui,"Microsoft JhengHei",sans-serif;box-shadow:0 3px 10px #0004;cursor:pointer;text-decoration:none}.cloud-button:focus-visible{outline:3px solid #fff;outline-offset:3px}.cloud-button:disabled{opacity:.62;cursor:wait}.update-button{background:#087348}.repair-button{background:#651018}.workflow-button{background:#17365d}.workflow-button.attention{animation:pulse 1.1s infinite}@keyframes pulse{50%{box-shadow:0 0 0 5px #ffd16688}}.cloud-control-note{margin-top:12px;font-weight:700}.update-times{display:flex;gap:8px 20px;flex-wrap:wrap;margin-top:10px;padding:10px 12px;border-radius:10px;background:#ffffff20}.cloud-action-status{min-height:24px;margin-top:8px;font-weight:800}.cloud-action-status.ok{color:#d8ffe9}.cloud-action-status.error{color:#fff0a8}.band{background:#fff;border:1px solid #d8dee8;border-radius:12px;padding:18px;margin:14px 0;box-shadow:0 2px 8px #0000000d}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:10px}.card{border:1px solid #d9dde5;border-radius:10px;padding:13px;background:#fff}.next-prediction{border:4px solid #7f1017;background:linear-gradient(135deg,#fff1f2,#fff)}.next-badge{background:#c1121f;font-size:16px}.next-meta{font-size:16px;font-weight:800;margin:-6px 0 14px;color:#4a1520}.next-grid{grid-template-columns:minmax(170px,.7fr) repeat(3,minmax(210px,1fr))}.next-single{border:3px solid #c1121f;background:#fff7f7;text-align:center}.next-single .number{font-size:72px;line-height:1.05}.repeat-audit{margin-top:16px;padding:14px;border-radius:12px;background:#fff}.repeat-audit h3{margin:0 0 12px}.repeat-ok{border:2px solid #087348}.repeat-bad{border:2px solid #c1121f}.primary{border:2px solid #c1121f;background:#fff5f5}.strong{border:3px solid #b8860b;background:linear-gradient(135deg,#fff8d8,#fff);box-shadow:0 4px 18px #b8860b33}.strong.warning{border-color:#e9b949}.strong .number{font-size:64px}.badge{display:inline-block;padding:6px 12px;border-radius:999px;background:#7f1017;color:#fff;font-weight:900;margin-bottom:8px}.proof-badge{background:#087348}.recompute-proof{border:3px solid #087348;background:linear-gradient(135deg,#edfff5,#fff)}.label{color:#687386;font-size:13px}.value{font-size:18px;font-weight:800;margin-top:4px}.number{color:#c1121f;font-size:38px;font-weight:900;letter-spacing:2px}.number-line{font-size:20px;letter-spacing:2px;color:#7f1017}.validation-seals{display:flex;gap:8px;flex-wrap:wrap;margin:12px 0}.validation-seals span{border:1px solid #d3b358;border-radius:999px;padding:5px 10px;background:#fff;font-weight:800}.sample-meter{height:14px;border-radius:999px;background:#e4e8ef;overflow:hidden}.sample-meter span{display:block;height:100%;background:linear-gradient(90deg,#d08a00,#087348)}.live-audit{border:2px solid #d08a00}.table-wrap{overflow-x:auto}table{width:100%;border-collapse:collapse}th{background:#7f1017;color:#fff}th,td{padding:9px;border:1px solid #d7dce4;text-align:left;white-space:nowrap}tr:nth-child(even) td{background:#fafafa}.warning{background:#fff8e6;border-color:#e9b949}.ok{color:#176b3a}.bad{color:#9b1c1c}.note{color:#626d7d}.empty{padding:22px;text-align:center;color:#687386}.low{border-color:#596576}.ball{display:inline-grid;place-items:center;width:39px;height:39px;margin:3px;border-radius:50%;background:#a71c23;color:#fff;font-weight:900;letter-spacing:0}.actual{background:#087348}.avoid{background:#596576}.specialball,.special{background:#d08a00}.special{display:inline-block;padding:8px;color:#fff;border-radius:10px;margin-left:4px}.report-details{margin:14px 0;border:1px solid #d8dee8;border-radius:12px;background:#fff;box-shadow:0 2px 8px #0000000d}.report-details>summary{list-style:none;min-height:54px;padding:14px 18px;display:flex;align-items:center;justify-content:space-between;color:#7f1017;font-weight:900;cursor:pointer}.report-details>summary::-webkit-details-marker{display:none}.report-details>summary::after{content:"點開";padding:5px 10px;border-radius:999px;background:#7f1017;color:#fff;font-size:13px}.report-details[open]>summary::after{content:"收起"}.report-details>.band{margin:0;border-width:1px 0 0;border-radius:0;box-shadow:none}.notice{text-align:center}footer{padding:14px 4px 28px;color:#687386;font-size:13px}@media(max-width:760px){main{padding:8px}header{border-radius:8px;padding:19px}nav{grid-template-columns:repeat(3,minmax(0,1fr))}nav button{font-size:14px}.band{padding:13px}h1{font-size:24px}.number-line{font-size:18px;letter-spacing:1px}.strong .number{font-size:56px}.next-grid{grid-template-columns:1fr}.next-single .number{font-size:64px}.cloud-button{width:100%}.ball{width:35px;height:35px}th,td{font-size:14px}.update-times{display:grid}}@media(max-width:390px){nav{grid-template-columns:repeat(2,minmax(0,1fr))}}'''

    js = '''document.querySelectorAll('nav button').forEach((button,index)=>{if(!index)button.classList.add('on');button.addEventListener('click',()=>{document.querySelectorAll('.tab').forEach(tab=>tab.classList.remove('active'));document.querySelectorAll('nav button').forEach(item=>item.classList.remove('on'));document.getElementById(button.dataset.tab)?.classList.add('active');button.classList.add('on');window.scrollTo({top:0,behavior:'smooth'})})});
const pageHash=document.querySelector('meta[name="report-version"]')?.content||'';
const pageGeneratedAt=document.querySelector('meta[name="report-generated-at"]')?.content||'';
const refreshButton=document.getElementById('manual-refresh');
const repairButton=document.getElementById('emergency-repair');
const secureUpdate=document.getElementById('secure-cloud-update');
const actionStatus=document.getElementById('cloud-action-status');
const lastManualUpdate=document.getElementById('last-manual-update');
const manualUpdateKey='marksix-last-manual-update';
const rescueUrl='https://github.com/pingshen670822/hong-kong-marksix-ironlaw/actions/workflows/cloud-self-repair.yml';
const updateApi='https://api.github.com/repos/pingshen670822/hong-kong-marksix-ironlaw/actions/workflows/update.yml/runs?per_page=1';
function taipeiNow(){return new Intl.DateTimeFormat('zh-TW',{timeZone:'Asia/Taipei',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit',hour12:false}).format(new Date())}
function setStatus(message,state=''){if(!actionStatus)return;actionStatus.textContent=message;actionStatus.className='cloud-action-status'+(state?' '+state:'')}
function setBusy(busy){[refreshButton,repairButton].forEach(button=>{if(button)button.disabled=busy})}
function readManualRecord(){try{return JSON.parse(localStorage.getItem(manualUpdateKey)||'null')}catch(error){return null}}
function renderManualRecord(record=readManualRecord()){if(!lastManualUpdate)return;if(record?.completedAt){lastManualUpdate.textContent=`${record.completedAt}（${record.date||'日期待確認'}／${record.period||'期別待確認'}）`}}
function saveManualRecord(snapshot){const draw=snapshot.analysis?.latest_draw||{};const record={completedAt:taipeiNow(),date:draw.date||'',period:draw.period||'',hash:snapshot.version?.hash||pageHash};try{localStorage.setItem(manualUpdateKey,JSON.stringify(record))}catch(error){}renderManualRecord(record);return record}
async function fetchJson(path){const response=await fetch(`${path}?t=${Date.now()}`,{cache:'no-store'});if(!response.ok)throw new Error(`${path}:${response.status}`);return response.json()}
async function fetchVersion(){return fetchJson('version.json')}
async function cloudSnapshot(){const [version,analysis]=await Promise.all([fetchVersion(),fetchJson('latest_analysis.json')]);let health=null;let selfTest=null;try{health=await fetchJson('health_status.json')}catch(error){}try{selfTest=await fetchJson('self_test_report.json')}catch(error){}return {version,analysis,health,selfTest}}
function renderProof(proof){if(!proof?.completed_at)return;const oldSingle=proof.previous_single==null?'首次':String(proof.previous_single).padStart(2,'0');const newSingle=proof.current_single==null?'待確認':String(proof.current_single).padStart(2,'0');const values={"proof-completed":proof.completed_at,"proof-basis":`${proof.current_draw_date||'—'}／${proof.current_period||'—'}`,"proof-data-change":proof.data_changed?'有新資料':'沒有新開獎',"proof-comparison":`${oldSingle} → ${newSingle}`,"proof-compare-note":proof.single_changed?'號碼已改變':'重算後維持相同',"proof-crosscheck":`${proof.crosschecked_dates||0}個日期`,"proof-status":proof.status||'重算狀態待確認'};Object.entries(values).forEach(([id,value])=>{const element=document.getElementById(id);if(element)element.textContent=value})}
async function hydrateLatestProof(){try{const analysis=await fetchJson('latest_analysis.json');renderProof(analysis.recalculation_proof)}catch(error){}}
async function latestWorkflowRun(){try{const response=await fetch(updateApi,{cache:'no-store',headers:{Accept:'application/vnd.github+json'}});if(!response.ok)return null;const data=await response.json();return data.workflow_runs?.[0]||null}catch(error){return null}}
function taipeiToday(){return new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Taipei',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date())}
function isCloudStale(snapshot){const draw=snapshot.analysis?.latest_draw||{};const target=snapshot.analysis?.target_date||'';return Boolean(target&&target<taipeiToday()&&draw.date<target)}
function reloadWith(key,value){const url=new URL(location.href);url.searchParams.set(key,value);location.replace(url.toString())}
function registerWorker(){if('serviceWorker'in navigator)return navigator.serviceWorker.register('service-worker.js').then(registration=>registration.update()).catch(()=>setStatus('背景快取未啟用；即時雲端資料仍可使用。','error'))}
function cloudVersionIsNewer(version){if(!version?.hash||version.hash===pageHash)return false;const cloudTime=Date.parse(version.updated_at||'');const pageTime=Date.parse(pageGeneratedAt);return Number.isFinite(cloudTime)&&Number.isFinite(pageTime)&&cloudTime>pageTime}
async function checkVersion(){try{const version=await fetchVersion();if(cloudVersionIsNewer(version)){reloadWith('v',version.hash)}return version}catch(error){return null}}
async function manualRefresh(){setBusy(true);setStatus('第1/3步：清除手機舊快取…');try{await resetClient();setStatus('第2/3步：重抓戰報、開獎資料與健康檔…');const [snapshot,run]=await Promise.all([cloudSnapshot(),latestWorkflowRun()]);const record=saveManualRecord(snapshot);const draw=snapshot.analysis.latest_draw||{};const proof=snapshot.analysis.recalculation_proof||{};renderProof(proof);const oldSingle=proof.previous_single==null?'首次':String(proof.previous_single).padStart(2,'0');const newSingle=proof.current_single==null?'待確認':String(proof.current_single).padStart(2,'0');const proofText=proof.completed_at?`；雲端重算 ${proof.completed_at}；獨支 ${oldSingle}→${newSingle}（${proof.single_changed?'已改變':'重算後維持'}）`:'';if(cloudVersionIsNewer(snapshot.version)){setStatus(`核對完成：${record.completedAt}；發現新版，正在載入…`,'ok');setTimeout(()=>reloadWith('v',snapshot.version.hash),300);return}const healthy=snapshot.health?.healthy!==false&&snapshot.selfTest?.operational_passed!==false;const stale=isCloudStale(snapshot);const runText=run?`；雲端主流程 ${run.status==='completed'?(run.conclusion||'完成'):'執行中'}`:'；主流程狀態暫時無法讀取';if(stale){setStatus(`核對完成：${record.completedAt}；已重抓4個雲端檔，但資料仍停在 ${draw.date||'日期待確認'}／${draw.period||'期別待確認'}。請按「啟動雲端主更新」。${proofText}${runText}`,'error');secureUpdate?.classList.add('attention')}else if(!healthy){setStatus(`核對完成：${record.completedAt}；最新 ${draw.date||'日期待確認'}／${draw.period||'期別待確認'}，健康檢測需修復。請按「當機立即修復」。${proofText}${runText}`,'error')}else{setStatus(`核對完成：${record.completedAt}；已清快取並重抓4個雲端檔；最新 ${draw.date||'日期待確認'}／${draw.period||'期別待確認'}；系統健康${proofText}${runText}`,'ok')}}catch(error){setStatus(`核對失敗：${taipeiNow()}；暫時無法連接雲端，請按「當機立即修復」。`,'error')}finally{setBusy(false);registerWorker()}}
async function resetClient(){if('caches'in window){const keys=await caches.keys();await Promise.allSettled(keys.map(key=>caches.delete(key)))}if('serviceWorker'in navigator){const registrations=await navigator.serviceWorker.getRegistrations();await Promise.allSettled(registrations.map(registration=>registration.unregister()))}}
async function emergencyRepair(){setBusy(true);setStatus('正在清除失效快取並重新連接雲端…');try{await resetClient();const snapshot=await cloudSnapshot();const record=saveManualRecord(snapshot);sessionStorage.setItem('marksix-repair-result',`當機修復完成：${record.completedAt}；已重新連接 ${snapshot.analysis?.latest_draw?.period||'最新戰報'}。`);reloadWith('repair',String(Date.now()))}catch(error){sessionStorage.setItem('marksix-repair-result','本機快取已清除；雲端來源仍無法連線，已開啟第二層救援頁。');const rescue=window.open(rescueUrl,'_blank','noopener,noreferrer');if(!rescue)location.href=rescueUrl;else reloadWith('repair',String(Date.now()))}finally{setBusy(false)}}
refreshButton?.addEventListener('click',manualRefresh);
repairButton?.addEventListener('click',emergencyRepair);
renderManualRecord();
const repairResult=sessionStorage.getItem('marksix-repair-result');if(repairResult){sessionStorage.removeItem('marksix-repair-result');setStatus(repairResult,'ok')}
hydrateLatestProof();checkVersion();setInterval(checkVersion,60000);addEventListener('pageshow',()=>{hydrateLatestProof();checkVersion()});addEventListener('visibilitychange',()=>{if(!document.hidden){hydrateLatestProof();checkVersion()}});registerWorker();'''

    service_worker = f'''const C='hk-marksix-{version["hash"]}';
const ASSETS=['./','index.html','style.css','app.js'];
self.addEventListener('install',event=>{{self.skipWaiting();event.waitUntil(caches.open(C).then(cache=>Promise.allSettled(ASSETS.map(asset=>cache.add(asset)))));}});
self.addEventListener('activate',event=>{{event.waitUntil(Promise.all([caches.keys().then(keys=>Promise.allSettled(keys.filter(key=>key!==C).map(key=>caches.delete(key)))),self.clients.claim()]));}});
self.addEventListener('fetch',event=>{{if(event.request.method!=='GET')return;event.respondWith(fetch(event.request,{{cache:'no-store'}}).then(response=>{{if(response.ok&&new URL(event.request.url).origin===self.location.origin){{const copy=response.clone();caches.open(C).then(cache=>cache.put(event.request,copy)).catch(()=>{{}});}}return response;}}).catch(()=>caches.match(event.request).then(cached=>cached||(event.request.mode==='navigate'?caches.match('index.html'):Response.error()))));}});'''

    manifest = json.dumps({
        "name": "香港六合彩新世代鐵律戰報",
        "short_name": "六合彩戰報",
        "start_url": "./",
        "display": "standalone",
        "theme_color": "#7f1017",
        "background_color": "#f3f4f6",
    }, ensure_ascii=False)

    for directory in (REPORTS, SITE, DOCS):
        atomic_write(directory / "index.html", html_text)
        atomic_write(directory / "latest_battle_report.html", html_text)
        atomic_write(directory / "latest_analysis.json", analysis_json)
        atomic_write(directory / "prediction_history.json", json.dumps(history, ensure_ascii=False, indent=2))
        atomic_write(directory / "version.json", json.dumps(version, ensure_ascii=False, indent=2))
        atomic_write(directory / "style.css", css)
        atomic_write(directory / "app.js", js)
        atomic_write(directory / "manifest.webmanifest", manifest)
        atomic_write(directory / "service-worker.js", service_worker)
