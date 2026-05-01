"""auq-web parser: HTML fragment → 内部表現 dict.

HTML 入力を「§3 / §5 仕様の構造」に変換する純粋モジュール。I/O は持たない。
caller (server.py / テスト) が input str を渡し、dict / 例外を受け取る。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any, Literal


class InvalidInput(ValueError):
    """§5.3 の 400 Bad Request 相当のバリデーション失敗"""


# HTML5 void elements: 終了タグを取らないので depth カウンタから除外する.
# ここから外れた要素は <foo>...</foo> で 1 段ぶん depth を消費する前提で扱う
VOID_ELEMENTS = frozenset({
    "area", "base", "br", "col", "embed", "hr", "img", "input",
    "link", "meta", "param", "source", "track", "wbr",
})

AUQ_TYPE = "application/auq+json"

# §5.2.1a: </script> の `>` の char offset を求めるための regex.
# re.I を付けないと `</SCRIPT>` 等の大文字表記揺れに失敗する (HTML 仕様上は許容)
_CLOSE_SCRIPT_RE = re.compile(r"</\s*script\s*>", re.IGNORECASE)

_ID_RE = re.compile(r"^[a-zA-Z0-9_]+$")

ALLOWED_KINDS = frozenset({"single", "multi", "rank"})

MAX_QUESTIONS = 4
DEFAULT_TIMEOUT_SEC = 300


@dataclass
class Marker:
    """metadata script の input 上の位置と中身"""

    start: int  # `<script ...>` 開始タグの '<' の char offset
    end: int    # 対応する `</script>` の '>' の次の char offset
    data: Any   # script 本文を json.loads した結果
    kind: Literal["meta", "question"]


def _build_line_offsets(source: str) -> list[int]:
    """各行頭の char offset を返す. 1-indexed line に offsets[line-1] でアクセスする想定"""
    offsets = [0]
    for i, ch in enumerate(source):
        if ch == "\n":
            offsets.append(i + 1)
    return offsets


def _is_auq_type(value: str | None) -> bool:
    """`<script type="...">` の type が application/auq+json と一致するか.

    case-insensitive、前後空白は許容、`;charset=...` 等のパラメータは不許可 (§3.2)
    """
    if value is None:
        return False
    return value.strip().lower() == AUQ_TYPE


# HTMLParser: トップレベル (depth 0) の auq metadata script を抽出する


class AuqMarker(HTMLParser):
    def __init__(self, source: str) -> None:
        # convert_charrefs=False: desc 内の `&lt;` を `<` に変換させない.
        # auq script 自体は HTML5 raw-text mode で entity 変換が起きないので
        # この設定は desc 領域の保全のために必要 (§5.2.4)
        super().__init__(convert_charrefs=False)
        self.source = source
        self.line_offsets = _build_line_offsets(source)
        self.depth = 0
        self.in_auq = False
        self.auq_start = -1
        self.auq_data: list[str] = []
        self.markers: list[Marker] = []

    def _here(self) -> int:
        """getpos() が指す現在位置を char offset に変換"""
        line, col = self.getpos()
        return self.line_offsets[line - 1] + col

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        # auq 領域に入っている時に他タグの開始は来ない (script は raw-text mode).
        # 仮に来ても depth tracking を狂わせないために何もしない
        if self.in_auq:
            return
        # HTMLParser は attrs の name を lowercase で渡すので case-insensitive 化は型側で済む.
        # 同名複数属性が来た場合 dict() は last-wins. type 重複は HTML 仕様上未定義なので気にしない
        if tag == "script" and self.depth == 0 and _is_auq_type(dict(attrs).get("type")):
            self.in_auq = True
            self.auq_start = self._here()
            self.auq_data = []
        if tag not in VOID_ELEMENTS:
            self.depth += 1

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        # 自己終了タグ <foo/>: depth は変わらない. auq script 用途では使わない想定
        # (`<script .../>` だと body が空で JSON parse 失敗するため事実上書けない)
        return

    def handle_endtag(self, tag: str) -> None:
        if self.in_auq and tag == "script":
            lt_offset = self._here()
            m = _CLOSE_SCRIPT_RE.match(self.source, lt_offset)
            if m is None:
                # HTMLParser が </script> を観測した直後なので通常マッチするはず.
                # 万一マッチしない (内部状態の不整合) は実装バグなので 400 で落とす
                raise InvalidInput(
                    f"</script> 終端パターンが見つからない (offset {lt_offset})"
                )
            text = "".join(self.auq_data)
            try:
                data = json.loads(text)
            except json.JSONDecodeError as e:
                raise InvalidInput(
                    f"metadata script の JSON parse に失敗 (offset {self.auq_start}): {e.msg} "
                    f"@ line {e.lineno} col {e.colno}"
                ) from e
            kind: Literal["meta", "question"] = (
                "meta"
                if isinstance(data, dict) and data.get("$auq") == "meta"
                else "question"
            )
            self.markers.append(Marker(self.auq_start, m.end(), data, kind))
            self.in_auq = False
            self.auq_start = -1
            self.auq_data = []
            self.depth -= 1
            return
        if tag not in VOID_ELEMENTS and self.depth > 0:
            self.depth -= 1

    def handle_data(self, data: str) -> None:
        if self.in_auq:
            self.auq_data.append(data)


# ─────────────────────────────────────────────────────────────────────────────
# header (script の前) 領域の検証
# ─────────────────────────────────────────────────────────────────────────────


def require_only_ws_or_comments(text: str, region_label: str) -> None:
    """`text` が空白 / BOM / HTML コメント のみで構成されている事を検証する.

    違反時は InvalidInput を投げる. 実装は短い state machine.
    """
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch.isspace() or ch == "\ufeff":
            i += 1
            continue
        if text.startswith("<!--", i):
            end = text.find("-->", i + 4)
            if end < 0:
                raise InvalidInput(
                    f"{region_label}: 閉じない HTML コメント (<!-- ... に対応する --> がない)"
                )
            i = end + 3
            continue
        raise InvalidInput(
            f"{region_label} には空白/コメント以外を置けません "
            f"(offset {i}, char {ch!r})"
        )


# ─────────────────────────────────────────────────────────────────────────────
# validate
# ─────────────────────────────────────────────────────────────────────────────


def validate_meta(data: Any) -> None:
    if not isinstance(data, dict):
        raise InvalidInput("meta: object である必要があります")
    if data.get("$auq") != "meta":
        raise InvalidInput('meta: "$auq" は "meta" である必要があります')
    if "repo" in data and not isinstance(data["repo"], str):
        raise InvalidInput('meta.repo は string である必要があります')
    if "timeoutSec" in data:
        ts = data["timeoutSec"]
        # bool は int サブクラスのため明示排除. timeoutSec=true を 1 として解釈させない
        if isinstance(ts, bool) or not isinstance(ts, int):
            raise InvalidInput('meta.timeoutSec は整数である必要があります')
        if ts < 0:
            raise InvalidInput("meta.timeoutSec は 0 以上である必要があります")


def validate_question(data: Any, seen_ids: set[str]) -> None:
    if not isinstance(data, dict):
        raise InvalidInput("question: object である必要があります")

    qid = data.get("id")
    if not isinstance(qid, str) or not _ID_RE.match(qid):
        raise InvalidInput(
            f"question.id は ^[a-zA-Z0-9_]+$ にマッチする string である必要があります "
            f"(実際: {qid!r})"
        )
    if qid in seen_ids:
        raise InvalidInput(f'question.id "{qid}" が重複しています')
    seen_ids.add(qid)

    if not isinstance(data.get("title"), str):
        raise InvalidInput(f"question[{qid}].title は string である必要があります")

    kind = data.get("kind")
    if kind not in ALLOWED_KINDS:
        raise InvalidInput(
            f"question[{qid}].kind は {sorted(ALLOWED_KINDS)} のいずれかである必要があります "
            f"(実際: {kind!r})"
        )

    if kind in ("single", "multi"):
        _validate_choice_array(data, qid, array_key="options", id_key="value")
        if "allowOther" in data and not isinstance(data["allowOther"], bool):
            raise InvalidInput(
                f"question[{qid}].allowOther は bool である必要があります"
            )
    else:  # rank
        _validate_choice_array(data, qid, array_key="items", id_key="id")


def _validate_choice_array(
    data: dict, qid: str, *, array_key: str, id_key: str,
) -> None:
    """options (single/multi) と items (rank) は array_key と識別子 key 名以外
    全く同じ shape (要素 dict, label 必須, hint optional, id 重複禁止). 共通化"""
    arr = data.get(array_key)
    if not isinstance(arr, list) or len(arr) < 2:
        raise InvalidInput(
            f"question[{qid}].{array_key} は 2 件以上の array である必要があります"
        )
    seen: set[str] = set()
    for i, el in enumerate(arr):
        path = f"question[{qid}].{array_key}[{i}]"
        if not isinstance(el, dict):
            raise InvalidInput(f"{path} は object である必要があります")
        ident = el.get(id_key)
        if not isinstance(ident, str):
            raise InvalidInput(f"{path}.{id_key} は string である必要があります")
        if not isinstance(el.get("label"), str):
            raise InvalidInput(f"{path}.label は string である必要があります")
        if ident in seen:
            raise InvalidInput(f'{path}.{id_key} "{ident}" が重複しています')
        seen.add(ident)
        if "hint" in el and not isinstance(el["hint"], str):
            raise InvalidInput(f"{path}.hint は string である必要があります")


# ─────────────────────────────────────────────────────────────────────────────
# 公開 API
# ─────────────────────────────────────────────────────────────────────────────


def parse_input(source: str) -> dict:
    """HTML fragment を auq の内部表現に変換する.

    返り値:
        {
          "meta": { "repo"?: str, "timeoutSec"?: int },
          "questions": [ { id, kind, title, ..., descHtml }, ... ],
        }

    失敗時は InvalidInput を投げる (§5.3 の各 400 ケース).
    """
    if not isinstance(source, str):
        raise TypeError("source must be str")

    # §5.2.2: BOM が先頭にあれば strip. 以降の char offset 計算を簡潔化する
    if source.startswith("\ufeff"):
        source = source[1:]

    parser = AuqMarker(source)
    parser.feed(source)
    parser.close()
    markers = parser.markers

    if not markers:
        raise InvalidInput(
            "metadata script (application/auq+json) が見つかりません"
        )

    # §3.3-5: 入力先頭から最初の metadata script までは ws / コメントのみ許容
    require_only_ws_or_comments(
        source[0:markers[0].start],
        "入力先頭から最初の metadata script までの領域",
    )

    # markers[0] が meta なら以降の loop で 2 個目以降の meta は i!=0 で弾ける.
    # よって `seen_meta` flag は不要 (markers[0].kind の事前判定で同等)
    has_meta = markers[0].kind == "meta"
    parsed: dict = {"meta": {}, "questions": []}
    prev_q_end: int | None = None
    seen_question_ids: set[str] = set()

    for i, m in enumerate(markers):
        if m.kind == "meta":
            if i != 0:
                raise InvalidInput(
                    "meta は最初の metadata script である必要があります "
                    "(2 個目以降に置いてはいけない)"
                )
            validate_meta(m.data)
            parsed["meta"] = {k: v for k, v in m.data.items() if k != "$auq"}
            continue

        if has_meta and not parsed["questions"]:
            # §3.3-5: meta script と最初の question script の間も ws / コメントのみ
            require_only_ws_or_comments(
                source[markers[0].end:m.start],
                "meta script と最初の question の間の領域",
            )

        if parsed["questions"]:
            assert prev_q_end is not None
            parsed["questions"][-1]["descHtml"] = source[prev_q_end:m.start]

        validate_question(m.data, seen_question_ids)
        if len(parsed["questions"]) >= MAX_QUESTIONS:
            raise InvalidInput(
                f"question は最大 {MAX_QUESTIONS} 件です "
                "(AskUserQuestion 互換)"
            )
        # m.data を直接保存すると元 dict を汚染するので shallow copy する
        parsed["questions"].append(dict(m.data))
        prev_q_end = m.end

    if not parsed["questions"]:
        raise InvalidInput(
            "question が 0 件です (metadata script は 1 個以上必要)"
        )

    # 末尾 question の desc: 最後の script end から EOF まで
    assert prev_q_end is not None
    parsed["questions"][-1]["descHtml"] = source[prev_q_end:]

    return parsed
