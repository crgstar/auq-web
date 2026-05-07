#!/usr/bin/env bash
# auq-web Skill のエントリ。SKILL.md からはこの run.sh を呼ぶ。
#
# why wrapper: SKILL.md に server.py の絶対パスを書くと repo を移動した時に
# symlink 経由でも参照が壊れる。SCRIPT_DIR 解決を 1 箇所に閉じ込める。
#
# why pwd -P: ~/.claude/skills/auq-web/run.sh から呼ばれる時, BASH_SOURCE 自体は
# symlink ではなく親ディレクトリ (auq-web) が symlink。`pwd -P` で物理パスに
# 解決すると、本体側の /Users/kumazaki/projects/auq-web/skill が得られる。
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
SERVER_PY="$SCRIPT_DIR/../server/server.py"

if [ ! -f "$SERVER_PY" ]; then
  echo "❌ server.py が見つかりません: $SERVER_PY" >&2
  echo "   (skill/ と server/ が同じ repo の sibling である前提)" >&2
  exit 1
fi

exec python3 "$SERVER_PY" "$@"
