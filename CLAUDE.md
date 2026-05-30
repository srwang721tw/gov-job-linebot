# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 專案說明

LINE 聊天機器人，讓使用者設定工作地點、人員類別、職缺關鍵字等訂閱條件，查詢時即時爬取台灣行政院人事行政總處事求人（`web3.dgpa.gov.tw`）的政府職缺並回覆結果。**無 LLM、無向量搜尋**，純靠 DGPA 表單篩選 + 模板格式化回覆。

## 常用指令

```bash
# 安裝依賴
pip install -r requirements.txt

# 本機啟動（支援熱重載）
uvicorn app.main:app --reload

# 煙霧測試爬蟲（列表頁 + 關鍵字搜尋 + 詳細頁解析）
python scripts/test_crawl.py
MAX_CRAWL_PAGES=1 python scripts/test_crawl.py

# 健康檢查（回傳訂閱人數）
curl http://localhost:8000/health
```

## 環境設定

複製 `.env.example` 為 `.env` 並填入：
- `LINE_CHANNEL_ACCESS_TOKEN` 和 `LINE_CHANNEL_SECRET` — LINE webhook 必填
- `DATABASE_URL` — Neon PostgreSQL 連線字串（`postgresql://...?sslmode=require`）；**未設定則自動 fallback 到本機 SQLite**
- `MAX_CRAWL_PAGES` — 每次查詢最多爬幾頁（15筆/頁），本機測試建議設 `1`，正式建議 `3`
- `TOP_K_RESULTS` — 回傳給使用者的最大職缺數（預設 5）

資料目錄 `data/sqlite/` 啟動時自動建立（SQLite 模式）。

## 架構

```
LINE 使用者 → /webhook → line_service（對話狀態機）
                              ├── 訂閱設定流程（Quick Reply 選單）→ database
                              └── 查詢觸發 → query_service → scraper → DGPA 網站
                                                                ↓
                                                         格式化後回覆
```

**查詢流程：**
1. LINE 訊息到達 `POST /webhook` → `line_service.handle_message`
2. 非訂閱設定指令 → `query_service.handle_user_query`
3. 讀取使用者訂閱條件（DB）→ 即時呼叫 `crawl_jobs()`
4. 格式化前 K 筆結果為純文字 → LINE reply

**訂閱設定流程（多步驟對話）：**
1. 使用者輸入「訂閱」觸發
2. Quick Reply 選工作地點 → 選人員類別 → 輸入關鍵字（可略過）
3. 儲存至 DB，對話狀態清除

## 關鍵實作細節

**爬蟲（`app/crawler/scraper.py`）：** 目標網站是 ASP.NET WebForms，每次分頁需帶著 `__VIEWSTATE` 跨頁 POST。日期使用民國年格式（YYYMMDD，YYY = 西元 − 1911）。查詢視窗固定為 30 天。只抓列表頁資料（職稱、機關、地點、截止日、連結），不抓詳細頁，以加快即時回應速度。`fetch_job_detail()` 函式存在但僅供測試腳本使用，正式查詢不呼叫。

**表單選項（`app/crawler/form_options.py`）：** 啟動後首次呼叫時從 DGPA 網站動態抓取下拉選單選項（工作地點、人員區分），快取於 module-level 全域變數。供訂閱設定的 Quick Reply 使用。

**資料庫（`app/db/database.py`）：** 雙後端設計：
- `DATABASE_URL` 未設定 → SQLite（`data/sqlite/subscriptions.db`）
- `DATABASE_URL` 已設定 → Neon PostgreSQL（psycopg2）
- `_run()` 自動將 SQLite 的 `?` 佔位符轉換為 psycopg2 的 `%s`
- 只儲存訂閱條件，不儲存職缺資料。`UPSERT ON CONFLICT(line_user_id)` 更新現有訂閱。

**訂閱模型（`app/models/subscription.py`）：** 欄位包含 `work_place_code/name`、`person_kind_code/name`、`title_keyword`（職缺名稱關鍵字）、`org_keyword`（機關名稱關鍵字）。

**對話狀態（`app/services/line_service.py`）：** 以 module-level dict `_conv` 維護每位使用者的對話步驟（`setup_location` → `setup_person_kind` → `setup_keyword`）。Quick Reply 每頁最多 11 個選項（`_PAGE_SIZE = 11`），超過時加入「下一頁▶」/「◀上一頁」翻頁按鈕（LINE 上限 13，保留 2 個給翻頁）。Server restart 後狀態清除，可接受。

**`app/utils/config.py`：** 所有路徑與環境變數的單一來源。`BASE_DIR` 從 config 檔案位置推導，無論工作目錄為何都能正確解析路徑。

## 已確定的技術決策（勿重新提議）

| 決策 | 原因 |
|---|---|
| 無 LLM | 使用者明確選擇不接付費 API |
| 無向量搜尋 / ChromaDB | 改用 DGPA 表單篩選，已移除 |
| 無 APScheduler | 改為使用者觸發即時爬取，不需排程 |
| SQLite 不用 ORM | 結構簡單，直接 sqlite3 足夠 |
| 只抓列表頁 | 省略詳細頁以加快即時回應速度 |

## 爬蟲關鍵參數

```
drpSYSNAM = ""          # 空字串 = 全部職系（"0100" 只抓無職系，是舊 Bug）
drpWORK_PLACE           # 下拉選單值，從 form_options.py 動態取得
drpPERSON_KIND          # 下拉選單值，從 form_options.py 動態取得
DATE_FROM / DATE_TO     # 民國年格式，例如 "1150526"
```

## 部署（Render）

使用 `render.yaml`：
- Build command：`pip install -r requirements.txt`
- Start command：`uvicorn app.main:app --host 0.0.0.0 --port $PORT`
- Healthcheck：`/health`

**資料持久化選項：**
1. **Neon PostgreSQL（建議）：** 在 Render Dashboard 設定 `DATABASE_URL` 環境變數，免費方案可用，restart 後資料保留。
2. **Render Disk（選用，付費）：** 取消 `render.yaml` 中 disk 的注解（`/opt/render/project/src/data`，$0.25/GB/月），保留 SQLite 資料。
3. **不持久化：** 免費方案 filesystem 於 restart 後清空，SQLite 訂閱資料會消失，使用者需重新設定。
