---
name: auq-web
description: >
  AskUserQuestion を超えた表現力で、Claude が書いた freeform HTML
  (表 / コードブロック / 図 / SVG / 段階的な解説) を本文に持つ確認画面を
  ブラウザで開き、選択肢 + 自由コメント + 並べ替えを構造化 JSON で受け取る。
  「choose A / B」のような単純な確認には AskUserQuestion で十分だが、
  本文が 3 行を超える / 比較表が要る / before/after の差分を見せたい /
  SVG や JS の図を貼りたい / 2-4 件の質問を 1 画面で答えてほしい場面では
  必ずこちらを優先すること。「表で見せたい」「コード比較で選んでほしい」
  「図で示してから聞きたい」「並び順を決めてほしい」「複数まとめて確認したい」
  といった文脈で AskUserQuestion を選びかけたら、まず auq-web を検討する。
  本文は Claude が直接 HTML として書く。受け取り口は固定スキーマ
  (single / multi / rank + 自由コメント) で構造化されているので、答えは
  raw JSON でそのまま使えばよい。
---

# auq-web

ブラウザ上の質問画面を 1-shot で立ち上げ、ユーザの回答 (raw JSON) を受け取る。

## いつ使うか

AskUserQuestion (組み込みツール) は単純な選択肢列挙には素直だが、
**質問本文に表現力を持たせたい場面で詰まる**。auq-web はそこを埋める。

| 質問の性質 | 推奨ツール |
|---|---|
| 「TS と Python どっちで書く?」 のような 1 行問い | AskUserQuestion |
| 比較表 (`<table>`) を読まないと判断できない | **auq-web** |
| before / after のコードブロックを並べたい | **auq-web** |
| SVG / JS の簡易チャートを描いてから選ばせたい | **auq-web** |
| 段階的な背景説明 (h2, リスト) で前提を共有 | **auq-web** |
| 2〜4 件の質問を 1 画面で答えてほしい | **auq-web** |
| 答え方の優先順位 (rank) を聞きたい | **auq-web** |

迷ったら auq-web。

## 全体フロー

```
1. HTML 本文を組み立てる            (Claude が直接書く)
2. /tmp に書き出す                 (Write ツール)
3. server.py を background 起動    (Bash run_in_background: true)
   ↳ server が listen 後にブラウザを自動オープン (webbrowser.open)
4. background 完了通知を待つ        (server は 1-shot で自滅する)
5. BashOutput で stdout を読み, 末行 JSON を parse
6. answer をそのまま使う           (raw JSON, 要約しない)
```

`server.py` は **POST /answer を受けたら自分で graceful shutdown する**ため、
background プロセスの「完了通知 = ユーザが回答を出した瞬間」になる。
Monitor で polling する必要はない。

## ステップ詳細

### 1. HTML を組み立てる

入力フォーマットの全体像はこう (詳細は `references/input-format.md`):

```html
<script type="application/auq+json">
{ "$auq": "meta", "repo": "<repo 名>", "timeoutSec": 300 }
</script>

<script type="application/auq+json">
{
  "id": "q1",
  "title": "質問の見出し",
  "kind": "single",
  "options": [
    { "value": "a", "label": "選択肢 A", "hint": "短い補足" },
    { "value": "b", "label": "選択肢 B" }
  ],
  "allowOther": true
}
</script>

<p>ここに desc HTML を自由に書く。<table>, <pre><code>, <svg>, <script> なんでも。</p>
```

要点だけ:

- `<script type="application/auq+json">` のみが metadata 扱い。それ以外の
  `<script>` (`text/javascript` や `application/json`) は **desc にそのまま流れる**
  ので、SVG 描画用の JS や chart-data の埋め込みも自由
- 1 個目の auq script は省略可能な **meta** (`{ "$auq": "meta", ... }`)
- 2 個目以降が question (1〜4 件)
- 各 question script の **直後から次の auq script まで** が `descHtml`
- desc に `</script>` の文字列を含めたい時は **HTML エンティティ**
  (`&lt;/script&gt;`) で書く

#### desc は **素のタグだけ書けば dark theme に馴染む**

`server/index.html` 側に default stylesheet を持たせてあるので、書き手は
`<table>` `<pre><code>` `<blockquote>` `<ul>` `<h2>` `<svg>` などを
**素のまま書けばよい**。inline `style` 属性で配色や padding を毎回書く必要は無い。

```html
<!-- これで OK. 配色や枠線は default で当たる -->
<h2>判断材料</h2>
<table>
  <thead><tr><th>候補</th><th>所要</th></tr></thead>
  <tbody>
    <tr><td>Python</td><td>~50 行</td></tr>
    <tr><td>Bun</td><td>~20 行</td></tr>
  </tbody>
</table>
<blockquote>原則: 呼び出し側に install を強いない</blockquote>
<p class="warn">⚠ 既存タブを閉じてから再実行してください</p>
```

サポートしているタグ: `h1`-`h6` / `p` / `strong` / `em` / `small` / `mark` /
`a` / `ul` / `ol` / `li` / `blockquote` / `hr` / `code` / `pre` / `kbd` /
`table` / `thead` / `tbody` / `tr` / `th` / `td` / `img` / `figure` / `svg` /
`figcaption` / `details` / `summary`。

簡易 callout として `<p class="note">` `<p class="warn">` `<p class="danger">`
`<p class="ok">` が使える (色付きの left-border + 薄い背景)。

inline `style` 属性で上書きしたい時は通常の HTML として動くので、レイアウト
固有の調整 (列幅 `<col>` / 特定セルの `colspan` など) はそのまま書いて構わない。
**毎回フルで配色を書かない** が原則。

`kind` は 3 種類:

- `single`: ラジオ。`options[]` で `value`/`label`/`hint?`、`allowOther?`
- `multi`: チェックボックス。同上
- `rank`: ドラッグ並び替え。`items[]` で `id`/`label`/`hint?`

`options[].value` (single/multi) と `items[].id` (rank) は **answer payload に
そのまま出る識別子**。後で読んだ時に意味が分かるよう、`a` `b` `c` ではなく
**意味のある short snake_case** (`python` `bun` `server` `template` 等) で書く。

`label` / `hint` は UI に出る本文だが **plain text として扱われる**
(HTML タグはエスケープして表示される)。リッチに見せたいテキスト整形
(コードフォント・強調・改行) は desc 側に書くこと。

### 2. /tmp に書き出す

HTML は **ファイル経由を既定**にする。理由:

- Bash の heredoc + `run_in_background` の組合せは動くが、HTML 内に shell が
  解釈しうる文字 (バッククォート / `$` / 連続 quote / heredoc 終端と被るトークン)
  を入れた時の事故が一番多いカテゴリ。`Write` ツールに渡せばこの懸念ゼロ
- 大きい本文 (SVG や code-block を含む) でも素直

```
Write ツールで /tmp/auq-web-current.html に HTML を書く
```

固定 path を使う理由: port 7777 が固定で並行起動を許していないので、tmp ファイル
も並行衝突しない。short random を毎回考えなくていい上、デバッグ時も
`cat /tmp/auq-web-current.html` で「直近 Claude が組み立てた HTML」を再現できる。

短い (1 質問 + 数行 desc) かつ shell-safe と判断できれば heredoc も可:

```bash
~/.claude/skills/auq-web/run.sh --port 7777 <<'AUQ_EOF'
<script type="application/auq+json">{ "$auq": "meta" }</script>
<script type="application/auq+json">{ "id":"q1","kind":"single","title":"...","options":[...]}</script>
<p>...</p>
AUQ_EOF
```

迷ったらファイル経由。

#### 起動前 dry-run (任意, 推奨)

書いた HTML が parse を通るか / 各 question にどんな id・descLen が割り当たるか を
**サーバを起動せずに** 確認できる:

```bash
~/.claude/skills/auq-web/run.sh --validate --input /tmp/auq-web-<random>.html
# OK 例: {"ok": true, "meta": {...}, "questions": [{"id":"q1","kind":"single","descLen":312,"options":["a","b"]}, ...]}
# NG 例: {"ok": false, "error": "question[q1].options は 2 件以上の array である必要があります"}
```

exit 0 / 1 で成否が判定できる。`{"ok": true, ...}` の `descLen` が想定外に小さい・
0 になっていたら desc HTML が意図した question に紐づいていない。複雑な HTML
(複数質問 + SVG + 大きい比較表) を初めて書く時は **起動前に 1 回 validate して
から `Bash run_in_background` する** とイテレーションが速い。

### 3. server を background 起動

Bash ツールを **`run_in_background: true`** で呼ぶ:

```bash
~/.claude/skills/auq-web/run.sh \
  --port 7777 \
  --input /tmp/auq-web-<random>.html
```

(`run.sh` は同 repo 内の `../server/server.py` を symlink 越しに辿って起動する
薄い wrapper。引数はそのまま `server.py` に渡る)

戻り値の **shell ID を控えておくこと**。step 5 の `BashOutput` で使う。

`server.py` の挙動 (重要):

- 起動時に入力 HTML をパース → 検証 → render
- listen 開始後に `webbrowser.open(url)` を呼んで **ブラウザを自動オープン**
  (macOS: `open`, Linux: `xdg-open`, Windows: `start`)
- パース失敗時:
  - **`--input` 指定時**: server は起動して **ブラウザに 200 で赤いエラー画面**
    を返す。入力ファイルを修正してリロードすれば再 parse される (server 再起動不要)。
    stderr にも警告が出る。書き手が `--validate` を回し忘れた時の救済になる
  - **stdin 経由**: stderr に詳細を出して exit 1 (再読込不可能なため確定エラー)
- POST /answer を 1 度受けたら **JSON 1 行を stdout に書いて exit 0**
- port 7777 が衝突していたら詳細メッセージを stderr に出して exit 1

ブラウザの自動オープンを抑制したい場合 (CI / headless / `--static` 等) は
`--no-open` を付ける。`webbrowser.open` が失敗した場合 (リモート ssh セッション等)
は stderr に「⚠️ ブラウザを自動で開けませんでした。手動で {url} を開いて
ください。」と出るので、それをユーザに見せて URL をクリックしてもらう。

#### draft auto-save (server 側で動作)

server は `POST /api/draft` を受けて partial answer を保持する仕組みを持つ
(画面 JS が 800ms debounce で送る)。これにより **タブクラッシュ・誤って閉じる・
長考からの timeout で入力が消える** 事故を減らせる。

通常運用では呼び出し側で意識する必要は無い (画面 JS が自動で動く)。
クラッシュ復旧のために draft をファイルに永続化したい時は `--draft-out` を指定:

```bash
~/.claude/skills/auq-web/run.sh \
  --port 7777 \
  --input /tmp/auq-web-current.html \
  --draft-out /tmp/auq-draft.json   # atomic write される
```

`POST /answer` (確定回答) を受けた瞬間に draft はクリアされる。

#### スナップショット出力 (`--static <path>`)

server を起動せずに、render 済み HTML を 1 ファイル吐いて exit するモード。
回答 UI は disabled になる (閲覧専用):

```bash
~/.claude/skills/auq-web/run.sh \
  --static /tmp/auq-snapshot.html \
  --input /tmp/auq-web-current.html
```

用途: Slack / docbase に「こういう確認画面を出した」と貼る、
ふりかえりや archive 用に保存する、headless 環境からファイルとして渡す、など。
通常運用 (回答受け取り) には使わない。

ユーザへの案内 (1 行で良い):
**「ブラウザで質問画面を開きました。回答後、自動で閉じます」**

### 4. background 完了を待つ

`run_in_background: true` で起動した shell は、**プロセス exit 時に harness が
完了通知を送ってくれる**。Claude 側は polling 不要。

待っている間は、関連の作業 (ドキュメント整理 / 別ブランチ確認 / 次の段の準備等)
を進めてよい。ユーザは自分のペースでブラウザに向かって回答を組み立てている。

### 5. stdout から answer JSON を取る

完了通知を受けたら、控えておいた shell ID で `BashOutput` を読む。
**stdout の末尾 1 行が JSON** (server.py が `json.dumps(...) + "\n"` で 1 度だけ書く)。

`stderr` に "auq-web listening on http://..." 等のログが混ざるが、stdout には
JSON 1 行しか出ないので、stdout を strip して json.loads で読めばよい。

server が exit 1 で落ちた場合: stderr に詳細メッセージ (パースエラー /
port 衝突 等) が出ているので、それをユーザに見せる。

### 6. answer を使う

返ってくる JSON はこの形:

```json
{
  "event": "answer",
  "timedOut": false,
  "elapsedSec": 42,
  "answers": {
    "q1": { "kind": "single", "selected": "python", "comment": "" },
    "q2": { "kind": "multi",  "selected": ["a", "c"], "comment": "" },
    "q3": { "kind": "rank",   "ranking": ["server", "template"], "comment": "" }
  }
}
```

| `event` | 意味 |
|---|---|
| `"answer"` | 通常の回答。`timedOut: true` なら時間切れ + `partialAnswers` 同梱 |
| `"reject"` | ユーザが拒否ボタンで閉じた。`answers` は無し |

`allowOther: true` の question で Other が選ばれた時:

- single: `selected: "__other__"` + `otherText: "<入力>"`
- multi:  `selected` 配列に `"__other__"` を含み + `otherText: "<入力>"`

`comment` は各 question 共通の自由コメント欄 (常に存在、未入力なら空文字)。

**raw JSON のまま使うこと**。要約せずに `answers["q1"].selected` 等で直接参照
する方がループバックが速い。`event: "reject"` の時はユーザが「やめた」と
言っているので、続けて勝手に判断せず、どうするか改めて確認する。

## 失敗時の対処

| 症状 | 対処 |
|---|---|
| ブラウザで「❌ auq-web: input parse failed」の赤い画面 | 入力 HTML の parse 失敗。画面の `<pre>` に詳細あり。/tmp/auq-web-current.html を Edit で修正 → ブラウザでリロードで復帰 (server 再起動不要) |
| background プロセスが exit 1 で即落ち | stderr (BashOutput) を読む。port 衝突 / index.html 不在 / heredoc(stdin) 経路の parse 失敗 が候補 |
| port 7777 衝突メッセージ | 前の auq-web タブが残っている可能性大。「画面を閉じてから再実行してください」とユーザに伝える |
| ブラウザで真っ白 | server stderr に listening log は出ているか確認。出ているなら 200 でレンダー済み (HTML が空 desc で見えにくいだけ) |
| `event: "reject"` | 続行を勝手に判断せず、ユーザに改めて意図を確認する |

## ファイル配置

```
/Users/kumazaki/projects/auq-web/
├── server/server.py         ← 起動対象
├── skill/
│   ├── SKILL.md            ← この file
│   ├── run.sh              ← Bash から呼ぶ entry (server.py を resolve)
│   └── references/
│       └── input-format.md ← HTML 入力仕様の詳細
└── ...

~/.claude/skills/auq-web -> /Users/kumazaki/projects/auq-web/skill   (symlink)
```

セットアップ (1 度だけ):

```bash
ln -s /Users/kumazaki/projects/auq-web/skill ~/.claude/skills/auq-web
```

`server.py` は **stdlib のみ** で動くので追加 install 不要 (macOS 標準 Python3)。
