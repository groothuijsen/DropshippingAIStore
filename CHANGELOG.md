# Changelog

Format: one line per ticket, newest at the top. `[T-###] short description`.

## Unreleased

## v0.2.0 (2026-09-30)
- [T-002] Session token validation (middleware, bounce page) + token exchange with `expiring=1` + refresh with Redis lock + `keep_tokens_fresh` beat task + `Shop`/`AuditLog` models + Fernet encryption. 20/20 tests passing.

## v0.1.0 (2026-09-30)
- [T-001] Repo scaffold: Django 5.2, uv, 12 apps, Docker Compose dev/prod, Makefile, ruff/mypy/pytest, CI workflow, healthcheck `/healthz`.
