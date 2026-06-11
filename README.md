# Gov Job LINE Bot

LINE + Telegram 聊天機器人，讓使用者設定訂閱條件查詢台灣政府職缺。

**設計理念：無 LLM、無向量搜尋。** 結構化訂閱條件 × pg_trgm 精確 SQL 搜尋，架構輕量、回應快速、維運成本趨近於零。

---

## 技術亮點

| 面向 | 選擇 |
|------|------|
| Web Framework | FastAPI（lifespan、async、BackgroundTasks） |
| 資料庫（正式） | Neon PostgreSQL + **pg_trgm** 模糊搜尋 + similarity 排序 |
| 資料庫（本機） | SQLite（自動 fallback，零設定開發） |
| 爬蟲 | ASP.NET WebForms `__VIEWSTATE` POST 分頁 + ThreadPoolExecutor 並行抓詳細頁 |
| LINE | line-bot-sdk v3・Quick Reply 分頁多選・**Rich Menu**（Pillow 生成圖片） |
| Telegram | python-telegram-bot v20・InlineKeyboard 多選・Webhook 簽章驗證 |
| 搜尋 | 多地點 IN、官等代碼 LIKE、職等範圍、職系 IN、多關鍵字 OR + similarity 排序 |
| 查詢 UI | `/detail` 靜態頁面：RWD 卡片/表格、多欄篩選、分頁、排序（桌機+手機） |
| 部署 | Render（免費 Web Service） + Neon PostgreSQL（免費） |

---

## 架構

```
使用者（LINE / Telegram）
    ↓ Webhook
FastAPI（Render）
    ├── /webhook        LINE 訊息 → line_service
    ├── /telegram-webhook  Telegram 訊息 → telegram_service
    ├── /detail         職缺查詢網頁（HTML + JS）
    └── /api/jobs       JSON 職缺資料（供 /detail 頁載入）
         ↓
    query_service
         ↓ SQL 搜尋 + pg_trgm similarity
    jobs 表（Neon PostgreSQL）

爬蟲（本機手動執行）
    python scripts/test_crawl.py
         ↓ UPSERT
    jobs 表 → delete_expired_jobs()
```

---

## 快速開始

### 1. 安裝依賴

```bash
pip install -r requirements.txt
```

### 2. 設定環境變數

```bash
cp .env.example .env
# 填入必要值（見下方環境變數說明）
# DATABASE_URL 不填則自動使用本機 SQLite
```

### 3. 啟動伺服器

```bash
uvicorn app.main:app --reload
# → http://localhost:8000/detail  （職缺查詢網頁）
# → http://localhost:8000/health  （健康檢查）
```

### 4. 測試爬蟲

```bash
python scripts/test_crawl.py
MAX_CRAWL_PAGES=1 python scripts/test_crawl.py   # 只爬 1 頁（快速煙霧測試）
```

---

## 環境變數

| 變數 | 必填 | 說明 |
|------|------|------|
| `LINE_CHANNEL_ACCESS_TOKEN` | LINE 必填 | LINE Messaging API 長期 Token |
| `LINE_CHANNEL_SECRET` | LINE 必填 | LINE Channel Secret |
| `DATABASE_URL` | 正式必填 | Neon PostgreSQL 連線字串（含 `?sslmode=require`） |
| `TELEGRAM_BOT_TOKEN` | Telegram 可選 | @BotFather 取得 |
| `TELEGRAM_WEBHOOK_SECRET` | 建議設定 | Telegram webhook 簽章驗證用，設定後需重新部署 |
| `MAX_CRAWL_PAGES` | 可選 | 本機查詢最多爬幾頁，預設 `3` |
| `MAX_CRAWL_PAGES_SCHEDULED` | 可選 | 爬蟲完整執行頁數，`0` = 全部，預設 `0` |
| `CRAWL_DETAIL_DELAY` | 可選 | 詳細頁爬取間隔秒數，預設 `0.3` |
| `TOP_K_RESULTS` | 可選 | 回傳給使用者的最大職缺數，預設 `10` |

---

## API 端點

| 端點 | 說明 |
|------|------|
| `GET /health` | 健康檢查（回傳訂閱人數 + 職缺筆數） |
| `GET /detail` | 職缺查詢網頁（篩選 / 排序 / 分頁） |
| `GET /api/jobs` | JSON 職缺資料（最多 5000 筆） |
| `POST /webhook` | LINE Webhook（含 HMAC 簽章驗證） |
| `POST /telegram-webhook` | Telegram Webhook（可選 Secret Token 驗證） |

---

## LINE / Telegram 功能

### 訂閱設定流程（6 步驟）

| 步驟 | LINE | Telegram |
|------|------|----------|
| 1. 工作地點 | Quick Reply 分頁多選（9 選項/頁 + 翻頁） | InlineKeyboard 分頁多選 |
| 2. 官等類別 | Quick Reply 多選（簡/薦/委/其他） | InlineKeyboard 多選 |
| 3. 職系大分類 | Quick Reply 單選 | InlineKeyboard 單選 |
| 4. 職系細項 | Quick Reply 分頁多選 | InlineKeyboard 分頁多選 |
| 5. 職等範圍 | 文字輸入（如 `5-9`） | 文字輸入（可略過） |
| 6. 關鍵字 | 文字輸入（可略過） | 文字輸入（可略過） |

### LINE 指令

| 指令 | 動作 |
|------|------|
| `/subscribe` 或 `訂閱` | 設定訂閱條件 |
| `/results` 或 `最新職缺` | 依訂閱條件查詢職缺 |
| `/mysubscription` 或 `我的訂閱` | 查看目前設定 |
| `/deletesubscription` 或 `刪除訂閱` | 清除訂閱 |
| `/help` 或 `說明` | 使用說明 |
| 其他任何文字 | 以輸入文字為關鍵字查詢 |

### LINE Rich Menu

執行一次 `python scripts/setup_line_menu.py` 即可設定下方固定選單（5 個按鈕）。

---

## 爬蟲使用（本機手動執行）

```bash
# 完整爬取（含詳細頁）
python scripts/test_crawl.py

# 限制 1 頁（煙霧測試）
MAX_CRAWL_PAGES=1 python scripts/test_crawl.py
```

爬取結果 UPSERT 到 jobs 表，並自動刪除截止日過期的職缺。

---

## 部署（Render + Neon）

### 1. 建立 Neon PostgreSQL

1. 前往 [neon.tech](https://neon.tech) 免費註冊
2. 建立 Project → 複製 Connection String（`postgresql://...?sslmode=require`）

### 2. 部署到 Render

1. New → **Web Service** → Connect GitHub → 選此 repo
2. Build Command：`pip install -r requirements.txt`
3. Start Command：`uvicorn app.main:app --host 0.0.0.0 --port $PORT`
4. Environment Variables：

   | 變數 | 值 |
   |------|----|
   | `LINE_CHANNEL_ACCESS_TOKEN` | LINE token |
   | `LINE_CHANNEL_SECRET` | LINE secret |
   | `DATABASE_URL` | Neon 連線字串 |
   | `TELEGRAM_BOT_TOKEN` | Telegram token（可選） |
   | `TELEGRAM_WEBHOOK_SECRET` | 自訂隨機字串（建議設定） |

### 3. 設定 LINE Webhook

Messaging API → Webhook URL：`https://<render-url>/webhook` → Verify → 開啟 Use webhook

### 4. 設定 Telegram Webhook

```bash
curl "https://api.telegram.org/bot<TOKEN>/setWebhook?url=https://<render-url>/telegram-webhook&secret_token=<TELEGRAM_WEBHOOK_SECRET>"
```

（部署後 app 啟動時會自動呼叫 set_webhook，無需手動設定）
