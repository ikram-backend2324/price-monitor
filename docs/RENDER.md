# Demo deployment on Render.com (free)

A one-click demo for your portfolio: everything runs in **one free Render web service** plus free Postgres and free Key Value (Redis).

## What runs where

| Render resource | Plan | Contents |
|---|---|---|
| `pricewatch-demo` (web, Docker, `Dockerfile.render`) | Free, 512 MB | Gunicorn (Django) + Celery worker with embedded Beat (threads) + demo shop on loopback + Telegram bot (only if a token is set) |
| `pricewatch-db` | Free Postgres | Database |
| `pricewatch-redis` | Free Key Value | Celery broker, cache, locks, rate limit |

Tested locally with a 512 MB memory limit: ~250 MB used, every check succeeded, alerts generated.

## Deploy (about 10 minutes)

1. Push the repository to GitHub (private is fine):
   ```bash
   git remote add origin https://github.com/<you>/price-monitor.git
   git push -u origin main
   ```
2. Sign up at https://render.com (log in with GitHub).
3. **New → Blueprint** → connect GitHub → choose `price-monitor` → Render reads `render.yaml` → **Apply**.
4. Optional values Render asks for (leave empty to skip):
   - `DJANGO_SUPERUSER_EMAIL`, `DJANGO_SUPERUSER_PASSWORD`: your private admin account for `/admin/`
   - `TELEGRAM_BOT_TOKEN`, `TELEGRAM_BOT_USERNAME`, `ADMIN_TELEGRAM_CHAT_ID`: see `docs/DATA.md`
   - `SENTRY_DSN`
5. Wait for the first build (5–10 min). Open `https://pricewatch-demo.onrender.com` (Render shows the exact URL) and log in as **demo@pricewatch.local / demo12345**.

Every `git push` to `main` redeploys automatically.

## Free-tier limitations

| Limitation | Effect | Workaround |
|---|---|---|
| Service sleeps after 15 min without visits | First visit takes ~1 min; price checks pause while asleep (they resume on wake) | Open the site a couple of minutes before a showing; or upgrade the web service to Starter ($7/mo) |
| Free Postgres expires after 30 days | Data is deleted | Recreate the database (Blueprint re-sync) or upgrade to a paid database |
| 512 MB RAM | No Playwright/Chromium → **no Uzum scraping** on Render | Show Uzum in the full Docker stack; demo-shop data works fully |
| Demo login is public | Visitors can edit demo data | Set `DEMO_RESET_ON_START=1` → fresh demo data on every restart/deploy |
| Telegram bot sleeps with the service | Bot doesn't answer while the service sleeps | Paid plan, or show the bot from the local Docker stack |

## Useful settings (Render → service → Environment)

- `DEMO_SHOP_CHANGE_INTERVAL`: how often demo prices change (seconds, default 120)
- `CELERY_CONCURRENCY`: Celery threads (default 4; lower to 2 if you see out-of-memory restarts)
- `DEMO_RESET_ON_START=1`: recreate demo data on every start

Logs: Render dashboard → `pricewatch-demo` → **Logs**.
