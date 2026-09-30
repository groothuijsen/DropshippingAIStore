# 11 — Ops and deployment (Proxmox)

## 1. Machines

| VM/LXC | Services | Minimum | Note |
| --- | --- | --- | --- |
| `app-01` | Caddy (TLS, reverse proxy), Gunicorn/Uvicorn (`web`) | 4 vCPU, 8 GB | only port 443 open via Cloudflare Tunnel |
| `worker-01` | Celery workers: `ai` (concurrency 8), `shopify` (4), `default` (4), `low` (2); Celery beat (1 instance!) | 4 vCPU, 8 GB | beat on only one machine |
| `db-01` | PostgreSQL 16, Redis 7 (AOF on) | 4 vCPU, 16 GB, SSD | not publicly reachable |
| `ops-01` | Uptime Kuma, GlitchTip, Grafana + Loki + Promtail | 2 vCPU, 4 GB | |
| `staging-01` | everything in one Docker Compose | 4 vCPU, 8 GB | linked to dev store |

## 2. Docker

- One image for `web`, `worker` and `beat` (`docker/Dockerfile`), different command.
- `compose.prod.yml` per VM with only the services of that VM; configuration via `.env` on the VM (not in Git).
- Healthchecks: `web` → `GET /healthz` (DB + Redis reachable); `worker` → `celery inspect ping`.
- Migrations: separate one-off container `migrate` before restarting `web`; migrations always backward compatible (add field first, remove only later).

## 3. CI/CD (GitHub Actions)

1. On every PR: `make lint`, `make test`, Function tests (`npm test` in `extensions/bundle-discount`).
2. Merge to `main`: build image, tag with commit SHA, push to own registry.
3. Deploy staging automatically; production manually (workflow_dispatch) on Tue–Thu 09:00–11:00 CET (SOP-2).
4. Extensions: `npx shopify app deploy --version <sha>` only in the production workflow, after a successful staging test.

## 4. Backups and recovery

- Proxmox Backup Server: daily snapshots of all VMs, retained 14 days.
- `pg_dump` every hour (retain 48) and daily (retain 30), encrypted (age) to external storage outside the data center.
- Quarterly: restore test on `staging-01`, result in `docs/ops-log.md`.

## 5. Monitoring and alerts

| Signal | Threshold | Channel |
| --- | --- | --- |
| `/healthz` down | 2 min | Telegram + email |
| Webhook endpoint 5xx | > 1% in 10 min | Telegram |
| Celery queue `ai` length | > 50 for 10 min | Telegram |
| Jobs `failed` | > 10% per hour | email |
| Avg. AI cost per store (24 h) | > `AI_COST_ALERT_USD_PER_STORE` | email |
| Reconcile billing (08 §5) | any discrepancy | email |
| C2PA signing certificate | expires < 30 days | email |

## 6. Security

- Secrets only in `.env` on the VMs (permissions 600) or a secrets manager; never in images.
- `FERNET_KEYS` rotation: add new key at the front, run beat task `core.tasks.reencrypt_tokens`, remove old key after 7 days.
- Django: `SECURE_PROXY_SSL_HEADER`, `SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE`, `CSRF_TRUSTED_ORIGINS` with the app domain. Admin views use session tokens, not Django sessions.
- `pip-audit` / `uv audit` weekly in CI.
- Django admin (`/admin/`) only reachable via Cloudflare Access (IP/identity), never public.
