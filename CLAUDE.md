# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## ⚡ 強制規則（每次都必須遵守）

**完成任何程式碼修改後，必須自動執行 git commit + git push 到 GitHub。**
- 不需要使用者提醒，修改完就 commit + push
- commit message 用繁體中文或英文描述本次修改內容
- 格式：`git commit -m "類型(範圍): 說明"`
- push 指令：`git push origin main`

## 專案說明（v3.1）

LINE + Telegram 聊天機器人，讓使用者設定工作地點（多選）、官等類別（多選）、職系、職務列等區間、關鍵字等訂閱條件。
後端每日定時爬取台灣行政院人事行政總處事求人（`web3.dgpa.gov.tw`）的政府職缺（含詳細頁），
儲存至 Neon PostgreSQL 的 `jobs` 資料表。查詢時直接從 DB 搜尋，速度快且資料完整。
**無 LLM、無向量搜尋**，搜尋用 pg_trgm 模糊比對 + 多關鍵字 similarity 排序。

## 常用指令

```bash
# 安裝依賴
pip install -r requirements.txt

# 本機啟動（支援熱重載）
uvicorn app.main:app --reload

# 煙霧測試爬蟲（含詳細頁）
python scripts/test_crawl.py
MAX_CRAWL_PAGES=1 python scripts/test_crawl.py

# 健康檢查（回傳訂閱人數 + 職缺筆數）
curl http://localhost:8000/health

# 手動觸發排程爬取（需設定 CRAWL_SECRET）
curl -X POST http://localhost:8000/admin/trigger-crawl \
  -H "X-Crawl-Secret: your_secret"
```

## 環境設定

複製 `.env.example` 為 `.env` 並填入：
- `LINE_CHANNEL_ACCESS_TOKEN` 和 `LINE_CHANNEL_SECRET` — LINE webhook 必填
- `DATABASE_URL` — Neon PostgreSQL 連線字串（`postgresql://...?sslmode=require`）；**未設定則自動 fallback 到本機 SQLite**
- `TELEGRAM_BOT_TOKEN` — Telegram @BotFather 取得（可選）
- `CRAWL_SECRET` — 保護 `/admin/trigger-crawl` 端點的 secret key（建議設定）
- `MAX_CRAWL_PAGES` — 即時查詢最多爬幾頁（本機建議 `1`，正式 `3`）
- `MAX_CRAWL_PAGES_SCHEDULED` — 排程爬取頁數（`0` = 不限，抓全部）
- `CRAWL_DETAIL_DELAY` — 詳細頁爬取間隔秒數（預設 `0.3`）
- `TOP_K_RESULTS` — 回傳給使用者的最大職缺數（預設 `5`）

資料目錄 `data/sqlite/` 啟動時自動建立（SQLite 模式）。

## 架構（v3.1）

```
前端 (LINE / Telegram)
    ↓ webhook
FastAPI (/webhook, /telegram-webhook)
    ├── 訂閱設定流程（Quick Reply / InlineKeyboard，7步驟）→ subscription 表
    └── 查詢請求 → query_service
                        ↓ SQL 搜尋 + pg_trgm similarity
                   jobs 表（Neon PostgreSQL）
                        ↓ 格式化 → 回覆

背景排程（APScheduler, 每日 02:00 台灣時間）
    → scraper（is_office=True，列表頁 + 詳細頁）
    → jobs 表 UPSERT → delete_expired_jobs()
    
外部 Cron（cron-job.org）
    → POST /admin/trigger-crawl
    → 確保 Render free tier 也能觸發排程
```

**查詢流程：**
1. 訊息到達 `POST /webhook` 或 `/telegram-webhook` → service 處理
2. 非設定指令 → `query_service.handle_user_query(platform, user_id)`
3. 從 `subscription` 表讀取訂閱條件
4. `search_jobs()` 從 `jobs` 表搜尋（若表空 → fallback 即時爬取）
5. 格式化前 K 筆結果 → LINE 純文字 / Telegram HTML 超連結

**訂閱設定流程（7步驟）：**
1. 使用者輸入「訂閱」觸發
2. 工作地點（多選）→ 官等類別（多選）→ 職系大分類 → 職系細項（可略過）→ 職務列等區間（可略過）→ 關鍵字（可略過）
3. 儲存至 `subscription` 表（platform + platform_user_id 為複合唯一鍵）

## 關鍵實作細節

**爬蟲（`app/crawler/scraper.py`）：** ASP.NET WebForms，每次分頁帶 `__VIEWSTATE` POST。
- 排程爬取固定 `is_office=True`（須具公務人員任用資格職缺）
- 列表頁 md_hides 欄位順序：**職系**（index 0）→ **官等/列等**（index 1）→ 地點（2）→ 截止日（3）
- 截止日格式：民國年 "115/05/30~115/06/08"，`_parse_deadline_range()` 轉為 ISO start+end
- `_parse_rank_grades()` 從官等文字提取最低/最高職等（0=無法解析）
- `_derive_rank_type_codes()` 推算官等代碼（1=簡任,2=薦任,3=委任,4=其他）
- `fetch_detail=True` 時：每筆抓詳細頁，間隔 `CRAWL_DETAIL_DELAY` 秒

**表單選項（`app/crawler/form_options.py`）：** 快取工作地點、人員區分、職系（sysnam）選單。
- `get_sysnam_names_for_grp('A')` 回傳所有行政類職系名稱（供 DB search IN 子句）
- `code_to_sysnam_grp('A101')` → `'A'`（職系代碼 → 大分類）
- `SYSNAM_GRP_OPTIONS` 硬編碼：`[{不限}, {A=行政類}, {B=技術類}]`

**資料庫（`app/db/database.py`）：** 雙後端設計：
- `DATABASE_URL` 未設定 → SQLite（`data/sqlite/jobs.db`）
- `DATABASE_URL` 已設定 → Neon PostgreSQL（psycopg2）
- `_run()` 自動將 `?` 佔位符轉為 `%s`（psycopg2 格式）
- init_db() 執行 ALTER TABLE migration（ADD COLUMN IF NOT EXISTS）自動補充新欄位
- `search_jobs()` 支援：多地點 IN、官等代碼 LIKE、職等範圍、職系 IN、多關鍵字 OR + pg_trgm 排序

**訂閱模型（`app/models/subscription.py`）：** `platform`（'line'/'telegram'）+ `platform_user_id` 識別。
欄位：`work_place_codes/names`（逗號分隔）、`rank_types`（逗號分隔）、`rank_grade_min/max`、`sysnam_grp/name`、`sysnam_names`、`keywords`。

**jobs 模型（`app/models/job.py`）：** 所有日期 YYYY-MM-DD。
欄位：`rank_type_codes`（逗號分隔推算代碼）、`rank_grade_min/max`、`deadline_start/end`、`search_text`（全文搜尋）。

**對話狀態：** 以 module-level dict `_conv` 維護每位使用者的對話步驟。Server restart 後清除，可接受。
- LINE：`setup_location` → `setup_rank_types` → `setup_sysnam_grp` → `setup_sysnam_names` → `setup_rank_grade` → `setup_keywords`
- Telegram：同樣六步驟，使用 InlineKeyboard 多選（✅/☐ toggle）

**handle_user_query() 回傳值：** `tuple[str, str]` = `(message_text, parse_mode)`
- LINE：parse_mode=''（純文字 URL）
- Telegram：parse_mode='HTML'（`<a href="url">職缺網址</a>`）

**排程器（`app/scheduler/crawl_scheduler.py`）：** APScheduler AsyncIOScheduler，每日 02:00 台灣時間。
固定 `is_office=True`，整批 upsert 完成後呼叫一次 `delete_expired_jobs()`。

## 已確定的技術決策（勿重新提議）

| 決策 | 原因 |
|---|---|
| 無 LLM | 使用者明確選擇不接付費 API |
| 無向量搜尋（pgvector）| pg_trgm 對現有結構化訂閱條件已足夠 |
| SQLite 不用 ORM | 結構簡單，直接 sqlite3 足夠 |
| 每日排程爬取（非即時） | 儲存完整詳細頁資料，查詢速度快 |
| 外部 cron 觸發（cron-job.org）| 解決 Render free tier spin down 問題 |
| IS_OFFICE 寫死 True | 只爬公務人員任用資格職缺 |
| 關鍵字不傳給爬蟲 | 只用於 DB 模糊比對，避免限制全量爬取 |

## 爬蟲 DGPA 表單欄位（已驗證 2026-06）

```
drpWORK_PLACE           工作地點（動態取得）
drpPERSON_KIND          人員區分（動態取得）
drpSYSNAM_grp           職系大分類：'' / 'A'（行政）/ 'B'（技術）
drpSYSNAM               職系細項（空字串 = 全部）
chkTYPE1~4              官等 checkbox：簡任/薦任/委任/其他
IS_OFFICE               職缺類別：須具公務員資格（排程爬取固定送 on）
txtTITLE                職稱關鍵字（排程爬取不送）
txbORG_NAME             機關名稱關鍵字（排程爬取不送）
DATE_FROM / DATE_TO     民國年格式 YYYMMDD
```

詳細頁 element ID：`PLTITLE`、`PLORG_NAME`、`PLRANK`、`PLSYSNAM`、
`PLWORK_ITEM`、`PLWORK_QUALITY`、`PLWORK_ADDRESS`、`PLDATE_FROM_TO`

## 部署（Render + Neon）

使用 `render.yaml`：
- Build command：`pip install -r requirements.txt`
- Start command：`uvicorn app.main:app --host 0.0.0.0 --port $PORT`
- Healthcheck：`/health`

**必要環境變數（Render Dashboard 手動設定）：**
`LINE_CHANNEL_ACCESS_TOKEN`、`LINE_CHANNEL_SECRET`、`DATABASE_URL`（Neon）、`CRAWL_SECRET`

**cron-job.org 設定：**
每日 18:00 UTC（= 台灣 02:00）打 POST 到 `https://<render-url>/admin/trigger-crawl`，
Header：`X-Crawl-Secret: <CRAWL_SECRET 值>`

**Neon 舊欄位清理（v3.1 升級後手動執行）：**
```sql
-- subscription 表
ALTER TABLE subscription DROP COLUMN IF EXISTS work_place_code;
ALTER TABLE subscription DROP COLUMN IF EXISTS work_place_name;
ALTER TABLE subscription DROP COLUMN IF EXISTS person_kind_code;
ALTER TABLE subscription DROP COLUMN IF EXISTS person_kind_name;
ALTER TABLE subscription DROP COLUMN IF EXISTS title_keyword;
ALTER TABLE subscription DROP COLUMN IF EXISTS org_keyword;

-- jobs 表
ALTER TABLE jobs DROP COLUMN IF EXISTS deadline;
ALTER TABLE jobs DROP COLUMN IF EXISTS deadline_end_iso;
ALTER TABLE jobs DROP COLUMN IF EXISTS person_kind;
ALTER TABLE jobs DROP COLUMN IF EXISTS person_kind_code;
ALTER TABLE jobs DROP COLUMN IF EXISTS apply_method;
ALTER TABLE jobs DROP COLUMN IF EXISTS contact_method;
```
