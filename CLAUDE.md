# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## ⚡ 強制規則（每次都必須遵守）

**完成任何程式碼修改後，必須自動執行 git commit + git push 到 GitHub。**
- 不需要使用者提醒，修改完就 commit + push
- commit message 用繁體中文或英文描述本次修改內容
- 格式：`git commit -m "類型(範圍): 說明"`
- push 指令：`git push origin main`

## 專案說明（v3.3）

LINE + Telegram 聊天機器人，讓使用者設定工作地點（多選）、官等類別（多選）、職系、職務列等區間、關鍵字等訂閱條件。
爬蟲透過 **proxynova.com 動態 proxy** 在 **Render Cron Job** 每天台灣凌晨 4 點自動執行，爬取台灣行政院人事行政總處事求人（`web3.dgpa.gov.tw`）的政府職缺（含詳細頁），
儲存至 Neon PostgreSQL 的 `jobs` 資料表。查詢時直接從 DB 搜尋，速度快且資料完整。
**無 LLM、無向量搜尋**，搜尋用 pg_trgm 模糊比對 + 多關鍵字 similarity 排序。

## 常用指令

```bash
# 安裝依賴
pip install -r requirements.txt

# 本機啟動（支援熱重載）
uvicorn app.main:app --reload

# 正式爬蟲（含 proxy + 存 DB）
python scripts/run_crawl.py --proxy                          # Render 用（透過 proxy）
MAX_CRAWL_PAGES_SCHEDULED=1 python scripts/run_crawl.py --proxy  # 只爬 1 頁（測試）

# 本機手動執行（直接連線，無 proxy）
python scripts/run_crawl.py
MAX_CRAWL_PAGES_SCHEDULED=1 python scripts/run_crawl.py  # 只爬 1 頁（本機）

# 煙霧測試爬蟲（不存 DB，確認爬蟲邏輯）
python scripts/test_crawl.py
MAX_CRAWL_PAGES=1 python scripts/test_crawl.py

# 設定 LINE Rich Menu（一次性，本機執行）
python scripts/setup_line_menu.py

# 健康檢查（回傳訂閱人數 + 職缺筆數）
curl http://localhost:8000/health
```

## 環境設定

複製 `.env.example` 為 `.env` 並填入：
- `LINE_CHANNEL_ACCESS_TOKEN` 和 `LINE_CHANNEL_SECRET` — LINE webhook 必填
- `DATABASE_URL` — Neon PostgreSQL 連線字串（`postgresql://...?sslmode=require`）；**未設定則自動 fallback 到本機 SQLite**
- `TELEGRAM_BOT_TOKEN` — Telegram @BotFather 取得（可選）
- `TELEGRAM_WEBHOOK_SECRET` — Telegram webhook 簽章驗證用，設定後需重新部署（建議設定）
- `MAX_CRAWL_PAGES` — 爬蟲每次最多爬幾頁（本機建議 `1`，正式 `0` = 全部）
- `MAX_CRAWL_PAGES_SCHEDULED` — 同上（供 config 讀取，預設 `0` = 全部）
- `CRAWL_DETAIL_DELAY` — 詳細頁爬取間隔秒數（預設 `0.3`）
- `TOP_K_RESULTS` — 回傳給使用者的最大職缺數（預設 `10`）

資料目錄 `data/sqlite/` 啟動時自動建立（SQLite 模式）。

## 架構（v3.3）

```
前端 (LINE / Telegram)
    ↓ webhook
FastAPI (Render)
    ├── /webhook            LINE 訊息 → line_service
    ├── /telegram-webhook   Telegram 訊息 → telegram_service（含簽章驗證）
    ├── /detail             職缺查詢網頁（RWD，篩選/排序/分頁）
    └── /api/jobs           JSON 職缺資料（供 /detail 頁載入）
         ↓
    query_service
         ↓ SQL 搜尋 + pg_trgm similarity
    jobs 表（Neon PostgreSQL）
         ↓ 格式化 → 回覆

爬蟲（Render Cron Job，每天台灣凌晨 4 點）
    python scripts/run_crawl.py
    → proxy_manager（proxynova.com 抓台灣 proxy → 測試 → 選第一個可用）
    → scraper（proxy 連線，列表頁 + 詳細頁並行爬取）
    → jobs 表 UPSERT → delete_expired_jobs()
    （無可用 proxy → exit(1)，可本機手動補跑）
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

**Proxy 管理（`app/crawler/proxy_manager.py`）：** DGPA 僅允許台灣 IP，Render 美國 IP 需透過 proxy。
- `get_working_proxy()` → 爬 proxynova.com 台灣 proxy 清單 → 依序測試 → 回傳第一個可用 dict
- proxy 測試：GET DGPA 首頁，確認回應含 `__VIEWSTATE`（確認為真實 DGPA 頁面）
- 無可用 proxy → 回傳 None → run_crawl.py exit(1)，Render log 可見

**爬蟲（`app/crawler/scraper.py`）：** ASP.NET WebForms，每次分頁帶 `__VIEWSTATE` POST。
- `crawl_jobs(proxy_dict=None, ...)` → `_new_session(proxy_dict)` → 設定 `session.proxies`
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

**Rich Menu（`scripts/setup_line_menu.py`）：** 一次性腳本，本機執行。
Pillow 生成 2500×843 PNG（深藍底 + 5 個藍色按鈕），透過 api-data.line.me 上傳，設為所有使用者預設選單。

## 已確定的技術決策（勿重新提議）

| 決策 | 原因 |
|---|---|
| 無 LLM | 使用者明確選擇不接付費 API |
| 無向量搜尋（pgvector）| pg_trgm 對現有結構化訂閱條件已足夠 |
| SQLite 不用 ORM | 結構簡單，直接 sqlite3 足夠 |
| 爬蟲本機手動執行（非 Render） | Render free tier 資源受限，本機爬取更穩定 |
| IS_OFFICE 寫死 True | 只爬公務人員任用資格職缺 |
| 關鍵字不傳給爬蟲 | 只用於 DB 模糊比對，避免限制全量爬取 |
| LINE Rich Menu（Pillow 生成） | 無需外部圖片服務，本機一次性執行即可 |

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

使用 `render.yaml`（兩個服務）：
- **Web Service**：`uvicorn app.main:app`（LINE/Telegram webhook + /detail 頁面）
- **Cron Job**（`gov-job-crawler`）：`python scripts/run_crawl.py`，每天 20:00 UTC（台灣凌晨 4 點）

**Web Service 必要環境變數（Render Dashboard 手動設定）：**
`LINE_CHANNEL_ACCESS_TOKEN`、`LINE_CHANNEL_SECRET`、`DATABASE_URL`（Neon）

**Cron Job 必要環境變數：**
`DATABASE_URL`（同 Neon 連線字串，在 gov-job-crawler 服務單獨設定）

**建議設定：**
`TELEGRAM_BOT_TOKEN`、`TELEGRAM_WEBHOOK_SECRET`（隨機字串，部署後自動 set_webhook）
