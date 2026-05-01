#!/usr/bin/env python3
"""auq-web minimal server (mock).

GET  /          -> server/index.html
POST /answer    -> body JSON to stdout, 200 OK, then graceful shutdown
others          -> 404

Why one-shot: the answer JSON on stdout is the contract between server and
caller (Skill via Monitor). One process, one answer; no long-running state.
"""
import argparse
import errno
import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
INDEX_PATH = os.path.join(HERE, "index.html")
DEFAULT_PORT = 7777
SHUTDOWN_POLL_SEC = 0.05  # serve_forever が shutdown フラグを観測する間隔。短くしてレスポンス完了直後の終了を速める


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802 (BaseHTTPRequestHandler convention)
        if self.path not in ("/", "/index.html"):
            self.send_error(404, "Not Found")
            return
        with open(INDEX_PATH, "rb") as f:
            content = f.read()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(content)

    def do_POST(self):  # noqa: N802
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

        body = b"{}"
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


def main() -> int:
    parser = argparse.ArgumentParser(description="auq-web minimal mock server")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()

    try:
        server = HTTPServer((args.host, args.port), Handler)
    except OSError as e:
        if e.errno == errno.EADDRINUSE:
            report_port_conflict(args.port)
            return 1
        raise

    url = f"http://{args.host}:{args.port}/"
    print(f"auq-web listening on {url}", file=sys.stderr)
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
