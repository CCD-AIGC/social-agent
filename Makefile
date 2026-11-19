.PHONY: install test lint doctor web

install:
	uv sync --extra dev

test:
	uv run pytest

lint:
	uv run python -m compileall -q src tests

doctor:
	uv run social-agent doctor

web:
	uv run social-agent-web --host 127.0.0.1 --port 8798
