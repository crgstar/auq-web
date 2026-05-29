#!/usr/bin/env bash
# auq-web Skill のエントリ。SKILL.md (dotfiles 管理) は PATH 上の `auq-web` 経由でこれを呼ぶ。
#
# why wrapper: SKILL.md に server.py の絶対パスを書くと repo を移動した時に
# symlink 経由でも参照が壊れる。SCRIPT_DIR 解決を 1 箇所に閉じ込める。
#
# why realpath: このスクリプトは ~/.local/bin/auq-web という *ファイル symlink*
# 越しに PATH 経由で呼ばれる。BASH_SOURCE はその symlink のパスを指すので、
# dirname → pwd -P だけだと ~/.local/bin に着地して ../server を見失う
# (pwd -P はディレクトリ symlink は解くが、ファイル symlink は辿らない)。
# realpath で symlink を実体 (auq-web リポの skill/run.sh) まで解決してから
# dirname する。python3 を使うのは、結局 server.py を python3 で起動する＝
# python3 の存在が保証済みで、readlink -f の BSD/GNU 差を避けられるため。
set -euo pipefail

SOURCE="$(python3 -c 'import os, sys; print(os.path.realpath(sys.argv[1]))' "${BASH_SOURCE[0]}")"
SCRIPT_DIR="$(cd "$(dirname "$SOURCE")" && pwd -P)"
SERVER_PY="$SCRIPT_DIR/../server/server.py"

if [ ! -f "$SERVER_PY" ]; then
  echo "❌ server.py が見つかりません: $SERVER_PY" >&2
  echo "   (skill/ と server/ が同じ repo の sibling である前提)" >&2
  exit 1
fi

exec python3 "$SERVER_PY" "$@"
