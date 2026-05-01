.PHONY: serve test

PORT  ?= 7777
INPUT ?= server/samples/s41_single_question.html

# auq-web server を起動。submit/reject で自滅するので one-shot。
# port は `make serve PORT=8080`、入力は `make serve INPUT=path/to.html` で上書き可能。
serve:
	@python3 server/server.py --port $(PORT) --input $(INPUT)

# parser / wire / samples の unittest を実行
test:
	@cd server && python3 -m unittest discover -v
