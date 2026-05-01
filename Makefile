.PHONY: serve

PORT ?= 7777

# auq-web mock server を起動。submit/reject で自滅するので one-shot。
# port は `make serve PORT=8080` で上書き可能。
serve:
	@python3 server/server.py --port $(PORT)
