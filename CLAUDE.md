# auq-web

Claude Code 本家の AskUserQuestion をベースに、**質問本文の表現力を自由化** するための Skill とサーバ一式。

- 質問本文: **Claude が freeform HTML を直接埋め込む**
- 答え受け箱: 固定スキーマ（選択肢 + 自由コメント + 並べ替え）で構造化された結果が返る

## アーキテクチャ

```
Claude → /<skill> → bash で server.py を background 起動 → open http://localhost:7777
       ↘ Monitor ツールで server stdout を tail
ユーザ → ブラウザで選択 + コメント + 並べ替え → POST /answer
       → server が JSON を stdout → Monitor が Claude へ通知 → server exit
```

## 確定済み設計判断

- **配信形態**: Skill 単身（MCP server ではなく `/<skill-name>` で起動）
- **言語**: Python
- **port**: 7777 固定。衝突時は「先のブラウザ画面を片付けて」と詳細メッセージ
- **受信モード**: background server + Monitor で stdout を tail（Claude は並行作業可能）
- **答え受け箱**: 選択肢 (single / multi) + 自由コメント + 並べ替え (rank)。固定スキーマ
- **質問本文**: Claude が freeform HTML を直接挿入。表・図 (SVG)・コードブロック
- **timeout**: answer JSON に `timedOut: true` フラグを立てて exit 0（呼び出し側の分岐を浅く）
- **キーバインド**: ⌘+Enter で submit
- **テーマ**: ダークモード

## ディレクトリ構成

```
auq-web/
├── CLAUDE.md
├── Makefile           # `make serve INPUT=...` で動作確認
├── server/
│   ├── parser.py      # HTML fragment → 内部表現 (純粋関数, §3/§5)
│   ├── wire.py        # `<` → \\u003c の escape + テンプレ置換 (§6.1.1)
│   ├── server.py      # stdin (or --input) → parse → render → 1-shot HTTP 配信
│   ├── index.html     # __AUQ_DATA__ sentinel + 動的 render する SPA
│   ├── samples/       # 仕様 §4 の入力例 fixture
│   └── test_*.py      # parser / wire / samples の unittest
└── skill/             # (未着手) SKILL.md と Claude が呼ぶエントリスクリプト
```

仕様の詳細 (入力フォーマット §3, パーサ実装 §5, wire format §6) は
`.local/input-format.md` に置いてある (作業中なので gitignore 配下)。
