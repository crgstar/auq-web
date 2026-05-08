"""server.py の unittest.

`_load_payload` の決定ロジックを中心に, parse 失敗時にどの経路へ落ちるかを
網羅する.

F7: --input + 非 watch + parse 失敗 → server を起動継続 (browser に error 画面)
が最新のルール. テストはこの分岐を含む.
"""
from __future__ import annotations

import argparse
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

from server import _load_payload
# parser script の最小組み立ては test_parser の helper を共有して
# parser 仕様変更時の追従点を一箇所に保つ
from test_parser import _meta, _q


VALID_HTML = _meta() + "\n" + _q("q1") + "\n<p>desc</p>\n"

# parser が必ず弾く形: meta はあるが question 0 件
INVALID_HTML = _meta() + "\n<p>question 無し</p>\n"


def _ns(**overrides) -> argparse.Namespace:
    """_load_payload が読む属性だけ持つ最小 Namespace"""
    base = {"input": None, "validate": False, "watch": False}
    base.update(overrides)
    return argparse.Namespace(**base)


class LoadPayloadTest(unittest.TestCase):
    def _write_tmp(self, body: str) -> str:
        fd, path = tempfile.mkstemp(suffix=".html")
        os.close(fd)
        with open(path, "w", encoding="utf-8") as f:
            f.write(body)
        self.addCleanup(os.remove, path)
        return path

    # ── 正常系 ──────────────────────────────────────────────────────────

    def test_valid_input_returns_payload(self):
        path = self._write_tmp(VALID_HTML)
        payload, exit_code = _load_payload(_ns(input=path))

        self.assertIsNone(exit_code)
        self.assertIsNotNone(payload)
        self.assertEqual(payload["meta"]["repo"], "auq-web")
        self.assertEqual(len(payload["questions"]), 1)

    # ── --validate (CI 用途): parse 失敗で exit 1 + JSON ───────────────

    def test_validate_with_invalid_input_exits_1_and_emits_error_json(self):
        path = self._write_tmp(INVALID_HTML)
        out = io.StringIO()
        with redirect_stdout(out):
            payload, exit_code = _load_payload(_ns(input=path, validate=True))

        self.assertIsNone(payload)
        self.assertEqual(exit_code, 1)
        emitted = json.loads(out.getvalue())
        self.assertFalse(emitted["ok"])
        self.assertIn("error", emitted)

    # ── --watch / --input + 非 watch (F7): server 継続 ─────────────────
    # どちらも GET / で再 parse する経路に合流. exit せず (None, None).

    def test_watch_with_invalid_input_keeps_server_alive(self):
        path = self._write_tmp(INVALID_HTML)
        err = io.StringIO()
        with redirect_stderr(err):
            payload, exit_code = _load_payload(_ns(input=path, watch=True))

        self.assertIsNone(payload)
        self.assertIsNone(exit_code)
        self.assertIn("server 継続", err.getvalue())

    def test_input_with_invalid_html_keeps_server_alive_f7(self):
        path = self._write_tmp(INVALID_HTML)
        err = io.StringIO()
        with redirect_stderr(err):
            payload, exit_code = _load_payload(_ns(input=path))

        # exit せず (None, None) → main() が reload_input_path を立てて
        # GET / でエラー画面 200 を返す
        self.assertIsNone(payload)
        self.assertIsNone(exit_code)
        self.assertIn("server 継続", err.getvalue())

    def test_input_path_missing_keeps_server_alive_f7(self):
        """ファイル不在 (OSError) も同じ経路で救済する.
        書き手が path を typo した時にも server-up + browser error の方が親切."""
        err = io.StringIO()
        with redirect_stderr(err):
            payload, exit_code = _load_payload(
                _ns(input="/tmp/auq-web-does-not-exist-xyz.html"),
            )

        self.assertIsNone(payload)
        self.assertIsNone(exit_code)
        self.assertIn("server 継続", err.getvalue())

    # ── stdin 経路: 再読込不可なので exit 1 ────────────────────────────

    def test_stdin_parse_fail_exits_1(self):
        original = sys.stdin
        sys.stdin = io.StringIO(INVALID_HTML)
        try:
            err = io.StringIO()
            with redirect_stderr(err):
                payload, exit_code = _load_payload(_ns())
        finally:
            sys.stdin = original

        self.assertIsNone(payload)
        self.assertEqual(exit_code, 1)
        self.assertIn("バリデーション失敗", err.getvalue())


if __name__ == "__main__":
    unittest.main()
