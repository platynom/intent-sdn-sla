.PHONY: test lint demo clean
test:  ; pytest tests -q
lint:  ; ruff check src tests topology experiments
demo:  ; bash experiments/scenarios/s1_single_intent.sh
clean: ; mn -c >/dev/null 2>&1 || true; find . -name __pycache__ -type d -exec rm -rf {} +
