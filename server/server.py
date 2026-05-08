#!/usr/bin/env python3
"""auq-web one-shot server.

GET  /            -> rendered index.html (parser → wire の結果を埋め込んだ HTML)
POST /answer      -> body JSON to stdout, 200 OK, then graceful shutdown
GET  /api/draft   -> 直近 draft (無ければ {})
POST /api/draft   -> partial answer を保存 (atomic)
DELETE /api/draft -> draft 破棄
others            -> 404

Why one-shot: the answer JSON on stdout is the contract between server and
caller (Skill via Monitor). One process, one answer; no long-running state.

入力経路 (§5.1):
  - stdin から HTML fragment を受け取る (デフォルト)
  - --input <path> で path を読む (debug 時)
  - 両方指定された場合は --input を優先
"""
import argparse
import errno
import html as html_lib
import json
import os
import subprocess
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer

from parser import InvalidInput, parse_input
from wire import render_template

HERE = os.path.dirname(os.path.abspath(__file__))
INDEX_PATH = os.path.join(HERE, "index.html")
DEFAULT_PORT = 7777
SHUTDOWN_POLL_SEC = 0.05  # serve_forever が shutdown フラグを観測する間隔。短くしてレスポンス完了直後の終了を速める


class DraftStore:
    """フォーム入力中の draft (partial answer) を保持する.

    タブクラッシュ・誤閉じ・長考 timeout で入力が消失するのを防ぐのが目的.
    1 server プロセス = 1 質問セッション なので保持する draft は最大 1 件.
    file path 指定があれば atomic write で永続化し、プロセス再起動越しにも残る.
    """

    def __init__(self, file_path: str | None) -> None:
        self.file_path = file_path
        self._buffer: bytes | None = None

    def read(self) -> bytes:
        if self.file_path:
            try:
                with open(self.file_path, "rb") as f:
                    return f.read()
            except FileNotFoundError:
                pass  # まだ保存されていない or 既に消えた
        return self._buffer or b""

    def write(self, body: bytes) -> None:
        self._buffer = body
        if self.file_path:
            # tmp + rename: 中途半端な内容で永続化されないよう atomic に置換
            tmp = self.file_path + ".tmp"
            with open(tmp, "wb") as f:
                f.write(body)
            os.replace(tmp, self.file_path)

    def clear(self) -> None:
        self._buffer = None
        if self.file_path:
            try:
                os.remove(self.file_path)
            except FileNotFoundError:
                pass  # idempotent: 既に消えていてよい


class Handler(BaseHTTPRequestHandler):
    rendered_html: bytes = b""  # main() が起動前に書き込む

    def _send_bytes(
        self, status: int, content_type: str, body: bytes,
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802 (BaseHTTPRequestHandler convention)
        if self.path == "/api/draft":
            body = self.server.draft_store.read() or b"{}"
            self._send_bytes(200, "application/json", body)
            return
        if self.path not in ("/", "/index.html"):
            self.send_error(404, "Not Found")
            return
        # watch mode (dev): 編集 → ブラウザリロードで即反映するため毎回 input を
        # 読み直して再 render. parse 失敗は exit せず人間が読めるエラー画面を 200 で返す
        if self.server.watch_input_path:
            content = _render_for_watch(
                self.server.watch_input_path, self.server.template_str,
            )
        else:
            content = self.rendered_html
        self._send_bytes(200, "text/html; charset=utf-8", content)

    def do_POST(self):  # noqa: N802
        if self.path == "/api/draft":
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b""
            try:
                # 中身は使わないが JSON 妥当性は検証する: 壊れた body を保存して
                # 後の GET /api/draft で復元失敗するのを防ぐ
                json.loads(raw.decode("utf-8") or "{}")
            except (UnicodeDecodeError, json.JSONDecodeError) as e:
                self.send_error(400, f"Invalid JSON: {e}")
                return
            self.server.draft_store.write(raw)
            self._send_bytes(200, "application/json", b"{}")
            return

        if self.path != "/answer":
            self.send_error(404, "Not Found")
            return
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        try:
            payload = json.loads(raw.decode("utf-8") or "{}")
        except (UnicodeDecodeError, json.JSONDecodeError) as e:
            self.send_error(400, f"Invalid JSON: {e}")
            return

        # 確定回答が来たので draft は不要. file path 残骸を消して再起動時に
        # 「古い draft が復元される」事故を防ぐ
        self.server.draft_store.clear()

        body = b"{}"
        # /answer は graceful shutdown 前に Connection: close を立てたいので
        # 共通 _send_bytes ではなく個別に書く (Cache-Control も不要)
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)
        self.wfile.flush()
        self.close_connection = True

        sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
        sys.stdout.flush()

        # server.shutdown() は serve_forever() が回っている別 (= main) スレッドの
        # 完了を待つので、handler スレッドから直接呼ぶとデッドロックする。daemon で逃がす
        threading.Thread(target=self.server.shutdown, daemon=True).start()

    def do_DELETE(self):  # noqa: N802
        if self.path == "/api/draft":
            self.server.draft_store.clear()
            self._send_bytes(200, "application/json", b"{}")
            return
        self.send_error(404, "Not Found")

    def log_message(self, format, *args):  # noqa: A002
        pass


def report_port_conflict(port: int) -> None:
    occupant = ""
    try:
        result = subprocess.run(
            ["lsof", f"-iTCP:{port}", "-sTCP:LISTEN", "-n", "-P"],
            capture_output=True, text=True, timeout=2,
        )
        occupant = result.stdout.strip()
    except Exception:
        pass

    msg = [
        f"❌ port {port} は既に使われています。",
        "",
        "auq-web は port 7777 を固定で使います。考えられる原因:",
        "  1. 前回開いたブラウザタブ + サーバが残っている",
        "     → そのタブで submit するか、タブを閉じてサーバを終了させてください",
        "  2. 別の auq-web プロセスが背面で生きている",
        f"     → `lsof -iTCP:{port} -sTCP:LISTEN` で PID を特定し kill",
        "  3. 別アプリが偶然 7777 を使っている",
        "     → 該当アプリを停止",
    ]
    if occupant:
        msg += ["", "現在の占有プロセス:", occupant]
    print("\n".join(msg), file=sys.stderr)


def _read_input(input_path: str | None) -> str:
    """§5.1: --input が指定されていればそちらを, なければ stdin を読む"""
    if input_path:
        with open(input_path, encoding="utf-8") as f:
            return f.read()
    return sys.stdin.read()


# watch mode のエラー画面.
# なぜ 200 で返す: 401/500 だとブラウザ拡張のキャッシュや devtools のフィルタで
# 「ページ読めない」状態になり、編集→リロードのループが分断されるため.
# 200 + 中身が「赤いエラー」の方が人間にもループにも優しい.
# パレットは index.html の dark theme と意図的に揃えている (依存させると
# index.html 不在時に動かなくなるので、独立 mirror として扱う)
_WATCH_ERROR_TEMPLATE = """<!doctype html>
<html lang="ja"><head><meta charset="utf-8">
<title>auq-web: invalid input</title>
<style>
  body {{ background:#0d1117; color:#f0f6fc; font:14px/1.5 -apple-system,system-ui,sans-serif; padding:24px; max-width:900px; margin:auto; }}
  h1 {{ color:#f85149; font-size:15px; margin:0 0 12px; }}
  .label {{ color:#b1bac4; font-size:12px; }}
  pre {{ background:#161b22; border:1px solid #30363d; padding:12px; border-radius:5px;
        color:#f85149; white-space:pre-wrap; word-break:break-word; font:12.5px/1.5 ui-monospace,monospace; }}
  .hint {{ color:#7d8590; font-size:12px; margin-top:14px; }}
</style></head>
<body>
<h1>❌ auq-web: input parse failed</h1>
<div class="label">--watch mode: edit and reload to retry</div>
<pre>{detail}</pre>
<div class="hint">source: <code>{path}</code></div>
</body></html>
"""


def _render_for_watch(input_path: str, template: str) -> bytes:
    """watch mode 専用: input を読み直して render. 失敗時はエラー HTML を返す.
    template は起動時にキャッシュされたものを受け取る (毎回 disk 読みしないため).
    """
    try:
        source = _read_input(input_path)
        payload = parse_input(source)
        return render_template(template, payload).encode("utf-8")
    except (InvalidInput, OSError, ValueError) as e:
        body = _WATCH_ERROR_TEMPLATE.format(
            detail=html_lib.escape(str(e)),
            path=html_lib.escape(input_path),
        )
        return body.encode("utf-8")


def _validate_summary(payload: dict) -> dict:
    """--validate の出力に詰める「目で読める要約」.
    desc 文字数 + 各 question の識別子一覧くらいで十分 (parser が通った時点で
    schema は OK と分かっているので、書き手が「自分の意図通り構造化されたか」
    を確認するための情報だけを返す)"""
    questions = []
    for q in payload["questions"]:
        item = {
            "id": q["id"],
            "kind": q["kind"],
            "title": q.get("title", ""),
            "descLen": len(q.get("descHtml", "")),
        }
        if q["kind"] in ("single", "multi"):
            item["options"] = [o["value"] for o in q.get("options", [])]
            if q.get("allowOther"):
                item["allowOther"] = True
        else:  # rank
            item["items"] = [i["id"] for i in q.get("items", [])]
        questions.append(item)
    return {"ok": True, "meta": payload["meta"], "questions": questions}


def _emit_validate_json(obj: dict) -> None:
    json.dump(obj, sys.stdout, ensure_ascii=False)
    sys.stdout.write("\n")


def _load_payload(args: argparse.Namespace) -> tuple[dict | None, int | None]:
    """input を読んで parse する. 戻り値は (payload, exit_code).

    - payload, None  : 成功. caller は通常フローへ
    - None, exit_code: 失敗 + exit すべき. 出力は本関数が済ませている
    - None, None     : watch mode で起動時失敗. caller はサーバを起動して継続
    """
    try:
        source = _read_input(args.input)
        return parse_input(source), None
    except (OSError, InvalidInput) as e:
        if args.validate:
            _emit_validate_json({"ok": False, "error": str(e)})
            return None, 1
        if args.watch:
            print(f"⚠️ 起動時 input 読込み/parse 失敗 (watch 継続): {e}", file=sys.stderr)
            return None, None
        prefix = "❌ 入力読込み失敗" if isinstance(e, OSError) else "❌ 入力 HTML のバリデーション失敗"
        print(f"{prefix}: {e}", file=sys.stderr)
        return None, 1


def main() -> int:
    arg_parser = argparse.ArgumentParser(description="auq-web one-shot server")
    arg_parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    arg_parser.add_argument("--host", default="127.0.0.1")
    arg_parser.add_argument(
        "--input",
        help="HTML fragment ファイルパス. 省略時は stdin (§5.1)",
    )
    arg_parser.add_argument(
        "--no-open", action="store_true",
        help="起動時にブラウザを自動オープンしない (headless / --static 用途)",
    )
    arg_parser.add_argument(
        "--validate", action="store_true",
        help="parse 結果を JSON で stdout に出して exit. server は起動しない. "
             "書き手が「自分の意図通り構造化されたか」を起動前に確認する dry-run.",
    )
    arg_parser.add_argument(
        "--static", dest="static_path", metavar="PATH",
        help="render 済み HTML を PATH に書いて exit. server は起動しない. "
             "回答 UI は disabled になる (Slack/docbase 貼付け用のスナップショット).",
    )
    arg_parser.add_argument(
        "--watch", action="store_true",
        help="dev hot-reload: GET / の度に --input を再読込 + parse + render. "
             "編集 → ブラウザリロードで即反映するモード. parse 失敗は exit せず "
             "200 でエラー画面. --input 必須 (stdin だと再読込できないため).",
    )
    arg_parser.add_argument(
        "--draft-out", dest="draft_out", metavar="PATH",
        help="フォーム入力中の draft を atomic 永続化する path. "
             "省略時は memory のみ (server の生きてる間だけ存続).",
    )
    args = arg_parser.parse_args()

    if args.watch and not args.input:
        print("❌ --watch には --input が必要です (stdin 再読込不可)", file=sys.stderr)
        return 1
    if args.watch and args.validate:
        # validate は「1 回 parse して exit」なので watch (再読込ループ) と
        # 用途が背反. 両指定はユーザの意図ミスとして弾く
        print("❌ --watch と --validate は併用できません", file=sys.stderr)
        return 1

    payload, exit_code = _load_payload(args)
    if exit_code is not None:
        return exit_code

    if args.validate:
        # exit_code is None かつ payload が None になるのは watch 経路だけだが、
        # 上で watch+validate を弾いているのでここに来た時 payload は必ず非 None
        assert payload is not None
        _emit_validate_json(_validate_summary(payload))
        return 0

    try:
        with open(INDEX_PATH, encoding="utf-8") as f:
            template = f.read()
    except OSError as e:
        print(f"❌ index.html 読込み失敗: {e}", file=sys.stderr)
        return 1

    if args.static_path:
        if payload is None:
            print("❌ --static には有効な --input が必要です", file=sys.stderr)
            return 1
        try:
            # static mode は payload に "mode" を載せて render_template に渡す.
            # mode を見た index.html JS が回答 UI を disabled 化する.
            rendered = render_template(template, {**payload, "mode": "static"})
            with open(args.static_path, "w", encoding="utf-8") as f:
                f.write(rendered)
        except (OSError, ValueError) as e:
            print(f"❌ static 書き出し失敗: {e}", file=sys.stderr)
            return 1
        print(f"✓ wrote {args.static_path}", file=sys.stderr)
        return 0

    if payload is not None:
        try:
            Handler.rendered_html = render_template(template, payload).encode("utf-8")
        except ValueError as e:
            print(f"❌ テンプレ render 失敗: {e}", file=sys.stderr)
            return 1
    # else: watch mode で payload 取得失敗. _render_for_watch が GET / 時に再試行する

    try:
        server = HTTPServer((args.host, args.port), Handler)
    except OSError as e:
        if e.errno == errno.EADDRINUSE:
            report_port_conflict(args.port)
            return 1
        raise

    # handler から self.server.<x> でアクセスする instance state.
    # クラス変数にすると test 間でリークするので instance に閉じ込める
    server.watch_input_path = args.input if args.watch else None
    server.template_str = template
    server.draft_store = DraftStore(args.draft_out)

    url = f"http://{args.host}:{args.port}/"
    print(f"auq-web listening on {url}", file=sys.stderr)
    if args.watch:
        print(f"--watch enabled: re-reading {args.input} on every GET /", file=sys.stderr)
    # webbrowser.open は OS 横断 (macOS=open / Linux=xdg-open / Windows=start).
    # headless / ssh 越しでは False が返るが exit せず警告だけにする:
    # 「URL を手動で開けば運用上 OK」のケース (ssh tunnel 先で確認するなど)
    # を潰したくないため.
    if not args.no_open and not webbrowser.open(url):
        print(
            f"⚠️ ブラウザを自動で開けませんでした。手動で {url} を開いてください。",
            file=sys.stderr,
        )
    try:
        server.serve_forever(poll_interval=SHUTDOWN_POLL_SEC)
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 130
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
