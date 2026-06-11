#!/usr/bin/env python3
"""
一次性設定 LINE Rich Menu（下方固定選單）。
在本機執行一次即可：

    python scripts/setup_line_menu.py

前置條件：
- pip install Pillow requests python-dotenv
- .env 檔案含 LINE_CHANNEL_ACCESS_TOKEN，或事先 export 環境變數
"""
import io
import os
import sys
from pathlib import Path

import requests

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    print("❌ 缺少 Pillow，請先執行：pip install Pillow")
    sys.exit(1)

# ── 載入 .env ────────────────────────────────────────────────────────────────
_env = Path(__file__).parent.parent / ".env"
if _env.exists():
    for _line in _env.read_text(encoding="utf-8").splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            k, v = _line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
if not ACCESS_TOKEN:
    print("❌ 請設定 LINE_CHANNEL_ACCESS_TOKEN 環境變數或填入 .env")
    sys.exit(1)

# ── 選單按鈕定義 ──────────────────────────────────────────────────────────────
BUTTONS = [
    ("訂閱設定", "/subscribe"),
    ("查詢職缺", "/results"),
    ("我的訂閱", "/mysubscription"),
    ("刪除訂閱", "/deletesubscription"),
    ("說明",     "/help"),
]

# ── API helpers ───────────────────────────────────────────────────────────────
_HEADERS  = {"Authorization": f"Bearer {ACCESS_TOKEN}"}
_API      = "https://api.line.me/v2/bot"
_API_DATA = "https://api-data.line.me/v2/bot"


def _get(path: str) -> dict:
    r = requests.get(f"{_API}{path}", headers=_HEADERS, timeout=10)
    r.raise_for_status()
    return r.json()


def _post(path: str, *, base=_API, json_body=None, raw_data=None, ct="application/json") -> dict:
    h = {**_HEADERS, "Content-Type": ct}
    r = requests.post(f"{base}{path}", headers=h,
                      json=json_body, data=raw_data, timeout=30)
    r.raise_for_status()
    return r.json() if r.content else {}


def _delete(path: str) -> None:
    requests.delete(f"{_API}{path}", headers=_HEADERS, timeout=10).raise_for_status()


# ── 圖片生成 ──────────────────────────────────────────────────────────────────
def _load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """嘗試載入系統中文字型。"""
    candidates = [
        "/System/Library/Fonts/PingFang.ttc",                          # macOS
        "/System/Library/Fonts/STHeiti Light.ttc",                     # macOS (older)
        "/System/Library/Fonts/Supplemental/Songti.ttc",               # macOS
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",      # Debian/Ubuntu
        "/usr/share/fonts/truetype/noto/NotoSansCJKsc-Regular.otf",
        "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/google-noto-cjk/NotoSansCJK-Regular.ttc",
    ]
    for path in candidates:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    print(f"  ⚠ 找不到中文字型，使用預設字型（文字可能顯示為方塊）")
    return ImageFont.load_default()


def generate_menu_image() -> bytes:
    """產生 2500×843 Rich Menu 圖片。"""
    W, H = 2500, 843
    N    = len(BUTTONS)
    BW   = W // N   # 每個按鈕寬度 = 500

    NAVY  = (30,  58, 138)    # #1e3a8a
    BLUE  = (37,  99, 235)    # #2563eb
    SEP   = (30,  64, 175)    # #1e40af
    WHITE = (255, 255, 255)
    HINT  = (186, 214, 251)   # 淡藍（command text）

    img  = Image.new("RGB", (W, H), color=NAVY)
    draw = ImageDraw.Draw(img)

    font_main = _load_font(100)
    font_sub  = _load_font(52)

    for i, (label, cmd) in enumerate(BUTTONS):
        x0 = i * BW
        x1 = x0 + BW
        cx = x0 + BW // 2

        # 按鈕背景（帶 inset padding）
        pad = 12
        draw.rounded_rectangle([x0 + pad, pad, x1 - pad, H - pad],
                                radius=20, fill=BLUE)

        # 分隔線
        if i > 0:
            draw.line([(x0, 0), (x0, H)], fill=SEP, width=4)

        # 主要標籤（中文）
        draw.text((cx, H // 2 - 55), label, fill=WHITE, font=font_main, anchor="mm")

        # 指令提示（英文小字）
        draw.text((cx, H // 2 + 95), cmd, fill=HINT, font=font_sub, anchor="mm")

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


# ── 主程式 ────────────────────────────────────────────────────────────────────
def setup() -> None:
    print("📋 設定 LINE Rich Menu…\n")

    # 1. 刪除現有 rich menu
    existing = _get("/richmenu/list").get("richmenus", [])
    for rm in existing:
        _delete(f"/richmenu/{rm['richMenuId']}")
        print(f"  🗑  刪除舊選單：{rm['richMenuId']}")

    # 2. 建立 rich menu 結構
    bw = 2500 // len(BUTTONS)
    menu_def = {
        "size":        {"width": 2500, "height": 843},
        "selected":    True,
        "name":        "gov-job-linebot",
        "chatBarText": "功能選單 ▲",
        "areas": [
            {
                "bounds": {"x": i * bw, "y": 0, "width": bw, "height": 843},
                "action": {"type": "message", "text": cmd},
            }
            for i, (_, cmd) in enumerate(BUTTONS)
        ],
    }
    res     = _post("/richmenu", json_body=menu_def)
    menu_id = res["richMenuId"]
    print(f"  ✅ 建立選單：{menu_id}")

    # 3. 上傳圖片（需走 api-data.line.me）
    image_bytes = generate_menu_image()
    print(f"  🖼  上傳圖片（{len(image_bytes)//1024} KB）…")
    _post(
        f"/richmenu/{menu_id}/content",
        base=_API_DATA,
        raw_data=image_bytes,
        ct="image/png",
    )
    print("  ✅ 圖片上傳完成")

    # 4. 設為所有使用者預設
    _post(f"/user/all/richmenu/{menu_id}")
    print("  ✅ 設為所有使用者預設選單")

    print(f"\n🎉 完成！重新開啟 LINE 聊天室即可看到下方選單。")
    print(f"   選單 ID：{menu_id}")


if __name__ == "__main__":
    setup()
