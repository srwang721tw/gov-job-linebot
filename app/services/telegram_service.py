"""
Telegram Bot 服務（v3）。
與 LINE bot 共用 query_service、database、form_options 層。

訂閱設定流程：InlineKeyboard 引導（地點 → 人員類別 → 職系大分類 → 關鍵字）
查詢觸發：任何文字訊息 → handle_user_query(platform='telegram', ...)
"""
import re
from typing import Optional

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

from app.crawler.form_options import SYSNAM_GRP_OPTIONS, get_form_options
from app.db.database import delete_subscription, get_subscription, save_subscription
from app.models.subscription import Subscription
from app.services.query_service import handle_user_query
from app.utils.config import TELEGRAM_BOT_TOKEN
from app.utils.logger import logger

# ── 全域 Application 實例 ─────────────────────────────────────────────────────
_tg_app: Optional[Application] = None

# ── 對話狀態 ─────────────────────────────────────────────────────────────────
_conv: dict[int, dict] = {}

# Inline keyboard 每頁顯示幾個選項、每行幾個
_PAGE_SIZE    = 8
_ITEMS_PER_ROW = 2

# ── callback_data 前綴 ────────────────────────────────────────────────────────
# LC:CODE  → 選擇地點
# LP:N     → 地點翻頁到第 N 頁
# PC:CODE  → 選擇人員類別
# PP:N     → 人員類別翻頁
# SC:GRP   → 選擇職系大分類（GRP: '_'=不限, 'A', 'B'）
# SKIP     → 略過關鍵字


# ── 工具函式 ──────────────────────────────────────────────────────────────────

def _clean_name(name: str) -> str:
    """去除地點代碼前綴：'10-臺北市' → '臺北市'"""
    m = re.match(r"^\d{1,3}-(.+)$", name)
    return m.group(1) if m else name


def _location_options() -> list[dict]:
    return [
        {"value": o["value"], "text": _clean_name(o["text"])}
        for o in get_form_options().get("work_place", [])
        if not o["value"].endswith("00")  # 過濾分組標題
    ]


def _person_kind_options() -> list[dict]:
    return list(get_form_options().get("person_kind", []))


def _encode_val(v: str) -> str:
    return v if v else "_"


def _decode_val(v: str) -> str:
    return "" if v == "_" else v


def _build_kb(
    options: list[dict],
    page: int,
    sel_prefix: str,
    page_prefix: str,
) -> InlineKeyboardMarkup:
    start = page * _PAGE_SIZE
    end   = min(start + _PAGE_SIZE, len(options))
    chunk = options[start:end]

    rows = []
    for i in range(0, len(chunk), _ITEMS_PER_ROW):
        rows.append([
            InlineKeyboardButton(
                text=o["text"],
                callback_data=f"{sel_prefix}:{_encode_val(o['value'])}",
            )
            for o in chunk[i:i + _ITEMS_PER_ROW]
        ])

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("◀ 上一頁", callback_data=f"{page_prefix}:{page - 1}"))
    if end < len(options):
        nav.append(InlineKeyboardButton("下一頁 ▶", callback_data=f"{page_prefix}:{page + 1}"))
    if nav:
        rows.append(nav)

    return InlineKeyboardMarkup(rows)


# ── 訂閱設定步驟 ──────────────────────────────────────────────────────────────

async def _ask_location(user_id: int, chat_id: int, bot) -> None:
    opts = [{"value": "", "text": "不限地區"}] + _location_options()
    _conv[user_id] = {"step": "setup_location", "page": 0, "options": opts, "pending": {}}
    kb = _build_kb(opts, 0, "LC", "LP")
    await bot.send_message(chat_id=chat_id, text="📍 請選擇工作地點：", reply_markup=kb)


async def _ask_person_kind(user_id: int, chat_id: int, bot) -> None:
    opts = [{"value": "", "text": "不限類別"}] + _person_kind_options()
    _conv[user_id].update({"step": "setup_person_kind", "page": 0, "options": opts})
    kb = _build_kb(opts, 0, "PC", "PP")
    await bot.send_message(chat_id=chat_id, text="👤 請選擇人員類別：", reply_markup=kb)


async def _ask_sysnam_grp(user_id: int, chat_id: int, bot) -> None:
    opts = SYSNAM_GRP_OPTIONS  # 不限 / 行政類 / 技術類
    _conv[user_id].update({"step": "setup_sysnam_grp", "page": 0, "options": opts})
    rows = [[
        InlineKeyboardButton(o["text"], callback_data=f"SC:{_encode_val(o['value'])}")
        for o in opts
    ]]
    await bot.send_message(
        chat_id=chat_id,
        text="🗂 請選擇職系大分類：",
        reply_markup=InlineKeyboardMarkup(rows),
    )


async def _ask_keyword(user_id: int, chat_id: int, bot) -> None:
    _conv[user_id]["step"] = "setup_keyword"
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("略過", callback_data="SKIP")]])
    await bot.send_message(
        chat_id=chat_id,
        text="🔍 請輸入職缺名稱關鍵字\n（例如：採購、資訊、行政）\n\n或點「略過」不限：",
        reply_markup=kb,
    )


async def _save_and_confirm(user_id: int, keyword: str, chat_id: int, bot) -> None:
    pending = _conv.get(user_id, {}).get("pending", {})
    sub = Subscription(
        platform         = "telegram",
        platform_user_id = str(user_id),
        work_place_code  = pending.get("work_place_code", ""),
        work_place_name  = pending.get("work_place_name", "不限"),
        person_kind_code = pending.get("person_kind_code", ""),
        person_kind_name = pending.get("person_kind_name", "不限"),
        sysnam_grp       = pending.get("sysnam_grp", ""),
        sysnam_grp_name  = pending.get("sysnam_grp_name", "不限"),
        title_keyword    = keyword,
    )
    save_subscription(sub)
    _conv.pop(user_id, None)

    await bot.send_message(chat_id=chat_id, text="\n".join([
        "✅ 訂閱設定完成！",
        "",
        f"📍 地點：{sub.work_place_name}",
        f"👤 類別：{sub.person_kind_name}",
        f"🗂 職系：{sub.sysnam_grp_name}",
        f"🔍 關鍵字：{sub.title_keyword or '不限'}",
        "",
        "傳任何訊息即可查詢最新職缺。",
    ]))


# ── Command handlers ──────────────────────────────────────────────────────────

async def cmd_start(update: Update, context) -> None:
    await update.message.reply_text("\n".join([
        "👋 歡迎使用政府職缺查詢 Bot！",
        "",
        "指令：",
        "/subscribe  設定訂閱條件",
        "/my\\_sub    查看目前設定",
        "/del\\_sub   刪除訂閱",
        "/help       使用說明",
        "",
        "傳任何訊息即可查詢最新職缺！",
    ]))


async def cmd_subscribe(update: Update, context) -> None:
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    await _ask_location(user_id, chat_id, context.bot)


async def cmd_my_sub(update: Update, context) -> None:
    sub = get_subscription("telegram", str(update.effective_user.id))
    if not sub:
        await update.message.reply_text("尚未設定訂閱條件。\n\n輸入 /subscribe 開始設定。")
    else:
        await update.message.reply_text("\n".join([
            "📋 目前訂閱設定",
            "",
            f"📍 地點：{sub.work_place_name or '不限'}",
            f"👤 類別：{sub.person_kind_name or '不限'}",
            f"🗂 職系：{sub.sysnam_grp_name or '不限'}",
            f"🔍 關鍵字：{sub.title_keyword or '不限'}",
            "",
            "輸入 /subscribe 可重新設定。",
        ]))


async def cmd_del_sub(update: Update, context) -> None:
    user_id = update.effective_user.id
    delete_subscription("telegram", str(user_id))
    _conv.pop(user_id, None)
    await update.message.reply_text("✅ 已刪除訂閱設定。\n輸入 /subscribe 可重新設定。")


async def cmd_help(update: Update, context) -> None:
    await update.message.reply_text("\n".join([
        "📋 使用說明",
        "",
        "/subscribe  設定訂閱條件",
        "/my\\_sub    查看目前設定",
        "/del\\_sub   刪除訂閱",
        "",
        "傳任何訊息即可查詢最新職缺。",
    ]))


# ── Callback query handler ────────────────────────────────────────────────────

async def handle_callback(update: Update, context) -> None:
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    data    = query.data
    step    = _conv.get(user_id, {}).get("step", "idle")

    # ── 翻頁 ─────────────────────────────────────────────────────────────────
    if data.startswith("LP:") and step == "setup_location":
        page = int(data[3:])
        opts = _conv[user_id]["options"]
        _conv[user_id]["page"] = page
        await query.edit_message_reply_markup(_build_kb(opts, page, "LC", "LP"))
        return

    if data.startswith("PP:") and step == "setup_person_kind":
        page = int(data[3:])
        opts = _conv[user_id]["options"]
        _conv[user_id]["page"] = page
        await query.edit_message_reply_markup(_build_kb(opts, page, "PC", "PP"))
        return

    # ── 選擇地點 ─────────────────────────────────────────────────────────────
    if data.startswith("LC:") and step == "setup_location":
        code = _decode_val(data[3:])
        opts = _conv[user_id]["options"]
        selected = next((o for o in opts if o["value"] == code), None)
        name = selected["text"] if selected else "不限地區"
        _conv[user_id]["pending"].update({
            "work_place_code": code,
            "work_place_name": name,
        })
        await query.edit_message_text(f"📍 地點：{name} ✓")
        await _ask_person_kind(user_id, chat_id, context.bot)
        return

    # ── 選擇人員類別 ─────────────────────────────────────────────────────────
    if data.startswith("PC:") and step == "setup_person_kind":
        code = _decode_val(data[3:])
        opts = _conv[user_id]["options"]
        selected = next((o for o in opts if o["value"] == code), None)
        name = selected["text"] if selected else "不限類別"
        _conv[user_id]["pending"].update({
            "person_kind_code": code,
            "person_kind_name": name,
        })
        await query.edit_message_text(f"👤 類別：{name} ✓")
        await _ask_sysnam_grp(user_id, chat_id, context.bot)
        return

    # ── 選擇職系大分類 ────────────────────────────────────────────────────────
    if data.startswith("SC:") and step == "setup_sysnam_grp":
        grp  = _decode_val(data[3:])
        name = next((o["text"] for o in SYSNAM_GRP_OPTIONS if o["value"] == grp), "不限")
        _conv[user_id]["pending"].update({
            "sysnam_grp":      grp,
            "sysnam_grp_name": name,
        })
        await query.edit_message_text(f"🗂 職系：{name} ✓")
        await _ask_keyword(user_id, chat_id, context.bot)
        return

    # ── 略過關鍵字 ────────────────────────────────────────────────────────────
    if data == "SKIP" and step == "setup_keyword":
        await query.edit_message_text("🔍 關鍵字：不限 ✓")
        await _save_and_confirm(user_id, "", chat_id, context.bot)
        return


# ── Message handler ───────────────────────────────────────────────────────────

async def handle_message(update: Update, context) -> None:
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    text    = update.message.text.strip()
    step    = _conv.get(user_id, {}).get("step", "idle")

    logger.info(f"Telegram user={user_id} step={step!r} text={text[:50]!r}")

    # 中文快速指令
    if text in {"訂閱", "設定條件", "設定訂閱"}:
        await _ask_location(user_id, chat_id, context.bot)
        return
    if text in {"我的訂閱", "查看訂閱"}:
        await cmd_my_sub(update, context)
        return
    if text in {"刪除訂閱", "取消訂閱"}:
        await cmd_del_sub(update, context)
        return
    if text in {"說明", "help"}:
        await cmd_help(update, context)
        return

    # 訂閱設定步驟：等待關鍵字輸入
    if step == "setup_keyword":
        await _save_and_confirm(user_id, text, chat_id, context.bot)
        return

    # 預設：以訂閱條件查詢
    result = handle_user_query("telegram", str(user_id))
    await update.message.reply_text(result)


# ── Application 管理 ──────────────────────────────────────────────────────────

def build_telegram_app() -> Application:
    if not TELEGRAM_BOT_TOKEN:
        raise ValueError("TELEGRAM_BOT_TOKEN 未設定")
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start",     cmd_start))
    app.add_handler(CommandHandler("subscribe", cmd_subscribe))
    app.add_handler(CommandHandler("my_sub",    cmd_my_sub))
    app.add_handler(CommandHandler("del_sub",   cmd_del_sub))
    app.add_handler(CommandHandler("help",      cmd_help))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    return app


async def init_telegram(webhook_url: str = "") -> None:
    global _tg_app
    if not TELEGRAM_BOT_TOKEN:
        logger.info("TELEGRAM_BOT_TOKEN 未設定，Telegram bot 停用")
        return

    _tg_app = build_telegram_app()
    await _tg_app.initialize()
    await _tg_app.start()

    if webhook_url:
        await _tg_app.bot.set_webhook(webhook_url)
        logger.info(f"Telegram webhook 已設定：{webhook_url}")
    else:
        logger.warning("未設定 Telegram webhook URL，bot 不接收訊息（僅限本機 ngrok 測試）")


async def shutdown_telegram() -> None:
    global _tg_app
    if _tg_app:
        await _tg_app.stop()
        await _tg_app.shutdown()
        _tg_app = None
        logger.info("Telegram bot 已關閉")


def get_telegram_app() -> Optional[Application]:
    return _tg_app
