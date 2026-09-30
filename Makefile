.PHONY: dev test lint migrate messages ext-dev ext-deploy eval shell

dev:
	docker compose -f docker/compose.dev.yml up

test:
	uv run pytest -q --cov

lint:
	uv run ruff check .
	uv run ruff format --check .
	uv run mypy apps

migrate:
	uv run python manage.py migrate

messages:
	uv run python manage.py makemessages -l nl -l en -l de
	uv run python manage.py compilemessages

ext-dev:
	npx shopify app dev

ext-deploy:
	npx shopify app deploy

eval:
	uv run python scripts/eval_ai.py

shell:
	uv run python manage.py shell
