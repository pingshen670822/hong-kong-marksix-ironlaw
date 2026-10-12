"""Standard-library renderer regression tests, with an optional Node DOM suite.

Run from the repository root:
    python -m unittest discover -s tests -p 'test_renderer.py' -v
    node tests/renderer_expiry.cjs

No network, browser, deployed site, repository data, or third-party package is
needed.  --emit-fixture is an internal bridge for the standalone Node command.
"""
from __future__ import annotations

from copy import deepcopy
from html.parser import HTMLParser
import json
from pathlib import Path
import shutil
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from v10.report import render  # noqa: E402


def fixture() -> dict:
    """Synthetic, deterministic input: not a claimed real-world result."""
    return {
        "schema": "marksix_v10", "version": "10.0.0",
        "generated_at": "2026-10-12T03:00:00+00:00", "code_sha256": "c" * 64,
        "release_id": "r" * 64,
        "data": {
            "sha256": "d" * 64, "count": 2700, "first": "2003-01-02",
            "latest": "2026-10-10", "latest_period": "26/108",
            "retrieved_at_utc": "2026-10-12T02:00:00+00:00",
            "coverage": {"months": 285, "fixture_only": True},
        },
        "currentness": {"status": "fresh_verified", "age_seconds": 3600, "reason": "fixture"},
        "latest_draw": {
            "period": "26/108", "date": "2026-10-10",
            "main": [1, 5, 17, 30, 32, 44], "special": 7,
        },
        "target": {
            "date": "2026-10-13", "period": "26/109", "status": "official_announced",
            "source": "fixture", "cutoff_policy": "fixture",
        },
        # A deliberately malformed incoming formal pick must never be rendered.
        "formal": {"single": 49, "status": "unqualified", "reason": "fixture"},
        "research": {
            "model": "bayes_60", "rank": list(range(1, 50)),
            "top9": list(range(1, 10)), "single": 1, "score_kind": "relative",
            "adjusted_p": 0.0961048, "normal_baseline": 6 / 49, "extra_baseline": 1 / 49,
            "repeat_guard": {"repeated": True, "consecutive": 2, "warning": "fixture"},
            "differs_from_seal": True,
            "evaluation_window": ["2025-12-01", "2026-10-10"],
        },
        "evidence": {
            "development_rounds": 400, "development_hits": 67,
            "evaluation_rounds": 120, "evaluation_hits": 23,
            "prospective_rounds": 0, "prospective_hits": 0, "qualification": "fixture",
        },
        "seal": {
            "hash": "s" * 64, "based_on_period": "26/108",
            "created_at_utc": "2026-10-12T03:00:00Z", "model": "bayes_60",
            "data_sha256": "d" * 64, "code_sha256": "c" * 64,
            "single": 2, "top9": list(range(2, 11)),
            "ranking": list(range(2, 50)) + [1], "target": {"date": None},
        },
        "legacy": {"sha256": "l" * 64, "events": 7, "settlements": 3, "hits": 1, "caveat": "fixture"},
    }


class Page(HTMLParser):
    """Inspect the output as HTML rather than relying only on string matching."""
    def __init__(self, source: str):
        super().__init__()
        self.scripts: list[dict] = []
        self.active_script = None
        self.metas: dict = {}
        self.ids: list[str] = []
        self.links: list[str] = []
        self.tags: list[tuple[str, dict]] = []
        self.feed(source)

    def handle_starttag(self, tag: str, attrs: list):
        values = dict(attrs)
        self.tags.append((tag, values))
        if values.get("id"):
            self.ids.append(values["id"])
        if tag == "meta":
            self.metas[values.get("name")] = values.get("content")
        if tag == "script":
            self.active_script = {"attrs": values, "body": ""}
            self.scripts.append(self.active_script)
        if tag == "a":
            self.links.append(values.get("href", ""))

    def handle_endtag(self, tag: str):
        if tag == "script":
            self.active_script = None

    def handle_data(self, content: str):
        if self.active_script is not None:
            self.active_script["body"] += content


def javascript_fixture() -> dict:
    page = Page(render(fixture()))
    return {"state": page.scripts[0]["body"], "script": page.scripts[1]["body"]}


class RendererTests(unittest.TestCase):
    def setUp(self):
        self.analysis = fixture()
        self.output = render(self.analysis)
        self.page = Page(self.output)

    def test_deterministic_rendering_and_empty_schema(self):
        self.assertEqual(self.output, render(deepcopy(self.analysis)))
        empty = render({})
        self.assertIn("正式獨支：暫不提供", empty)
        self.assertIn("來源新鮮度未通過", empty)
        self.assertEqual(len(Page(empty).scripts), 2)

    def test_release_identity_and_provenance(self):
        self.assertEqual(self.page.metas["marksix-report-version"], self.analysis["release_id"])
        self.assertEqual(self.page.metas["marksix-report-period"], "26/108")
        for value in (self.analysis["code_sha256"], self.analysis["data"]["sha256"],
                      self.analysis["legacy"]["sha256"], self.analysis["seal"]["hash"],
                      self.analysis["generated_at"], self.analysis["data"]["retrieved_at_utc"]):
            self.assertIn(value, self.output)

    def test_accessible_sections_and_standalone_assets(self):
        self.assertEqual(len(self.page.ids), len(set(self.page.ids)))
        self.assertTrue(all(href[1:] in self.page.ids for href in self.page.links if href.startswith("#")))
        self.assertTrue(any(tag == "html" and attrs.get("lang") == "zh-Hant" for tag, attrs in self.page.tags))
        self.assertTrue(any(tag == "button" and attrs.get("type") == "button" for tag, attrs in self.page.tags))
        self.assertEqual(len(self.page.scripts), 2)
        self.assertTrue(all("src" not in item["attrs"] for item in self.page.scripts))
        self.assertFalse(any(tag in {"img", "iframe", "object", "embed", "link"} for tag, _ in self.page.tags))
        self.assertIn("@media(max-width:720px)", self.output)
        self.assertIn("@media(prefers-reduced-motion:reduce)", self.output)

    def test_formal_pick_always_blank_and_research_separate(self):
        formal = next(attrs for _, attrs in self.page.tags if attrs.get("id") == "formal-selection")
        self.assertIn("hidden", formal)
        self.assertIn('data-formal-selection hidden></span>', self.output)
        start = self.output.index('<section class="card formal"')
        section = self.output[start:self.output.index("</section>", start)]
        self.assertNotIn(">49<", section)
        self.assertIn("正式獨支：暫不提供", section)
        self.assertIn("研究第一順位", self.output)
        self.assertIn("共同平滑不改變頻率名次", self.output)

    def test_factual_baselines_and_separate_scores(self):
        self.assertIn("6/49 ≈ 12.24%", self.output)
        self.assertIn("1/49 ≈ 2.04%", self.output)
        self.assertIn("23 / 120（19.17%）", self.output)
        self.assertIn("0 / 0（尚無可結算樣本）", self.output)
        self.assertIn("p 值不是下期中獎機率", self.output)
        self.assertIn("不計入 V10 合格前瞻成績", self.output)

    def test_current_recalculation_and_original_seal_are_distinct(self):
        self.assertIn("本次重新計算的排序與原封存不同", self.output)
        self.assertIn("不以重算結果覆寫原封存或追改成績", self.output)
        self.analysis["research"]["differs_from_seal"] = False
        unchanged = render(self.analysis)
        self.assertIn("本次重新計算與原封存的排序一致", unchanged)
        self.assertNotIn("本次重新計算的排序與原封存不同", unchanged)
        del self.analysis["research"]["differs_from_seal"]
        self.assertIn("未提供本次重新計算與原封存的差異判定", render(self.analysis))

    def test_snapshot_never_claims_live_and_missing_target_not_guessed(self):
        self.analysis["currentness"]["status"] = "snapshot"
        self.analysis["target"]["date"] = None
        output = render(self.analysis)
        self.assertIn("此資料狀態為 snapshot", output)
        self.assertIn("沒有核實此刻的官方最新資料", output)
        self.assertIn("尚未核實，不推算日期", output)
        self.assertIn("不會抓取官方資料或啟動雲端重算", output)

    def test_all_string_surfaces_escape_markup_and_script_endings(self):
        attack = '</script><img src=x onerror=alert(1)><script>alert("x")</script> & \' "'
        surfaces = [
            ((), "release_id"), ((), "generated_at"), ((), "code_sha256"),
            (("data",), "sha256"), (("data",), "coverage"), (("data",), "retrieved_at_utc"),
            (("currentness",), "status"), (("currentness",), "reason"),
            (("latest_draw",), "period"), (("target",), "date"), (("target",), "source"),
            (("formal",), "reason"), (("research",), "model"), (("research",), "score_kind"),
            (("research", "repeat_guard"), "warning"), (("evidence",), "qualification"),
            (("seal",), "hash"), (("seal",), "target"), (("legacy",), "caveat"),
        ]
        for path, key in surfaces:
            with self.subTest(path=path, key=key):
                value = deepcopy(self.analysis)
                mapping = value
                for segment in path:
                    mapping = mapping[segment]
                mapping[key] = attack
                output = render(value)
                page = Page(output)
                self.assertEqual(len(page.scripts), 2)
                self.assertFalse(any(tag == "img" for tag, _ in page.tags))
                self.assertNotIn("<img src=x", output)
                self.assertIn("&lt;img src=x", output)
                self.assertFalse(any(name.startswith("on") for _, attrs in page.tags for name in attrs))
                json.loads(page.scripts[0]["body"])
                if key == "release_id":
                    self.assertEqual(page.metas["marksix-report-version"], attack)
                if key == "generated_at":
                    self.assertEqual(json.loads(page.scripts[0]["body"])["generatedAt"], attack)
                    self.assertIn(r"\u003c/script\u003e", page.scripts[0]["body"])

    @unittest.skipUnless(shutil.which("node"), "Node is needed for the JavaScript DOM harness")
    def test_javascript_expiry_and_refresh_harness(self):
        process = subprocess.run(
            [shutil.which("node"), str(ROOT / "tests" / "renderer_expiry.cjs"), "--stdin"],
            input=json.dumps(javascript_fixture()), text=True, capture_output=True,
            cwd=ROOT, check=False, timeout=30,
        )
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        self.assertIn("All renderer DOM checks passed", process.stdout)


if __name__ == "__main__":
    if sys.argv[1:] == ["--emit-fixture"]:
        print(json.dumps(javascript_fixture()))
    else:
        unittest.main()
