"""wire.py の unittest. §6.1.1 の escape 仕様を検証."""
from __future__ import annotations

import json
import unittest

from wire import escape_json_in_html_script, render_template, DEFAULT_SENTINEL


# 6 文字 escape 文字列 (リテラル \uXXXX). raw string で書くと 6 char になる.
_LT_ESC  = r"\u003c"
_GT_ESC  = r"\u003e"
_AMP_ESC = r"\u0026"
_LS_ESC  = r"\u2028"
_PS_ESC  = r"\u2029"


class EscapeJsonTest(unittest.TestCase):
    """§6.1.1: <script type="application/json"> 内 JSON escape の必須/防御要件"""

    def test_basic_object_roundtrip(self):
        out = escape_json_in_html_script({"a": 1, "b": "hello"})
        self.assertEqual(json.loads(out), {"a": 1, "b": "hello"})

    def test_less_than_is_escaped(self):
        """必須: `<` → `\\u003c` でないと </script> で early close される"""
        out = escape_json_in_html_script({"x": "</script>"})
        self.assertNotIn("<", out)
        self.assertIn(_LT_ESC, out)

    def test_greater_than_is_escaped(self):
        """防御: `>` も escape (HTML パーサ亜種への保険)"""
        out = escape_json_in_html_script({"x": "1>0"})
        self.assertNotIn(">", out)
        self.assertIn(_GT_ESC, out)

    def test_ampersand_is_escaped(self):
        out = escape_json_in_html_script({"x": "a&b"})
        self.assertNotIn("&", out)
        self.assertIn(_AMP_ESC, out)

    def test_line_separator_is_escaped(self):
        # 第1引数の中で実 U+2028 を構築 (chr() で生成. ソース直書きしない: §6.1.1 の diff 安全方針)
        out = escape_json_in_html_script({"x": "a" + chr(0x2028) + "b"})
        self.assertNotIn(chr(0x2028), out)
        self.assertIn(_LS_ESC, out)

    def test_paragraph_separator_is_escaped(self):
        out = escape_json_in_html_script({"x": "a" + chr(0x2029) + "b"})
        self.assertNotIn(chr(0x2029), out)
        self.assertIn(_PS_ESC, out)

    def test_quote_not_escaped_beyond_json(self):
        """JSON 文字列内 `'` は escape しない (§6.1.1 注). `"` は JSON 仕様で既に `\\\"`"""
        out = escape_json_in_html_script({"x": "it's"})
        self.assertIn("'", out)

    def test_full_breakout_payload_is_safe_for_script(self):
        """生 </script> を含む payload を escape しても script 早期 close されない事"""
        out = escape_json_in_html_script({"descHtml": "<p>hi</p><script>alert(1)</script>"})
        self.assertNotIn("</script>", out.lower())
        self.assertNotIn("</", out)

    def test_unicode_kept_when_safe(self):
        """ASCII 範囲外 (日本語等) は ensure_ascii=False により直接出力される"""
        out = escape_json_in_html_script({"x": "こんにちは"})
        self.assertIn("こんにちは", out)

    def test_browser_can_jsonparse_escaped_output(self):
        """escape 後の文字列を JSON.parse 相当 (Python json.loads) で読み戻せる事"""
        original = {"q": "<p>1 < 2 & 3 > 0</p>", "n": 42}
        encoded = escape_json_in_html_script(original)
        self.assertEqual(json.loads(encoded), original)


class RenderTemplateTest(unittest.TestCase):
    def test_replaces_sentinel_once(self):
        template = "<head><script>__AUQ_DATA__</script></head>"
        out = render_template(template, {"v": 1})
        self.assertIn('"v"', out)
        self.assertNotIn(DEFAULT_SENTINEL, out)

    def test_missing_sentinel_raises(self):
        with self.assertRaises(ValueError):
            render_template("no sentinel here", {})

    def test_multiple_sentinels_raise(self):
        template = "__AUQ_DATA__ and __AUQ_DATA__"
        with self.assertRaises(ValueError):
            render_template(template, {})

    def test_breakout_payload_does_not_close_script(self):
        """desc に </script> が混入してもテンプレが壊れない事"""
        template = '<script id="auq-questions" type="application/json">__AUQ_DATA__</script>'
        out = render_template(template, {"questions": [{"descHtml": "</script><img>"}]})
        self.assertEqual(out.lower().count("</script>"), 1)


if __name__ == "__main__":
    unittest.main()
