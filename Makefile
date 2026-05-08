.PHONY: serve serve-watch validate test

PORT  ?= 7777
INPUT ?= server/samples/s41_single_question.html

# auq-web server を起動。submit/reject で自滅するので one-shot。
# port は `make serve PORT=8080`、入力は `make serve INPUT=path/to.html` で上書き可能。
serve:
	@python3 server/server.py --port $(PORT) --input $(INPUT)

# 編集 → ブラウザリロードで即反映する dev mode。
# parse 失敗は exit せず 200 でエラー画面を返すので、書きながら直せる。
serve-watch:
	@python3 server/server.py --port $(PORT) --input $(INPUT) --watch

# サーバ起動せず parse 結果を JSON で stdout に出す dry-run。
# OK 例: {"ok": true, "questions": [...]}  / NG 例: {"ok": false, "error": "..."}
validate:
	@python3 server/server.py --validate --input $(INPUT)

# parser / wire / samples の unittest を実行
test:
	@cd server && python3 -m unittest discover -v
