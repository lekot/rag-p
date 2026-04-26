.PHONY: dev lint typecheck test helm-lint clean

dev:
	tilt up

lint:
	uv run ruff format --check apps/api
	uv run ruff check apps/api
	pnpm lint

typecheck:
	uv run mypy apps/api/src
	pnpm typecheck

test:
	uv run pytest apps/api
	pnpm test

helm-lint:
	helm lint charts/rag-p

clean:
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type d -name .pytest_cache -exec rm -rf {} +
	find . -type d -name .mypy_cache -exec rm -rf {} +
	find . -type d -name .ruff_cache -exec rm -rf {} +
	find . -type d -name node_modules -exec rm -rf {} +
	find . -type d -name .next -exec rm -rf {} +
