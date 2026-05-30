# Gov Job LINE Bot

LINE 聊天機器人，讓使用者設定訂閱條件（工作地點、人員類別、職缺關鍵字），查詢時即時爬取台灣[行政院人事行政總處事求人](https://web3.dgpa.gov.tw/want03front/AP/WANTF00001.ASPX)的政府職缺並回覆。

**無 LLM、無向量搜尋**，純靠 DGPA 表單篩選 + 模板格式化，架構輕量。

---

## 功能

- 📍 依地點、人員類別、職缺關鍵字設定訂閱條件
- 🔍 傳任何訊息即可即時查詢符合條件的最新職缺
- 📱 訊息格式針對手機版 LINE 優化

### LINE 操作指令

| 輸入 | 動作 |
|------|------|
| `訂閱` | 開始設定查詢條件（Quick Reply 引導） |
| `我的訂閱` | 查看目前訂閱設定 |
| `刪除訂閱` | 清除所有條件 |
| `說明` | 顯示使用說明 |
| 其他任何訊息 | 以訂閱條件查詢最新職缺 |

---

## 技術棧

| 類別 | 選擇 |
|------|------|
| Web Framework | FastAPI |
| 爬蟲 | requests + BeautifulSoup4 + lxml |
| 資料庫（正式） | Neon PostgreSQL（免費，永不過期） |
| 資料庫（本機） | SQLite（自動 fallback） |
| LINE SDK | line-bot-sdk v3 |
| 部署 | Render（免費方案） |

---

## 本機開發

### 1. 安裝依賴

```bash
pip install -r requirements.txt
```

### 2. 設定環境變數

```bash
cp .env.example .env
# 填入 LINE_CHANNEL_ACCESS_TOKEN 和 LINE_CHANNEL_SECRET
# DATABASE_URL 不填則自動使用本機 SQLite
```

### 3. 啟動伺服器

```bash
uvicorn app.main:app --reload
```

### 4. 測試爬蟲

```bash
python scripts/test_crawl.py
```

---

## 部署到 Render + Neon PostgreSQL

### 步驟一：建立 Neon PostgreSQL（免費，永不過期）

1. 前往 [neon.tech](https://neon.tech) → 免費註冊
2. 建立新 Project（選台灣最近的 region，建議 `ap-southeast-1`）
3. 進入 Dashboard → **Connection Details**
4. 複製 **Connection String**（格式如下）：
   ```
   postgresql://user:password@ep-xxx.ap-southeast-1.aws.neon.tech/neondb?sslmode=require
   ```

### 步驟二：部署到 Render

1. 前往 [render.com](https://render.com) → 免費註冊
2. New → **Web Service** → Connect GitHub → 選 `gov-job-linebot`
3. 設定：
   - **Runtime**：Python 3
   - **Build Command**：`pip install -r requirements.txt`
   - **Start Command**：`uvicorn app.main:app --host 0.0.0.0 --port $PORT`
4. **Environment Variables**（在 Environment 分頁設定）：

   | Key | Value |
   |-----|-------|
   | `LINE_CHANNEL_ACCESS_TOKEN` | 你的 LINE token |
   | `LINE_CHANNEL_SECRET` | 你的 LINE secret |
   | `DATABASE_URL` | Neon 連線字串 |

5. 點 **Deploy** → 等待部署完成
6. 記下 Render 提供的網址（例如 `https://gov-job-linebot.onrender.com`）

---

## 設定 LINE Bot Webhook

### 前置：取得 LINE 憑證

1. 前往 [LINE Developers Console](https://developers.line.biz/)
2. 選擇或建立一個 **Provider**
3. 建立 **Messaging API** Channel
4. **Basic Settings** 分頁 → 複製 **Channel Secret** → 填入 `LINE_CHANNEL_SECRET`
5. **Messaging API** 分頁 → **Channel access token** → Issue → 複製 → 填入 `LINE_CHANNEL_ACCESS_TOKEN`

### 設定 Webhook

1. **Messaging API** 分頁 → **Webhook settings**
2. **Webhook URL** 填入：
   ```
   https://your-render-domain.onrender.com/webhook
   ```
3. 點 **Update** → 點 **Verify**（應顯示 Success）
4. 開啟 **Use webhook** 開關

### 關閉自動回覆（避免衝突）

1. **Messaging API** 分頁 → **LINE Official Account features**
2. **Auto-reply messages** → 點 **Edit** → 關閉
3. **Greeting messages** → 關閉（可選）

---

## 爬蟲說明

目標網站為 ASP.NET WebForms，需攜帶 `__VIEWSTATE` 跨頁 POST 分頁。

- **列表頁**：每頁 15 筆，依 `MAX_CRAWL_PAGES` 限制頁數
- **詳細頁**：包含工作說明、應徵條件、聯絡方式（僅測試腳本使用，LINE 查詢只顯示摘要以加快回應）
- **篩選**：工作地點（`drpWORK_PLACE`）、人員區分（`drpPERSON_KIND`）、職缺名稱（`txtTITLE`）
- **資料窗口**：查詢最近 30 天的職缺

---

## 健康檢查

```bash
curl https://your-render-domain.onrender.com/health
# → {"status": "ok", "subscription_count": 3}
```
