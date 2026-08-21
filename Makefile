.PHONY: test lint demo clean
test:  ; pytest tests -q
lint:  ; ruff check src tests topology experiments
demo:  ; @echo "Not yet implemented - see ST-5 (first working slice)." && exit 1
clean: ; mn -c >/dev/null 2>&1 || true; find . -name __pycache__ -type d -exec rm -rf {} +
