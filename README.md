# Taiwan Government Job Bot

> Automated civil-service job alerts on **LINE** and **Telegram** — powered by a custom web crawler that reverse-engineers a legacy ASP.NET government portal, with a shared 6-step subscription engine across both messaging platforms.

![Python](https://img.shields.io/badge/Python-3.12-blue)
![FastAPI](https://img.shields.io/badge/FastAPI-0.110-green)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-pg__trgm-336791)
![LINE](https://img.shields.io/badge/LINE-Bot%20SDK%20v3-00C300)
![Telegram](https://img.shields.io/badge/Telegram-Bot%20v20-2CA5E0)
![Railway](https://img.shields.io/badge/Deployed-Railway-0B0D0E)

---

## Portfolio Highlights

### 🕷️ Web Scraping — Reverse-Engineering a Legacy ASP.NET Portal

The target site ([DGPA job board](https://web3.dgpa.gov.tw)) provides no public API and is built on ASP.NET WebForms — a stateful framework that embeds a large `__VIEWSTATE` blob in every HTML response. Every page navigation and filter requires a POST request that carries that exact blob back to the server.

| Challenge | Engineering Solution |
|---|---|
| Session state held in `__VIEWSTATE` hidden field | Parse every HTML response with BeautifulSoup; extract all `<input type="hidden">` fields and replay them verbatim in the next POST |
| Pagination is a POST (not a link GET) | Detect "next page" by presence of `__doPostBack`; reconstruct POST payload with `__EVENTTARGET = btnNEXT` and fresh VIEWSTATE |
| Detail pages needed for full job data | `ThreadPoolExecutor` with 8 workers — concurrent detail-page fetching without separate sessions |
| Portal geo-blocks non-Taiwan IPs (Render runs in the US) | Dynamic proxy pool: scrape [proxynova.com](https://proxynova.com/proxy-server-list/country-tw/) for Taiwan proxies, then validate each by confirming the response contains a real `__VIEWSTATE` — not just an HTTP 200 from a proxy error page |
| Cloud IPv6 routing failure | Force `AF_INET` globally via `urllib3.util.connection.allowed_gai_family` |
| Transient failures on a live government site | `urllib3.util.retry.Retry(total=3, backoff_factor=2)` — exponential backoff on 429/5xx |
| Date format is ROC calendar (民國年) | Custom parser converts `115/06/03` → `2026-06-03` (ISO 8601) |

**Scale:** ~2,900 job postings per full run; ~120 detail pages fetched concurrently; scheduled daily at 04:00 Taiwan time via Railway Cron Job.

---

### 🤖 Chatbot — One Subscription Flow, Two Platforms

Designed a single 6-step guided subscription flow and implemented it on both LINE and Telegram using each platform's native interactive widgets. Shared business logic lives in `query_service` and the `Subscription` model; only the UI layer is platform-specific.

| Feature | LINE | Telegram |
|---|---|---|
| Multi-select input | Quick Reply buttons, paginated (9 items/page + prev/next) | InlineKeyboard with ✅ / ☐ toggle and pagination |
| Webhook security | HMAC-SHA256 signature (`X-Line-Signature`) | `X-Telegram-Bot-Api-Secret-Token` via `hmac.compare_digest` |
| Custom menu | Pillow-generated 2500 × 843 PNG uploaded to `api-data.line.me` | Telegram `/` command list |
| Response format | Plain-text URLs | HTML `<a href>` anchor tags (`parse_mode="HTML"`) |
| Free-text steps | Quick Reply "skip" button | InlineKeyboard skip button |

**Subscription parameters:** work location (multi-select), rank category (簡/薦/委/其他, multi-select), job series, grade range (e.g. `5-9`), free-text keywords.

---

### 🗄️ Backend — Production-Grade Search, Zero LLM Cost

- **Full-text search via `pg_trgm`**: GIN index on a pre-built `search_text` column; multi-keyword OR scoring using `similarity()` across `title`, `org_name`, `qualifications`, and `work_items`; results ranked by relevance then deadline
- **Dual-backend**: Neon PostgreSQL in production; SQLite auto-fallback for local development — zero extra setup required
- **Smart UPSERT**: `ON CONFLICT(job_id) DO UPDATE` with `CASE`-based field preservation — never overwrites a rich detail-page field with an empty value from a list-page crawl
- **No LLM, no embeddings**: structured subscriptions + fuzzy matching deliver precise, fast results with no inference cost

---

## Architecture

```
User (LINE / Telegram)
       │ webhook (signature validated)
       ▼
  FastAPI — Railway Web Service
  ├── POST /webhook            LINE messages  → line_service
  ├── POST /telegram-webhook   Telegram msgs  → telegram_service
  ├── GET  /detail             RWD job search page (filter / sort / paginate)
  └── GET  /api/jobs           JSON feed (up to 5,000 jobs)
                │
          query_service
                │ SQL + pg_trgm similarity scoring
          jobs table (Neon PostgreSQL)

Railway Cron Job — daily 04:00 Taiwan (UTC 20:00)
  python scripts/run_crawl.py --proxy
  ├── proxy_manager   scrape proxynova.com → validate → pick first working proxy
  ├── scraper         VIEWSTATE POST pagination + 8-worker concurrent detail fetch
  ├── upsert_jobs     deduplicate by job_id + smart ON CONFLICT UPSERT
  └── delete_expired_jobs()
```

---

## Tech Stack

| Layer | Technology |
|---|---|
| API Framework | FastAPI · uvicorn (async lifespan) |
| Database (production) | Neon PostgreSQL · `pg_trgm` similarity · `psycopg2` |
| Database (local dev) | SQLite (auto-fallback, zero config) |
| LINE Bot | `line-bot-sdk` v3 · Quick Reply · Pillow Rich Menu |
| Telegram Bot | `python-telegram-bot` v20 · InlineKeyboard · Webhook |
| Web Scraper | `requests` · `BeautifulSoup4` / `lxml` · `ThreadPoolExecutor` |
| Proxy Management | `proxynova.com` scraping · VIEWSTATE-based proxy validation |
| Deployment | Railway (Web Service + Cron Job) · `railway.toml` |
| Logging | `loguru` (structured, colorized, ISO timestamps) |

---

## Quick Start

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
# Fill in required values (see Environment Variables below)
# Leave DATABASE_URL blank to use local SQLite automatically
```

### 3. Start the server

```bash
uvicorn app.main:app --reload
# → http://localhost:8000/detail   (job search page)
# → http://localhost:8000/health   (health check)
```

### 4. Run a smoke test

```bash
MAX_CRAWL_PAGES=1 python scripts/test_crawl.py   # crawl 1 page, no DB write
```

---

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `LINE_CHANNEL_ACCESS_TOKEN` | LINE | LINE Messaging API long-lived token |
| `LINE_CHANNEL_SECRET` | LINE | LINE Channel Secret (webhook signature) |
| `DATABASE_URL` | Production | Neon PostgreSQL connection string (`postgresql://...?sslmode=require`); omit for SQLite |
| `TELEGRAM_BOT_TOKEN` | Telegram | Token from [@BotFather](https://t.me/BotFather) |
| `TELEGRAM_WEBHOOK_SECRET` | Recommended | Random string for `X-Telegram-Bot-Api-Secret-Token` validation |
| `MAX_CRAWL_PAGES` | Optional | Max pages for on-demand crawl (default `3`; `0` = all) |
| `MAX_CRAWL_PAGES_SCHEDULED` | Optional | Max pages for cron crawl (default `0` = all) |
| `CRAWL_DETAIL_DELAY` | Optional | Seconds between detail-page requests (default `0.3`) |
| `TOP_K_RESULTS` | Optional | Max results returned to users (default `10`) |

---

## API Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Status · subscriber count · job count |
| `GET` | `/detail` | Interactive job search page (RWD, filter/sort/paginate) |
| `GET` | `/api/jobs` | JSON array of all active job postings (max 5,000) |
| `POST` | `/webhook` | LINE webhook (HMAC-SHA256 validated) |
| `POST` | `/telegram-webhook` | Telegram webhook (Secret-Token validated) |

---

## Chatbot Features

### 6-Step Subscription Flow

| Step | Field | Input method |
|---|---|---|
| 1 | Work location | Multi-select (paginated) |
| 2 | Rank category | Multi-select (簡任 / 薦任 / 委任 / 其他) |
| 3 | Job series group | Single select (行政類 / 技術類 / unlimited) |
| 4 | Job series (sub) | Multi-select (paginated); skippable |
| 5 | Grade range | Free text e.g. `5-9`; skippable |
| 6 | Keywords | Free text (comma-separated); skippable |

After setup, any message triggers a fresh search matching the stored subscription.
Ad-hoc keyword messages override the saved keyword for that query only.

### LINE Commands

| Command / Text | Action |
|---|---|
| `/subscribe` · `訂閱` | Start subscription setup |
| `/results` · `最新職缺` | Query jobs using saved subscription |
| `/mysubscription` · `我的訂閱` | View current subscription |
| `/deletesubscription` · `刪除訂閱` | Clear subscription |
| `/help` · `說明` | Help message |
| Any other text | Use as keyword override for one query |

LINE Rich Menu (5 buttons) is configured once via `python scripts/setup_line_menu.py`.

### Telegram Commands

`/start` · `/subscribe` · `/results` · `/mysubscription` · `/deletesubscription` · `/help`

---

## Crawler Usage

### Automated (Railway Cron Job)

Runs daily at **04:00 Taiwan time** (UTC 20:00) via Railway Dashboard Cron Job:

```
python scripts/run_crawl.py --proxy
```

View logs: Railway Dashboard → Cron Job service → Deployments.

### Manual Run (local machine, direct connection)

```bash
python scripts/run_crawl.py                              # full crawl
MAX_CRAWL_PAGES_SCHEDULED=1 python scripts/run_crawl.py  # 1-page test
```

### Smoke Test (no DB write)

```bash
python scripts/test_crawl.py
MAX_CRAWL_PAGES=1 python scripts/test_crawl.py
```

---

## Deployment (Railway + Neon)

### 1. Create Neon PostgreSQL

Sign up at [neon.tech](https://neon.tech) → Create Project → copy the connection string (`postgresql://...?sslmode=require`).

### 2. Deploy Web Service to Railway

New Project → **Deploy from GitHub repo** → select this repo. Railway auto-detects `railway.toml`.

Set environment variables in Railway Dashboard:

| Variable | Value |
|---|---|
| `LINE_CHANNEL_ACCESS_TOKEN` | From LINE Developers Console |
| `LINE_CHANNEL_SECRET` | From LINE Developers Console |
| `DATABASE_URL` | Neon connection string |
| `TELEGRAM_BOT_TOKEN` | From [@BotFather](https://t.me/BotFather) |
| `TELEGRAM_WEBHOOK_SECRET` | Any random string |

`RAILWAY_PUBLIC_DOMAIN` is injected automatically — no need to set it.

### 3. Create Cron Job (same repo)

Railway Dashboard → **New Service** → **GitHub Repo** (same repo) → configure:

| Field | Value |
|---|---|
| Service type | Cron Job |
| Start command | `python scripts/run_crawl.py --proxy` |
| Schedule | `0 20 * * *` (UTC 20:00 = Taiwan 04:00) |
| `DATABASE_URL` | Same Neon connection string |
| `MAX_CRAWL_PAGES_SCHEDULED` | `0` (crawl all pages) |

### 4. Configure LINE Webhook

LINE Developers Console → Messaging API → Webhook URL: `https://<railway-domain>/webhook` → Verify → enable **Use webhook**.

### 5. Telegram Webhook (auto-configured)

The app calls `set_webhook` automatically on startup. No manual step needed after deploying with `TELEGRAM_BOT_TOKEN` set.

### 6. LINE Rich Menu (one-time)

```bash
python scripts/setup_line_menu.py   # run locally with LINE token in .env
```
