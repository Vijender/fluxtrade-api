# FluxTrade Python backend

FastAPI spread scanner with **Postgres** tables:


| Table            | Purpose                                                                                |
| ---------------- | -------------------------------------------------------------------------------------- |
| **users**        | Accounts (email, password hash, SMTP settings, alert dedupe signatures).               |
| **watchlist**    | Symbols per user (order preserved). **Alert batch** scans these symbols.               |
| **strategies**   | Saved strategy templates (`name`, `strategy_type`, `option_type`, `params` JSON).      |
| **trades**       | Saved trade ideas (`ticker`, `title`, `idea` JSON — e.g. a scanner row snapshot).      |
| **alerts**       | Each batch run: scanned tickers, TRADE rows, new TRADE rows (retained 2–5 days).       |
| **scan_results** | Optional shared cache for full-symbol scan payloads (`ticker` + `mode`, `expires_at`). |


Run with `**PYTHONPATH`** = repo root. `create_all` on startup creates missing tables.

## Auth

`POST /api/auth/register` and `POST /api/auth/login` return a JWT with **`sub`** (user id) and **`email`**. Protected routes require `Authorization: Bearer …` and match email to the `users` row.

## User API (prefix `/api`)

- **Watchlist:** `GET` / `PUT /user/watchlist` — `{ "symbols": ["AAPL", …] }`
- **Strategies:** `GET` / `POST /user/strategies`; `PATCH` / `DELETE /user/strategies/{id}`
- **Saved trades:** `GET` / `POST /user/trades`; `PATCH` / `DELETE /user/trades/{id}` — body includes `idea` (object)
- **Alerts:** `GET /user/alerts?limit=50`
- **Profile / SMTP:** `GET /user/me`, `POST` / `DELETE /user/smtp`

## Scan cache (optional)

Set `FLUXTRADE_SCAN_CACHE_ENABLED=1` and optional `FLUXTRADE_SCAN_CACHE_TTL_SECONDS` (default 900). Expired rows are removed when `purge_expired_storage()` runs (startup + each alert batch).

## Health

`GET /health` — database, JWT, alert retention, scan cache, and `https_redirect_enforced`.

## HTTPS / security headers

- **Security headers** on every response: `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, `Permissions-Policy`, `Cross-Origin-Opener-Policy`, and **HSTS** when the request is HTTPS (`X-Forwarded-Proto: https` or `https` scheme).
- **HTTP → HTTPS redirect** when `RENDER=true` (Render) or `FLUXTRADE_ENFORCE_HTTPS=1`. Use **uvicorn** with `--proxy-headers --forwarded-allow-ips='*'` so the app sees TLS correctly behind a proxy. If you get redirect loops, set `FLUXTRADE_DISABLE_HTTPS_REDIRECT=1`.
- Optional **`FLUXTRADE_HSTS_MAX_AGE`** (seconds, default 31536000).

Local `./backend/start_backend.sh` already passes `--proxy-headers`.

## GitLab

**Host the repo on GitLab** (GitLab.com or self-managed):

```bash
cd /path/to/fluxtrade-api
git remote add gitlab https://gitlab.com/YOUR_GROUP/fluxtrade-api.git
# or SSH: git@gitlab.com:YOUR_GROUP/fluxtrade-api.git
git push -u gitlab main
```

**CI/CD:** the repo root file `.gitlab-ci.yml` runs a **test** job on every branch and merge request: installs `backend/requirements.txt` and verifies `backend.api.main` imports. Open **Build → Pipelines** after you push.

**Deploy the API:** GitLab CI does not run your FastAPI server by itself. Typical setup:

1. Keep hosting the app on **Render**, **Fly.io**, **Google Cloud Run**, a **VPS**, or **GitLab’s Kubernetes agent** / **GitLab Docker executor** with a container.
2. Optional: add a **Render deploy hook** (or similar), store `RENDER_DEPLOY_HOOK_URL` under **Settings → CI/CD → Variables**, then uncomment the `deploy:render` job in `.gitlab-ci.yml` so each push to `main` triggers a redeploy.

**GitLab environment variables** (for review apps or future deploy jobs) mirror Render: `DATABASE_URL`, `FLUXTRADE_JWT_SECRET`, etc.

## Render

Link Postgres, set `DATABASE_URL`, `FLUXTRADE_JWT_SECRET`, and use:

```bash
PYTHONPATH=$PWD uvicorn backend.api.main:app --host 0.0.0.0 --port $PORT --proxy-headers --forwarded-allow-ips='*'
```

**Note:** If you previously used `fluxtrade_*` table names, create new tables or migrate data into `users`, `watchlist`, `strategies`, `trades`, `alerts`, `scan_results`.