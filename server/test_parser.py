"""parser.py の unittest.

仕様 (.local/input-format.md) §3 / §4 / §5 に対する正常系 / 異常系を網羅する.
Python 標準ライブラリ unittest を使用. 外部依存なし.
"""
from __future__ import annotations

import json
import unittest

from parser import (
    AUQ_TYPE,
    InvalidInput,
    MAX_QUESTIONS,
    parse_input,
    require_only_ws_or_comments,
    validate_meta,
    validate_question,
)


def _meta(repo="auq-web", timeoutSec=300, **extra) -> str:
    body = {"$auq": "meta", "repo": repo, "timeoutSec": timeoutSec, **extra}
    return f'<script type="{AUQ_TYPE}">{json.dumps(body)}</script>'


def _q(qid, kind="single", title="t?", **extra) -> str:
    """テスト用: 最小要件を満たす question script を組み立てる"""
    body = {"id": qid, "kind": kind, "title": title}
    if kind in ("single", "multi"):
        body.setdefault("options", [
            {"value": "a", "label": "A"},
            {"value": "b", "label": "B"},
        ])
    elif kind == "rank":
        body.setdefault("items", [
            {"id": "x", "label": "X"},
            {"id": "y", "label": "Y"},
        ])
    body.update(extra)
    return f'<script type="{AUQ_TYPE}">{json.dumps(body)}</script>'


# ─────────────────────────────────────────────────────────────────────────────
# 正常系
# ─────────────────────────────────────────────────────────────────────────────


class HappyPathTest(unittest.TestCase):
    def test_single_question_with_meta(self):
        src = _meta() + "\n" + _q("q1") + "\n<p>desc</p>\n"
        out = parse_input(src)
        self.assertEqual(out["meta"], {"repo": "auq-web", "timeoutSec": 300})
        self.assertEqual(len(out["questions"]), 1)
        q = out["questions"][0]
        self.assertEqual(q["id"], "q1")
        self.assertEqual(q["kind"], "single")
        self.assertEqual(q["title"], "t?")
        self.assertIn("<p>desc</p>", q["descHtml"])

    def test_multiple_questions(self):
        src = (
            _meta()
            + _q("q1") + "<p>d1</p>"
            + _q("q2", kind="multi") + "<p>d2</p>"
            + _q("q3", kind="rank") + "<p>d3</p>"
            + _q("q4") + "<p>d4</p>"
        )
        out = parse_input(src)
        self.assertEqual(len(out["questions"]), 4)
        self.assertEqual([q["id"] for q in out["questions"]],
                         ["q1", "q2", "q3", "q4"])
        self.assertIn("<p>d1</p>", out["questions"][0]["descHtml"])
        self.assertIn("<p>d4</p>", out["questions"][3]["descHtml"])

    def test_no_meta_only_questions(self):
        """meta は任意 (§3.4 で repo/timeoutSec も任意). 質問だけでも通る"""
        src = _q("q1") + "<p>x</p>"
        out = parse_input(src)
        self.assertEqual(out["meta"], {})
        self.assertEqual(len(out["questions"]), 1)

    def test_meta_with_only_required_field(self):
        src = (
            f'<script type="{AUQ_TYPE}">{{"$auq":"meta"}}</script>'
            + _q("q1") + "<p>x</p>"
        )
        out = parse_input(src)
        self.assertEqual(out["meta"], {})

    def test_rank_kind(self):
        src = _meta() + _q("q1", kind="rank") + "<p>z</p>"
        out = parse_input(src)
        self.assertEqual(out["questions"][0]["kind"], "rank")
        self.assertEqual(len(out["questions"][0]["items"]), 2)

    def test_allow_other(self):
        src = _meta() + _q("q1", allowOther=True) + "<p>x</p>"
        out = parse_input(src)
        self.assertTrue(out["questions"][0]["allowOther"])


# ─────────────────────────────────────────────────────────────────────────────
# desc 保全 (§5.2.1 raw-slice 方式の正当性)
# ─────────────────────────────────────────────────────────────────────────────


class DescPreservationTest(unittest.TestCase):
    def test_html_entities_are_kept_raw(self):
        """desc の `&lt;` が `<` に変換されない事 (§5.2.4 convert_charrefs=False)"""
        src = _meta() + _q("q1") + "<pre><code>&lt;script&gt;...&lt;/script&gt;</code></pre>"
        out = parse_input(src)
        self.assertIn("&lt;script&gt;", out["questions"][0]["descHtml"])
        self.assertIn("&lt;/script&gt;", out["questions"][0]["descHtml"])
        # entities が `<` に decode されていない事を強く保証
        self.assertNotIn("<script>", out["questions"][0]["descHtml"])

    def test_svg_attribute_case_preserved(self):
        """SVG の viewBox / requiredExtensions 等 camelCase 属性が保持される事"""
        svg = '<svg viewBox="0 0 10 10" requiredExtensions="x"><rect/></svg>'
        src = _meta() + _q("q1") + svg
        out = parse_input(src)
        self.assertIn("viewBox", out["questions"][0]["descHtml"])
        self.assertIn("requiredExtensions", out["questions"][0]["descHtml"])

    def test_nested_auq_script_in_desc_is_preserved(self):
        """SVG の <metadata> 等で desc 内に application/auq+json が現れても
        それは desc の一部として流す (§3.3-1)"""
        nested = (
            '<svg><metadata>'
            f'<script type="{AUQ_TYPE}">{{"id":"fake","kind":"single","title":"x",'
            '"options":[{"value":"a","label":"A"},{"value":"b","label":"B"}]}}</script>'
            '</metadata></svg>'
        )
        src = _meta() + _q("q1") + nested
        out = parse_input(src)
        # marker 抽出は q1 の 1 件 (meta + q1) のみ. nested は desc に残る
        self.assertEqual(len(out["questions"]), 1)
        self.assertIn("<metadata>", out["questions"][0]["descHtml"])
        self.assertIn('"id":"fake"', out["questions"][0]["descHtml"])

    def test_text_javascript_in_desc_is_preserved(self):
        src = (
            _meta() + _q("q1")
            + '<p>js below</p>'
            + '<script type="text/javascript">alert(1);</script>'
            + '<p>after</p>'
        )
        out = parse_input(src)
        self.assertIn('<script type="text/javascript">', out["questions"][0]["descHtml"])
        self.assertIn("alert(1);", out["questions"][0]["descHtml"])

    def test_application_json_data_in_desc_is_preserved(self):
        """desc 内の application/json (auq+json ではない) は desc に流す"""
        src = (
            _meta() + _q("q1")
            + '<svg id="c"></svg>'
            + '<script type="application/json" id="d">{"v":[1,2,3]}</script>'
        )
        out = parse_input(src)
        self.assertIn('type="application/json"', out["questions"][0]["descHtml"])
        self.assertIn('"v":[1,2,3]', out["questions"][0]["descHtml"])

    def test_bom_at_start_is_stripped(self):
        src = "﻿" + _meta() + _q("q1") + "<p>x</p>"
        out = parse_input(src)
        self.assertEqual(len(out["questions"]), 1)

    def test_desc_leading_whitespace_kept(self):
        """§5.2.1a: descHtml は strip しない. leading ws は CSS 側の責務"""
        src = _meta() + _q("q1") + "\n\n<p>x</p>"
        self.assertTrue(parse_input(src)["questions"][0]["descHtml"].startswith("\n"))

    def test_type_with_whitespace_padding(self):
        src = (
            f'<script type="  {AUQ_TYPE}  ">{{"$auq":"meta"}}</script>'
            + _q("q1") + "<p>x</p>"
        )
        out = parse_input(src)
        self.assertEqual(out["meta"], {})

    def test_type_uppercase(self):
        src = (
            f'<script type="APPLICATION/AUQ+JSON">{{"$auq":"meta"}}</script>'
            + _q("q1") + "<p>x</p>"
        )
        out = parse_input(src)
        self.assertEqual(out["meta"], {})

    def test_type_with_charset_param_is_not_recognized(self):
        """`;charset=...` 付きは auq metadata として認識されない (§3.2).

        結果: その script は desc 領域候補として扱われ、後続の真の
        metadata script より前に「空白でない要素」がある事になり header 違反 400
        """
        src = (
            f'<script type="{AUQ_TYPE};charset=utf-8">{{"$auq":"meta"}}</script>'
            + _q("q1") + "<p>x</p>"
        )
        with self.assertRaises(InvalidInput):
            parse_input(src)


# ─────────────────────────────────────────────────────────────────────────────
# 異常系: ヘッダ領域 (§3.3-5)
# ─────────────────────────────────────────────────────────────────────────────


class HeaderRegionTest(unittest.TestCase):
    def test_content_before_first_metadata_script_rejected(self):
        src = "<p>foo</p>" + _q("q1") + "<p>x</p>"
        with self.assertRaises(InvalidInput):
            parse_input(src)

    def test_text_before_first_metadata_script_rejected(self):
        src = "hello " + _q("q1") + "<p>x</p>"
        with self.assertRaises(InvalidInput):
            parse_input(src)

    def test_whitespace_before_first_metadata_script_ok(self):
        src = "\n  \n" + _q("q1") + "<p>x</p>"
        out = parse_input(src)
        self.assertEqual(len(out["questions"]), 1)

    def test_html_comment_before_first_metadata_script_ok(self):
        src = "<!-- header --> \n" + _q("q1") + "<p>x</p>"
        out = parse_input(src)
        self.assertEqual(len(out["questions"]), 1)

    def test_unclosed_html_comment_before_metadata_rejected(self):
        src = "<!-- never closes" + _q("q1") + "<p>x</p>"
        with self.assertRaises(InvalidInput):
            parse_input(src)

    def test_content_between_meta_and_first_question_rejected(self):
        src = _meta() + "<p>foo</p>" + _q("q1") + "<p>x</p>"
        with self.assertRaises(InvalidInput):
            parse_input(src)

    def test_whitespace_between_meta_and_first_question_ok(self):
        src = _meta() + "\n\n  " + _q("q1") + "<p>x</p>"
        out = parse_input(src)
        self.assertEqual(len(out["questions"]), 1)


# ─────────────────────────────────────────────────────────────────────────────
# 異常系: 質問数 / meta 出現位置
# ─────────────────────────────────────────────────────────────────────────────


class StructureValidationTest(unittest.TestCase):
    def test_no_metadata_script_at_all(self):
        with self.assertRaises(InvalidInput):
            parse_input("<p>just html</p>")

    def test_only_meta_no_questions(self):
        with self.assertRaises(InvalidInput):
            parse_input(_meta())

    def test_too_many_questions(self):
        src = _meta() + "".join(_q(f"q{i}") + "<p/>" for i in range(MAX_QUESTIONS + 1))
        with self.assertRaises(InvalidInput):
            parse_input(src)

    def test_meta_in_second_position(self):
        src = _q("q1") + _meta() + "<p>x</p>"
        with self.assertRaises(InvalidInput):
            parse_input(src)

    def test_two_metas(self):
        src = _meta() + _meta() + _q("q1") + "<p>x</p>"
        with self.assertRaises(InvalidInput):
            parse_input(src)


# ─────────────────────────────────────────────────────────────────────────────
# 異常系: question / meta フィールドバリデーション
# ─────────────────────────────────────────────────────────────────────────────


class QuestionValidationTest(unittest.TestCase):
    def test_missing_id(self):
        body = {"kind": "single", "title": "t", "options": [
            {"value": "a", "label": "A"}, {"value": "b", "label": "B"}]}
        src = _meta() + f'<script type="{AUQ_TYPE}">{json.dumps(body)}</script><p/>'
        with self.assertRaises(InvalidInput):
            parse_input(src)

    def test_invalid_id_chars(self):
        with self.assertRaises(InvalidInput):
            parse_input(_meta() + _q("q-1") + "<p/>")

    def test_id_with_spaces(self):
        with self.assertRaises(InvalidInput):
            parse_input(_meta() + _q("q 1") + "<p/>")

    def test_duplicate_id(self):
        src = _meta() + _q("q1") + "<p/>" + _q("q1") + "<p/>"
        with self.assertRaises(InvalidInput):
            parse_input(src)

    def test_invalid_kind(self):
        with self.assertRaises(InvalidInput):
            parse_input(_meta() + _q("q1", kind="scale") + "<p/>")

    def test_options_too_few(self):
        body = {"id": "q1", "kind": "single", "title": "t",
                "options": [{"value": "a", "label": "A"}]}
        src = _meta() + f'<script type="{AUQ_TYPE}">{json.dumps(body)}</script><p/>'
        with self.assertRaises(InvalidInput):
            parse_input(src)

    def test_items_too_few(self):
        body = {"id": "q1", "kind": "rank", "title": "t",
                "items": [{"id": "x", "label": "X"}]}
        src = _meta() + f'<script type="{AUQ_TYPE}">{json.dumps(body)}</script><p/>'
        with self.assertRaises(InvalidInput):
            parse_input(src)

    def test_duplicate_option_value(self):
        body = {"id": "q1", "kind": "single", "title": "t",
                "options": [{"value": "a", "label": "A"}, {"value": "a", "label": "A2"}]}
        src = _meta() + f'<script type="{AUQ_TYPE}">{json.dumps(body)}</script><p/>'
        with self.assertRaises(InvalidInput):
            parse_input(src)

    def test_duplicate_item_id(self):
        body = {"id": "q1", "kind": "rank", "title": "t",
                "items": [{"id": "x", "label": "X"}, {"id": "x", "label": "X2"}]}
        src = _meta() + f'<script type="{AUQ_TYPE}">{json.dumps(body)}</script><p/>'
        with self.assertRaises(InvalidInput):
            parse_input(src)

    def test_invalid_json_body(self):
        src = (
            _meta()
            + f'<script type="{AUQ_TYPE}">{{ "id": "q1", }}</script><p/>'
        )
        with self.assertRaises(InvalidInput):
            parse_input(src)

    def test_meta_negative_timeout(self):
        body = {"$auq": "meta", "timeoutSec": -1}
        src = (
            f'<script type="{AUQ_TYPE}">{json.dumps(body)}</script>'
            + _q("q1") + "<p/>"
        )
        with self.assertRaises(InvalidInput):
            parse_input(src)

    def test_meta_timeout_zero_ok(self):
        """0 = 無制限 (§3.4)"""
        body = {"$auq": "meta", "timeoutSec": 0}
        src = (
            f'<script type="{AUQ_TYPE}">{json.dumps(body)}</script>'
            + _q("q1") + "<p/>"
        )
        self.assertEqual(parse_input(src)["meta"]["timeoutSec"], 0)

    def test_meta_timeout_float_rejected(self):
        body = {"$auq": "meta", "timeoutSec": 1.5}
        src = (
            f'<script type="{AUQ_TYPE}">{json.dumps(body)}</script>'
            + _q("q1") + "<p/>"
        )
        with self.assertRaises(InvalidInput):
            parse_input(src)

    def test_meta_timeout_bool_rejected(self):
        body = {"$auq": "meta", "timeoutSec": True}
        src = (
            f'<script type="{AUQ_TYPE}">{json.dumps(body)}</script>'
            + _q("q1") + "<p/>"
        )
        with self.assertRaises(InvalidInput):
            parse_input(src)


# ─────────────────────────────────────────────────────────────────────────────
# unit: helper 関数
# ─────────────────────────────────────────────────────────────────────────────


class HelperFunctionsTest(unittest.TestCase):
    def test_require_only_ws_or_comments_empty_ok(self):
        require_only_ws_or_comments("", "x")  # 例外を投げないこと

    def test_require_only_ws_or_comments_whitespace_ok(self):
        require_only_ws_or_comments("\n\t  \n", "x")

    def test_require_only_ws_or_comments_bom_ok(self):
        require_only_ws_or_comments("﻿  \n", "x")

    def test_require_only_ws_or_comments_comment_ok(self):
        require_only_ws_or_comments("<!-- a -->\n<!-- b -->", "x")

    def test_require_only_ws_or_comments_text_rejected(self):
        with self.assertRaises(InvalidInput):
            require_only_ws_or_comments("foo", "x")

    def test_require_only_ws_or_comments_tag_rejected(self):
        with self.assertRaises(InvalidInput):
            require_only_ws_or_comments("<p>x</p>", "x")

    def test_validate_meta_extra_fields_ok(self):
        # 不明 key は forward compat のため許容
        validate_meta({"$auq": "meta", "futureField": "x"})


if __name__ == "__main__":
    unittest.main()
