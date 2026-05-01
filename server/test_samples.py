"""samples/ 配下の入力 fixture が parse_input を素通りし、
仕様書 §4 で謳われた特性 (descHtml の保全等) を満たす事を回帰検証する.

test_parser.py が unit (parser 内部の各分岐) を担うのに対し、
こちらは spec の input 例を丸ごと食わせる integration 寄りの確認.
"""
from __future__ import annotations

import os
import unittest

from parser import parse_input

SAMPLES_DIR = os.path.join(os.path.dirname(__file__), "samples")


def _load(name: str) -> str:
    """samples/<name> を UTF-8 で読み出す. BOM 等は parser 側が吸収する想定"""
    with open(os.path.join(SAMPLES_DIR, name), encoding="utf-8") as f:
        return f.read()


class SampleParseTests(unittest.TestCase):
    """各 sample が例外なく parse できる事を最低限の sanity check として確認"""

    def test_s41_parses(self) -> None:
        parse_input(_load("s41_single_question.html"))

    def test_s42_parses(self) -> None:
        parse_input(_load("s42_multi_question.html"))

    def test_s43_parses(self) -> None:
        parse_input(_load("s43_chart_with_js.html"))

    def test_s44_parses(self) -> None:
        parse_input(_load("s44_script_in_pre.html"))


class S41SingleQuestionTests(unittest.TestCase):
    """§4.1: 1 質問 + meta. desc は table と本文を保全する"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.out = parse_input(_load("s41_single_question.html"))

    def test_question_count_is_one(self) -> None:
        self.assertEqual(len(self.out["questions"]), 1)

    def test_question_id(self) -> None:
        self.assertEqual(self.out["questions"][0]["id"], "q1")

    def test_question_kind_single(self) -> None:
        self.assertEqual(self.out["questions"][0]["kind"], "single")

    def test_allow_other_true(self) -> None:
        self.assertTrue(self.out["questions"][0]["allowOther"])

    def test_desc_contains_table_and_label(self) -> None:
        # descHtml は raw slice なので、原文の `<table>` と option label が
        # そのまま残っている事を確認する (§5.2.1 raw-slice の本質)
        desc = self.out["questions"][0]["descHtml"]
        self.assertIn("<table>", desc)
        self.assertIn("Python で固める", desc)


class S42MultiQuestionTests(unittest.TestCase):
    """§4.2: 2 質問 (single + rank). 順序と kind, items 件数を確認"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.out = parse_input(_load("s42_multi_question.html"))

    def test_question_count_is_two(self) -> None:
        self.assertEqual(len(self.out["questions"]), 2)

    def test_question_ids_in_order(self) -> None:
        ids = [q["id"] for q in self.out["questions"]]
        self.assertEqual(ids, ["q1", "q3"])

    def test_second_kind_is_rank(self) -> None:
        self.assertEqual(self.out["questions"][1]["kind"], "rank")

    def test_rank_items_at_least_two(self) -> None:
        # rank は items 2 件以上が spec 上の最小単位 (§3.6)
        self.assertGreaterEqual(len(self.out["questions"][1]["items"]), 2)


class S43ChartWithJsTests(unittest.TestCase):
    """§4.3: desc 内の SVG / application/json / 通常 script が
    auq metadata と誤認されず、descHtml に**そのまま**残る事を検証"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.out = parse_input(_load("s43_chart_with_js.html"))

    def test_desc_contains_svg(self) -> None:
        # SVG は descHtml に raw slice として残る. id 属性付きで保全される事を確認
        desc = self.out["questions"][0]["descHtml"]
        self.assertIn('<svg id="chart"', desc)

    def test_desc_contains_application_json_script(self) -> None:
        # application/json は auq+json と区別され、metadata 抽出されずに
        # desc に残る (§3.2 MIME type discriminator). chart-data id ごと保全
        desc = self.out["questions"][0]["descHtml"]
        self.assertIn('type="application/json"', desc)
        self.assertIn('id="chart-data"', desc)


class S44ScriptInPreTests(unittest.TestCase):
    """§4.4 / §5.2.4: HTML エンティティが decode されずに保全される事.
    `convert_charrefs=False` + raw slice で `&lt;/script&gt;` のままになる"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.out = parse_input(_load("s44_script_in_pre.html"))

    def test_desc_keeps_entity_encoded_close_script(self) -> None:
        desc = self.out["questions"][0]["descHtml"]
        self.assertIn("&lt;/script&gt;", desc)

    def test_desc_does_not_contain_raw_close_script(self) -> None:
        # 生 `</script>` が混入していると、ブラウザに渡した瞬間に
        # 周囲の <script> タグが早期 close されて壊れる. 仕様 §5.2.4 の核心
        desc = self.out["questions"][0]["descHtml"]
        self.assertNotIn("</script>", desc)


if __name__ == "__main__":
    unittest.main()
