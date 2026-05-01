"""auq-web wire format: 内部表現 → ブラウザ向け HTML テンプレ.

§6 のテンプレ機構を提供する純粋モジュール。
- escape_json_in_html_script: JSON を `<script type="application/json">` 内に
  安全に埋めるための文字置換 (§6.1.1)
- render_template: index.html の `__AUQ_DATA__` sentinel を置換
"""
from __future__ import annotations

import json
from typing import Any

DEFAULT_SENTINEL = "__AUQ_DATA__"

# §6.1.1 の必須 + 防御 escape を 1 pass で適用するための変換テーブル.
#   `<` → `\u003c` が必須 (生 </script> による early close 回避).
#   `>` `&` `U+2028` `U+2029` は将来 inline JS literal 経路に切り替えた時の保険.
# str.maketrans の dict 形式は key に 1 文字, value に多文字 string を許す.
_ESCAPE_TABLE = str.maketrans({
    "<":      r"\u003c",
    ">":      r"\u003e",
    "&":      r"\u0026",
    "\u2028": r"\u2028",
    "\u2029": r"\u2029",
})


def escape_json_in_html_script(payload: Any) -> str:
    """JSON を `<script type="application/json">` 内に埋めるための escape.

    XSS 緩和ではなく `</script>` break-out 回避が目的。
    信頼モデル (§2-6) の下では XSS そのものは対策対象ではない。
    """
    return json.dumps(payload, ensure_ascii=False).translate(_ESCAPE_TABLE)


def render_template(
    template: str,
    payload: Any,
    sentinel: str = DEFAULT_SENTINEL,
) -> str:
    """`template` 内の sentinel を escape 済み JSON で 1 度だけ置換する.

    sentinel が複数回出ると壊れる (multiple replace). 1 回出現を要求し,
    違反時は ValueError を投げる. これにより template の取り違えを早期検知できる
    """
    count = template.count(sentinel)
    if count == 0:
        raise ValueError(f"template に sentinel {sentinel!r} が見つかりません")
    if count > 1:
        raise ValueError(
            f"template に sentinel {sentinel!r} が複数 ({count} 個) あります. "
            "1 個のみ許容"
        )
    return template.replace(sentinel, escape_json_in_html_script(payload))
