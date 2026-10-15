"""Render an escaped, self-contained, read-only V10 research report.

The renderer never promotes a research pick to a formal recommendation.  Its
browser code checks the age of the *source retrieval*, not the page load time,
and does not fetch data, register a service worker, or trigger a pipeline.
"""
from __future__ import annotations

import html
import json
import math
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta, timezone
from numbers import Integral, Real


HKT = timezone(timedelta(hours=8))
MAX_SOURCE_AGE_SECONDS = 24 * 60 * 60


def _mapping(value: object) -> Mapping:
    return value if isinstance(value, Mapping) else {}


def _plain(value: object, missing: str = "未提供") -> str:
    if value is None or value == "":
        return missing
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    if isinstance(value, bool):
        return "是" if value else "否"
    return str(value)


def _safe(value: object, missing: str = "未提供") -> str:
    return html.escape(_plain(value, missing), quote=True)


def _json_script(value: object) -> str:
    # HTML parsers recognize </script> even inside a JSON string.  Escape HTML
    # delimiters as JSON escapes rather than interpolating raw serialized data.
    return (json.dumps(value, ensure_ascii=True, allow_nan=False)
            .replace("<", "\\u003c").replace(">", "\\u003e")
            .replace("&", "\\u0026"))


def _number(value: object) -> str:
    if isinstance(value, Integral) and not isinstance(value, bool) and 1 <= value <= 49:
        return f"{int(value):02d}"
    return "—"


def _numbers(value: object) -> list:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return [n for n in value if _number(n) != "—"]


def _balls(value: object, *, research: bool = False) -> str:
    values = _numbers(value)
    if not values:
        return '<p class="muted">未提供有效號碼</p>'
    kind = " research-ball" if research else ""
    return '<ol class="balls" aria-label="' + ("研究排序" if research else "正碼") + '">' + "".join(
        f'<li class="ball{kind}" aria-label="第 {i} {"順位" if research else "個正碼"}：{_number(n)}">{_number(n)}</li>'
        for i, n in enumerate(values, 1)
    ) + "</ol>"


def _timestamp(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.astimezone(timezone.utc) if parsed.tzinfo is not None else None
    except (ValueError, OverflowError):
        return None


def _ratio(hits: object, rounds: object) -> str:
    if (isinstance(hits, Integral) and not isinstance(hits, bool)
            and isinstance(rounds, Integral) and not isinstance(rounds, bool)
            and 0 <= hits <= rounds):
        return f"{hits} / {rounds}" + (f"（{hits / rounds:.2%}）" if rounds else "（尚無可結算樣本）")
    return f"{_safe(hits)} / {_safe(rounds)}"


def _count(value: object) -> str:
    if isinstance(value, (list, tuple)):
        return str(len(value))
    return _safe(value)


def _p_value(value: object) -> str:
    if isinstance(value, Real) and not isinstance(value, bool) and math.isfinite(value) and 0 <= value <= 1:
        return f"{value:.6g}"
    return "未提供有效值"


def _field(label: str, value: object, *, code: bool = False) -> str:
    content = _safe(value)
    if code:
        content = f'<code>{content}</code>'
    return f'<div><dt>{label}</dt><dd>{content}</dd></div>'


def _explain(value: object) -> object:
    translations = {
        "Research-only policy: no preregistered prospective validation establishes a predictive edge": "僅供研究：尚無事先登記的合格前瞻驗證，足以建立預測優勢。",
        "Not established; rolling historical holdout is exploratory, not independent prospective proof": "資格尚未建立；滾動歷史保留樣本屬探索性評估，並非獨立前瞻證據。",
        "Conservative: forecasts made on or after the target Hong Kong date are not scored": "採保守規則：香港日期為目標開獎當日或之後建立的封存，不計入合格前瞻成績。",
        "Repeated research number is not extra confidence; formal selection remains blank": "重複研究號碼不會增加可信度；正式獨支維持空白。",
        "Imported V9 ledger retained unchanged; not V10 prospective performance. Local hash chains are tamper-evident, not independent timestamps.": "匯入的 V9 記錄原樣保留，不算作 V10 前瞻成績。本地雜湊鏈只能協助辨識篡改，不是獨立時間證明。",
        "Relative ranking only, not a winning probability. bayes_60 is exactly the last-60 frequency ordering with numeric tie-breaks.": "僅為相對排序，不是中獎機率；bayes_60 等同最近 60 期頻率排序，同分時依號碼排序。",
        "unverified": "尚未核實",
        "official_announced": "官方已公布",
    }
    return translations.get(value, value) if isinstance(value, str) else value


def render(analysis: dict) -> str:
    """Return the complete Chinese HTML report, without file or network I/O.

    Formal output is deliberately blank even if a caller supplies a non-null
    formal.single.  V10 research scores are not calibrated win probabilities.
    """
    a = _mapping(analysis)
    data = _mapping(a.get("data"))
    current = _mapping(a.get("currentness"))
    latest = _mapping(a.get("latest_draw"))
    target = _mapping(a.get("target"))
    formal = _mapping(a.get("formal"))
    research = _mapping(a.get("research"))
    repeat = _mapping(research.get("repeat_guard"))
    evidence = _mapping(a.get("evidence"))
    seal = _mapping(a.get("seal"))
    legacy = _mapping(a.get("legacy"))

    generated = _timestamp(a.get("generated_at"))
    retrieved = _timestamp(data.get("retrieved_at_utc"))
    initial_age = (generated - retrieved).total_seconds() if generated and retrieved else None
    target_date = target.get("date")
    try:
        target_day = datetime.strptime(str(target_date), "%Y-%m-%d").date()
        if target_day.isoformat() != target_date:
            target_day = None
    except ValueError:
        target_day = None
    initial_cutoff = bool(generated and target_day and generated.astimezone(HKT).date() >= target_day)
    initial_stale = (initial_age is None or initial_age < 0
                     or initial_age >= MAX_SOURCE_AGE_SECONDS or current.get("status") == "expired")
    is_snapshot = current.get("status") == "snapshot"
    if initial_stale:
        initial_banner = "來源新鮮度未通過：來源時間缺失、無效或已達 24 小時。此頁僅保留研究與稽核記錄，正式獨支不顯示。"
    elif initial_cutoff:
        initial_banner = "已進入或超過目標開獎日（香港時間）。此頁僅保留研究與稽核記錄，正式獨支不顯示。"
    elif is_snapshot:
        initial_banner = "此資料狀態為 snapshot：只代表已保存的快照，沒有核實此刻的官方最新資料。正式獨支不顯示。"
    else:
        initial_banner = "本頁為唯讀快照，來源新鮮度將由瀏覽器重新檢查。未達正式資格，正式獨支不顯示。"

    model_note = ("bayes_60 是最近 60 期正碼頻率的共同先驗平滑排序；共同平滑不改變頻率名次，並非新的預測訊號。"
                  if research.get("model") in ("bayes_60", "bayes60") else
                  "模型僅產生歷史資料的相對排序；模型名稱或分數不代表下一期中獎機率。")
    repeat_note = ("第一順位與先前記錄重複。重複不是新訊號，也不是命中保證。"
                   if repeat.get("repeated") is True else
                   "第一順位是否重複，不能作為預測優勢的證據。")
    seal_note = ("注意：本次重新計算的排序與原封存不同。上方顯示本次重算，以下保留原封存內容；不以重算結果覆寫原封存或追改成績。"
                 if research.get("differs_from_seal") is True else
                 "本次重新計算與原封存的排序一致。" if research.get("differs_from_seal") is False else
                 "未提供本次重新計算與原封存的差異判定。")
    rank_html = "".join(f'<li><span class="rank-position">{i}</span><span>{_number(n)}</span></li>'
                        for i, n in enumerate(_numbers(research.get("rank")), 1))
    rank_html = rank_html or '<li class="muted">未提供完整排序</li>'
    model_results = _mapping(research.get("model_results"))
    families = {"baseline": "原有基準", "frequency_window": "區間頻率",
                "exponential_recency": "指數近期權重", "cross_draw_transition": "跨期條件",
                "same_draw_cooccurrence": "同期开奖共現", "fixed_weight_blend": "固定權重混合"}
    model_rows = []
    for item in research.get("catalog", []):
        if not isinstance(item, Mapping) or item.get("name") not in model_results:
            continue
        result = _mapping(model_results[item["name"]])
        selected_mark = "（本期選中）" if item["name"] == research.get("model") else ""
        model_rows.append(
            f'<tr><th scope="row">{_safe(item["name"])}{selected_mark}</th>'
            f'<td>{_safe(families.get(item.get("family"), item.get("family")))}</td>'
            f'<td>{_safe(item.get("parameter"), "—")}</td>'
            f'<td>{_number(result.get("current_first"))}</td>'
            f'<td>{_ratio(result.get("development_hits"), result.get("development_rounds"))}</td>'
            f'<td>{_ratio(result.get("evaluation_hits"), result.get("evaluation_rounds"))}</td>'
            f'<td><code>{_safe(result.get("rank_sha256"))}</code></td></tr>')
    model_audit = (f'''<section class="card wide" id="models" aria-labelledby="models-title">
<h2 id="models-title">50 條研究規則：運算與驗證</h2>
<p>本次實際計算 <strong>{len(model_rows)} / 50</strong> 條固定規則：5 條原有基準，加上五類各 9 條參數變體。每一期只用當期之前的官方開獎資料；前 400 期挑選規則，後 120 期保留評估。結果可核對，但高度相關的變體不是 50 份獨立證據。</p>
<p class="fine">區間頻率計算指定期數的正碼出現率；指數近期權重讓較近資料有較高權重；跨期條件比較指定間隔前的號碼重疊；同期开奖共現比較上一期號碼與歷史同期开奖的重疊；固定權重混合只合併既有分數。這些都是可重算的描述性規則，並非已發現的開獎規律。</p>
<p class="notice">選中規則的單尾檢驗以 50 倍 Bonferroni 校正；歷史回放仍不是事先登記的前瞻證據，不代表下期中獎機率或保證。</p>
<p class="fine">選擇與驗證規則：{_safe(research.get("selection_rule"))}</p>
<details><summary>展開全部 50 條規則的逐項結果</summary><div class="table-scroll"><table><thead><tr><th scope="col">規則</th><th scope="col">類別</th><th scope="col">參數</th><th scope="col">當前第一順位</th><th scope="col">開發期</th><th scope="col">評估期</th><th scope="col">當前排序 SHA-256</th></tr></thead><tbody>{''.join(model_rows)}</tbody></table></div></details>
</section>''' if len(model_rows) == 50 else '')
    model_nav = '<a href="#models">50 條規則</a>' if model_audit else ''
    payload = {
        "generatedAt": _plain(a.get("generated_at"), ""),
        "retrievedAt": _plain(data.get("retrieved_at_utc"), ""),
        "sourceStatus": _plain(current.get("status"), "unknown"),
        "targetDate": target_date if isinstance(target_date, str) else None,
        "maxAgeSeconds": MAX_SOURCE_AGE_SECONDS,
    }
    data_fields = "".join((
        _field("資料期數", data.get("count")),
        _field("資料首期／日期", data.get("first")),
        _field("資料末期／日期", data.get("latest")),
        _field("資料最新期別", data.get("latest_period")),
        _field("來源擷取時間（UTC）", data.get("retrieved_at_utc")),
        _field("資料涵蓋與核驗範圍", data.get("coverage")),
    ))
    audit_fields = "".join((
        _field("報告版本", a.get("version")),
        _field("資料結構", a.get("schema")),
        _field("發行識別碼", a.get("release_id"), code=True),
        _field("報告產生時間", a.get("generated_at")),
        _field("資料 SHA-256", data.get("sha256"), code=True),
        _field("程式 SHA-256", a.get("code_sha256"), code=True),
        _field("來源狀態（產生時記錄）", current.get("status")),
        _field("來源年齡秒數（產生時記錄）", current.get("age_seconds")),
        _field("來源狀態說明", current.get("reason")),
        _field("正式資格狀態（原始記錄）", formal.get("status")),
    ))
    seal_fields = "".join((
        _field("封存雜湊", seal.get("hash"), code=True),
        _field("封存建立時間（UTC）", seal.get("created_at_utc")),
        _field("依據期別", seal.get("based_on_period")),
        _field("封存資料 SHA-256", seal.get("data_sha256"), code=True),
        _field("封存程式 SHA-256", seal.get("code_sha256"), code=True),
        _field("封存模型", seal.get("model")),
        _field("封存研究第一順位", _number(seal.get("single"))),
        _field("封存研究前九順位", seal.get("top9")),
        _field("封存完整排序", seal.get("ranking")),
        _field("封存目標", seal.get("target")),
    ))

    return fr'''<!doctype html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="marksix-report-version" content="{_safe(a.get("release_id"))}">
<meta name="marksix-report-period" content="{_safe(latest.get("period"))}">
<meta name="theme-color" content="#153c4a">
<meta name="description" content="六合彩 V10 唯讀研究報告：正式獨支留白，研究排序、資料時效與封存證據分開呈現。">
<title>六合彩 V10｜研究與核驗報告</title>
<style>
:root{{color-scheme:light;--ink:#16323d;--muted:#526873;--line:#d9e3e6;--paper:#fff;--bg:#f0f5f6;--teal:#155668;--warn:#674313;--warn-bg:#fff5de;font-family:system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI","Noto Sans TC",sans-serif}}
*{{box-sizing:border-box}}html{{scroll-behavior:smooth;scroll-padding-top:20px}}body{{margin:0;background:var(--bg);color:var(--ink);line-height:1.65}}main{{width:min(1080px,100%);margin:auto;padding:24px 20px 40px}}a{{color:#14596c;text-underline-offset:3px}}a:hover{{text-decoration-thickness:2px}}button{{font:inherit;cursor:pointer}}:focus-visible{{outline:3px solid #bb7900;outline-offset:4px}}.skip{{position:absolute;left:12px;top:-100px;background:white;padding:10px;z-index:3}}.skip:focus{{top:10px}}
header{{padding:27px 28px;border-radius:20px;background:#153c4a;color:white}}header p{{max-width:70ch;margin:9px 0 0;color:#d7e8ed}}h1{{font-size:clamp(1.5rem,4vw,2.1rem);line-height:1.3;margin:10px 0}}h2{{font-size:1.18rem;line-height:1.4;margin:0 0 14px}}h3{{font-size:1rem;margin:0 0 8px}}p{{margin:10px 0}}.eyebrow{{font-size:.78rem;font-weight:750;letter-spacing:.1em;text-transform:uppercase}}.pills{{display:flex;gap:8px;flex-wrap:wrap}}.pill{{font-size:.8rem;padding:3px 10px;border:1px solid #60818d;border-radius:100px;background:#214b59}}.toolbar{{display:flex;align-items:center;gap:15px;flex-wrap:wrap;margin-top:18px}}.reload{{padding:10px 15px;border:1px solid #fff;border-radius:9px;background:#fff;color:#153c4a;font-weight:700;min-height:44px}}.reload:hover{{background:#e8f2f5}}header .fine{{font-size:.82rem;color:#e0ebef}}nav{{display:flex;gap:12px 18px;flex-wrap:wrap;margin:17px 3px;font-size:.9rem}}
.banner{{border:1px solid #dec68d;border-left:5px solid #b17d20;border-radius:12px;background:var(--warn-bg);color:var(--warn);padding:15px 18px;margin:18px 0}}.banner p{{margin:0}}.banner .fine{{margin-top:5px;color:#6b552a}}.layout{{display:grid;grid-template-columns:1fr 1fr;gap:18px}}.card{{background:var(--paper);border:1px solid var(--line);border-radius:16px;padding:23px;min-width:0}}.wide{{grid-column:1/-1}}.formal{{border-top:4px solid #758791}}.research{{border-top:4px solid #3c788a}}.kicker{{font-size:.85rem;color:var(--muted);margin-bottom:3px}}.blank{{font-size:3rem;line-height:1.25;font-weight:750;color:#647780;margin:6px 0}}.research-first{{display:flex;gap:17px;align-items:center;margin-bottom:15px}}.first-number{{font-variant-numeric:tabular-nums;font-size:2.45rem;font-weight:800;line-height:1.2;color:#24596a}}.muted{{color:var(--muted)}}.fine{{font-size:.83rem}}.notice{{padding:11px 13px;background:#f2f6f7;border-radius:9px;font-size:.89rem}}.balls{{display:flex;flex-wrap:wrap;gap:8px;list-style:none;margin:12px 0;padding:0}}.ball{{display:grid;place-items:center;flex:0 0 39px;width:39px;height:39px;border:1px solid #b7ccd2;border-radius:50%;font-weight:750;font-variant-numeric:tabular-nums;background:#f0f6f7;color:#193f4d}}.research-ball{{background:#eaf2f5;color:#21596a;border-color:#b6d1da}}.special{{display:flex;gap:10px;align-items:center;margin-top:12px}}.special .ball{{background:#fff5e2;border-color:#d9bf89;color:#704b11}}.draw-heading{{display:flex;justify-content:space-between;gap:10px;flex-wrap:wrap;margin-bottom:4px}}.draw-period{{font-size:1.14rem;font-weight:750}}.baseline-grid,.metrics{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}}.baseline-grid{{grid-template-columns:repeat(2,minmax(0,1fr));margin:15px 0}}.metric{{background:#f3f7f8;border-radius:10px;padding:14px;min-width:0}}.metric strong{{display:block;font-size:1.09rem;margin:5px 0;font-variant-numeric:tabular-nums}}.metric p{{margin:0;font-size:.82rem;color:var(--muted)}}.metric .label{{font-size:.85rem;color:#425d68}}dl{{margin:0}}.facts>div{{display:grid;grid-template-columns:minmax(130px,30%) minmax(0,1fr);gap:12px;padding:10px 0;border-bottom:1px solid #e6edef}}.facts>div:last-child{{border:0}}dt{{color:var(--muted);font-size:.87rem}}dd{{margin:0;overflow-wrap:anywhere;min-width:0}}code{{font-family:ui-monospace,SFMono-Regular,Consolas,monospace;font-size:.82rem;overflow-wrap:anywhere;word-break:break-all}}details{{margin-top:14px}}summary{{font-weight:650;cursor:pointer;padding:8px 0;min-height:44px}}.ranking-list{{display:grid;grid-template-columns:repeat(auto-fit,minmax(65px,1fr));gap:7px;list-style:none;padding:0;margin:10px 0}}.ranking-list li{{border:1px solid var(--line);border-radius:8px;padding:6px 9px;display:flex;justify-content:space-between;gap:6px;font-weight:650;font-variant-numeric:tabular-nums}}.ranking-list .rank-position{{font-weight:400;font-size:.75rem;color:var(--muted)}}footer{{font-size:.81rem;color:var(--muted);padding:22px 3px 0}}[hidden]{{display:none!important}}
.table-scroll{{overflow-x:auto}}table{{border-collapse:collapse;width:100%;min-width:860px;font-size:.78rem}}th,td{{padding:8px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}}tbody th{{font-weight:650}}td code{{font-size:.72rem;word-break:normal;white-space:nowrap}}
@media(max-width:720px){{main{{padding:14px 12px 28px}}header{{padding:22px 20px;border-radius:15px}}.layout{{grid-template-columns:minmax(0,1fr);gap:14px}}.card{{padding:19px}}.metrics{{grid-template-columns:1fr}}.facts>div{{grid-template-columns:1fr;gap:3px}}nav{{gap:9px 15px}}.baseline-grid{{gap:9px}}.metric{{padding:12px}}.ball{{flex-basis:36px;width:36px;height:36px}}}}
@media(max-width:360px){{.baseline-grid{{grid-template-columns:1fr}}.card{{padding:16px}}h1{{font-size:1.45rem}}}}
@media(prefers-reduced-motion:reduce){{html{{scroll-behavior:auto}}}}
@media print{{body{{background:white}}main{{max-width:none;padding:0}}header{{background:white;color:var(--ink);border:1px solid var(--line)}}header p,header .fine{{color:var(--muted)}}.pill{{background:white;color:var(--ink);border-color:var(--line)}}nav,.toolbar{{display:none}}.card{{break-inside:avoid}}.layout{{display:block}}.card,.banner{{margin:12px 0}}details{{display:block}}}}
</style>
</head>
<body>
<a class="skip" href="#main-content">跳至報告內容</a>
<main>
<header>
<div class="eyebrow">Mark Six · V10 · Research record</div>
<h1>六合彩研究與核驗報告</h1>
<div class="pills"><span class="pill">唯讀靜態快照</span><span class="pill">未證實預測優勢</span></div>
<p>正式獨支留白。研究順位、回放結果與開獎前封存記錄分開檢視；歷史頻率不能保證未來命中。</p>
<div class="toolbar"><button class="reload" type="button" id="reload-page">重新載入本頁</button><span class="fine">報告產生：{_safe(a.get("generated_at"))}</span></div>
<p class="fine" id="refresh-help">按鈕只重新載入這份頁面，不會抓取官方資料或啟動雲端重算；可能仍載入同一份快照。</p>
</header>
<nav aria-label="報告章節"><a href="#formal">正式資格</a><a href="#research">研究排序</a><a href="#evidence">驗證證據</a>{model_nav}<a href="#audit">版本與稽核</a></nav>
<aside class="banner" id="freshness-banner" role="status" aria-live="polite" aria-atomic="true">
<p id="freshness-message">{initial_banner}</p>
<p class="fine" id="source-age">來源擷取：{_safe(data.get("retrieved_at_utc"))}。時效上限：24 小時。</p>
</aside>
<noscript><div class="banner">JavaScript 未啟用，頁面無法持續重算來源時效。請自行核對來源擷取時間；正式獨支仍維持空白。</div></noscript>
<div class="layout" id="main-content">
<section class="card formal" id="formal" aria-labelledby="formal-title">
<h2 id="formal-title">正式獨支：暫不提供</h2>
<p class="kicker">未達正式資格</p>
<div class="blank" aria-label="正式獨支空白">—</div>
<span id="formal-selection" data-formal-selection hidden></span>
<p>{_safe(_explain(formal.get("reason")), "尚無足夠的合格前瞻證據，不能提供正式獨支。")}</p>
<p class="notice">資料未核實、來源達 24 小時，或香港日期已進入目標開獎日，均不得顯示正式選號。此版本不將研究順位升格為正式獨支。</p>
</section>
<section class="card research" id="research" aria-labelledby="research-title">
<h2 id="research-title">研究排序</h2>
<div class="research-first"><div class="first-number">{_number(research.get("single"))}</div><div><strong>研究第一順位</strong><div class="muted fine">相對排序，非中獎機率</div></div></div>
<p>模型：<strong>{_safe(research.get("model"))}</strong></p>
<p class="fine">{model_note}</p>
<h3>研究前九順位</h3>
{_balls(research.get("top9"), research=True)}
<p class="fine muted">由左至右依序排列。九個研究號碼的集合結果不能當作單一號碼命中率。</p>
<p class="notice" id="research-validity">這份排序只描述本快照的計算結果，不代表已取得當下最新一期，也不構成投注建議。</p>
</section>
<section class="card" aria-labelledby="latest-title">
<h2 id="latest-title">資料中最後一期開獎</h2>
<div class="draw-heading"><span class="draw-period">{_safe(latest.get("period"))}</span><span>{_safe(latest.get("date"))}</span></div>
<p class="kicker">六個正碼</p>
{_balls(latest.get("main"))}
<div class="special"><span class="kicker">特別號</span><span class="ball">{_number(latest.get("special"))}</span></div>
<p class="fine muted">以上是資料快照中的最後一期；重新載入頁面不等於重新核實官方最新結果。</p>
</section>
<section class="card" aria-labelledby="target-title">
<h2 id="target-title">目標期別與保守截止</h2>
<dl class="facts">
{_field("目標期別", target.get("period"))}
{_field("目標日期（香港時間）", target.get("date") or "尚未核實，不推算日期")}
{_field("目標狀態", _explain(target.get("status")))}
{_field("目標來源", target.get("source"))}
{_field("截止政策", _explain(target.get("cutoff_policy")))}
</dl>
<p class="fine muted">未取得可靠目標日期時，不宣稱適用日期。保守日界為香港時間 00:00；目標當日或之後不顯示正式選號。</p>
</section>
<section class="card wide" id="evidence" aria-labelledby="evidence-title">
<h2 id="evidence-title">證據分層：回放與前瞻分開</h2>
<div class="metrics">
<div class="metric"><span class="label">開發期回放：命中 / 期數</span><strong>{_ratio(evidence.get("development_hits"), evidence.get("development_rounds"))}</strong><p>用於開發或選擇模型，不能充當前瞻成績。</p></div>
<div class="metric"><span class="label">評估期回放：命中 / 期數</span><strong>{_ratio(evidence.get("evaluation_hits"), evidence.get("evaluation_rounds"))}</strong><p>歷史評估仍不是未來優勢的保證。</p></div>
<div class="metric"><span class="label">合格前瞻：命中 / 期數</span><strong>{_ratio(evidence.get("prospective_hits"), evidence.get("prospective_rounds"))}</strong><p>僅按本版資格規則認列；不混入舊版紀錄。</p></div>
</div>
<p>歷史評估區間：{_safe(research.get("evaluation_window"))}</p>
<p>資格判定：{_safe(_explain(evidence.get("qualification")))}</p>
<p>多重比較調整後 p 值：<strong>{_p_value(research.get("adjusted_p"))}</strong>。p 值不是下期中獎機率，也不是模型正確的機率。</p>
<div class="baseline-grid">
<div class="metric"><span class="label">固定一號進入六個正碼的公平基準</span><strong>6/49 ≈ 12.24%</strong><p>獨支正碼命中與這個基準比較。</p></div>
<div class="metric"><span class="label">固定一號成為特別號的公平基準</span><strong>1/49 ≈ 2.04%</strong><p>特別號不能混算為正碼命中。</p></div>
</div>
<p class="fine muted">上述基準以公平的 49 球攪珠為前提。模型分數類型：{_safe(_explain(research.get("score_kind")))}。本頁不宣稱任何號碼具有已證實的預測優勢。</p>
</section>
{model_audit}
<section class="card" aria-labelledby="repeat-title">
<h2 id="repeat-title">重複順位檢查</h2>
<p>{repeat_note}</p>
<dl class="facts">{_field("本次是否重複", repeat.get("repeated"))}{_field("連續記錄次數", repeat.get("consecutive"))}{_field("檢查說明", _explain(repeat.get("warning")))}</dl>
<details><summary>查看完整研究排序</summary><ol class="ranking-list" aria-label="完整研究順位">{rank_html}</ol></details>
</section>
<section class="card" aria-labelledby="data-title">
<h2 id="data-title">資料範圍與來源時間</h2>
<dl class="facts">{data_fields}</dl>
<p class="fine muted">擷取時間是來源時效的起點；報告重新產生、網頁重新載入或雜湊改變，不會讓舊資料變新。</p>
</section>
<section class="card wide" aria-labelledby="seal-title">
<h2 id="seal-title">研究封存記錄</h2>
<p class="notice">{seal_note}</p>
<p class="muted">雜湊可供一致性核對；單靠雜湊不能證明獨立公證、開獎前公開，也不能證明預測優勢。</p>
<details><summary>查看本次封存內容</summary><dl class="facts">{seal_fields}</dl></details>
</section>
<section class="card wide" aria-labelledby="legacy-title">
<h2 id="legacy-title">舊版記錄：獨立保留</h2>
<div class="metrics"><div class="metric"><span class="label">舊版事件</span><strong>{_count(legacy.get("events"))}</strong></div><div class="metric"><span class="label">舊版結算</span><strong>{_count(legacy.get("settlements"))}</strong></div><div class="metric"><span class="label">舊版命中</span><strong>{_count(legacy.get("hits"))}</strong></div></div>
<p>{_safe(_explain(legacy.get("caveat")), "舊版記錄不等同本版的合格前瞻證據，不混入本版成績。")}</p>
<p class="fine muted">以上舊版事件、結算與命中數不計入 V10 合格前瞻成績。</p>
<p class="fine">舊版資料 SHA-256：<code>{_safe(legacy.get("sha256"))}</code></p>
</section>
<section class="card wide" id="audit" aria-labelledby="audit-title">
<h2 id="audit-title">版本、時間與可核對識別碼</h2>
<dl class="facts">{audit_fields}</dl>
<p class="fine muted">本頁不會背景抓取、啟動更新工作或安裝離線快取。時效提示依裝置時鐘重算；裝置時間錯誤也可能影響提示。</p>
</section>
</div>
<footer>六合彩屬隨機攪珠。研究排序不保證中獎，不應視為投注依據。量力而為，未滿 18 歲不得投注。</footer>
</main>
<script type="application/json" id="report-state">{_json_script(payload)}</script>
<script>
(() => {{
  'use strict';
  const state = JSON.parse(document.getElementById('report-state').textContent);
  const message = document.getElementById('freshness-message');
  const ageLabel = document.getElementById('source-age');
  const researchLabel = document.getElementById('research-validity');
  function timestamp(value) {{
    if (typeof value !== 'string' || !/^\d{{4}}-\d{{2}}-\d{{2}}T\d{{2}}:\d{{2}}:\d{{2}}(?:\.\d+)?(?:Z|[+-]\d{{2}}:\d{{2}})$/.test(value)) return NaN;
    if (dateOnly(value.slice(0, 10)) === null || Number(value.slice(11, 13)) > 23 || Number(value.slice(14, 16)) > 59 || Number(value.slice(17, 19)) > 59) return NaN;
    return Date.parse(value);
  }}
  function dateOnly(value) {{
    if (typeof value !== 'string' || !/^\d{{4}}-\d{{2}}-\d{{2}}$/.test(value)) return null;
    const date = new Date(value + 'T00:00:00Z');
    return Number.isFinite(date.getTime()) && date.toISOString().slice(0, 10) === value ? value : null;
  }}
  function recompute() {{
    const now = Date.now();
    const retrieved = timestamp(state.retrievedAt);
    const generated = timestamp(state.generatedAt);
    const ageSeconds = (now - retrieved) / 1000;
    const hkDay = new Date(now + 8 * 60 * 60 * 1000).toISOString().slice(0, 10);
    const targetDay = dateOnly(state.targetDate);
    const cutoff = targetDay !== null && hkDay >= targetDay;
    const invalidTime = !Number.isFinite(retrieved) || !Number.isFinite(generated) || retrieved > generated || now < generated || ageSeconds < 0;
    const stale = invalidTime || ageSeconds >= state.maxAgeSeconds || state.sourceStatus === 'expired';
    const snapshot = state.sourceStatus === 'snapshot';
    const verifiedStatus = state.sourceStatus === 'fresh_verified';
    // Fail closed.  This V10 report never emits a formal pick, including for a
    // malformed input that incorrectly contains formal.single.
    document.querySelectorAll('[data-formal-selection]').forEach((node) => {{
      node.hidden = true;
      node.textContent = '';
    }});
    const reasons = [];
    if (invalidTime) reasons.push('來源或產生時間無法可靠核對，請檢查裝置時間及資料時間戳。');
    else if (ageSeconds >= state.maxAgeSeconds) reasons.push('來源擷取已達 24 小時時效上限，資料已過期。');
    else if (state.sourceStatus === 'expired') reasons.push('來源記錄已標示為過期，不能當作目前有效資料。');
    if (cutoff) reasons.push('香港日期已進入或超過目標開獎日。');
    if (snapshot) reasons.push('來源狀態為 snapshot，只有保存的快照，未核實此刻的官方最新資料。');
    else if (!verifiedStatus) reasons.push('來源狀態未通過新鮮度核驗。');
    if (targetDay === null) reasons.push('目標日期尚未可靠核實，不推算適用日期。');
    if (!reasons.length) reasons.push('來源擷取距今未滿 24 小時；這仍是靜態快照，不是持續更新的即時資料。');
    reasons.push('正式獨支維持空白。');
    message.textContent = reasons.join(' ');
    ageLabel.textContent = Number.isFinite(ageSeconds) && ageSeconds >= 0
      ? '來源擷取距今約 ' + Math.floor(ageSeconds / 3600) + ' 小時 ' + Math.floor((ageSeconds % 3600) / 60) + ' 分鐘。時效上限：24 小時。'
      : '來源年齡無法可靠計算。時效上限：24 小時。';
    researchLabel.textContent = stale || cutoff || snapshot || !verifiedStatus || targetDay === null
      ? '此排序僅供歷史研究與稽核，不得當作當前有效選號。'
      : '此排序只描述本快照的研究結果，尚無已證實的預測優勢，也不構成投注建議。';
    document.getElementById('freshness-banner').dataset.state = stale ? 'stale' : cutoff ? 'target-cutoff' : snapshot ? 'snapshot' : verifiedStatus ? 'snapshot-within-24h' : 'unverified';
  }}
  document.getElementById('reload-page').addEventListener('click', () => window.location.reload());
  recompute();
  window.setInterval(recompute, 30000);
  window.addEventListener('pageshow', recompute);
  document.addEventListener('visibilitychange', () => {{ if (!document.hidden) recompute(); }});
}})();
</script>
</body>
</html>'''
