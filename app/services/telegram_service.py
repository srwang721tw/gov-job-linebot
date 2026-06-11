"""
Telegram Bot 服務（v3.2）。
與 LINE bot 共用 query_service、database、form_options 層。

訂閱設定流程（7 步驟，InlineKeyboard）：
  1. 工作地點（多選 + 確定）
  2. 官等類別（多選 + 確定）
  3. 職系大分類（單選）
  4. 職系細項（多選 + 確定，大分類=不限則略過）
  5. 職務列等區間（文字輸入）
  6. 關鍵字（文字輸入）
  7. 確認摘要

callback_data 前綴：
  LC:CODE   選擇地點（CODE=_ 表空值）
  LP:N      地點翻頁
  LC:ALL    不限地區（清除所有選擇並前往下一步）
  LC:CONFIRM 地點確認
  RC:CODE   選擇官等（1~4）
  RC:ALL    不限官等
  RC:CONFIRM 官等確認
  SC:GRP    選擇職系大分類
  NC:IDX    選擇職系細項（index in options list）
  NP:N      職系細項翻頁
  NC:ALL    不限細項
  NC:CONFIRM 職系細項確認
  SKIP      略過（職務列等/關鍵字）
"""
import asyncio
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

from app.crawler.form_options import SYSNAM_GRP_OPTIONS, get_form_options, get_sysnam_names_for_grp
from app.db.database import delete_subscription, get_subscription, save_subscription, upsert_telegram_user
from app.models.subscription import Subscription
from app.services.query_service import handle_user_query
from app.utils.config import TELEGRAM_BOT_TOKEN, TELEGRAM_WEBHOOK_SECRET
from app.utils.formatting import RANK_TYPE_NAMES, comma_to_jap, grade_label, rank_names
from app.utils.logger import logger

# ── 全域 Application 實例 ─────────────────────────────────────────────────────
_tg_app: Optional[Application] = None

# ── 對話狀態 ─────────────────────────────────────────────────────────────────
_conv: dict[int, dict] = {}

_PAGE_SIZE     = 8   # Inline keyboard 每頁顯示幾個選項
_ITEMS_PER_ROW = 2



# ── 工具函式 ──────────────────────────────────────────────────────────────────

def _clean_name(name: str) -> str:
    """去除地點代碼前綴：'10-臺北市' → '臺北市'"""
    m = re.match(r"^\d{1,3}-(.+)$", name)
    return m.group(1) if m else name


def _location_options() -> list[dict]:
    return [
        {"value": o["value"], "text": _clean_name(o["text"])}
        for o in get_form_options().get("work_place", [])
        if not o["value"].endswith("00")
    ]


def _encode_val(v: str) -> str:
    return v if v else "_"


def _decode_val(v: str) -> str:
    return "" if v == "_" else v


def _build_multiselect_kb(
    options: list[dict],
    page: int,
    sel_prefix: str,
    page_prefix: str,
    selected_values: set[str],
    confirm_data: str,
    all_data: str,
) -> InlineKeyboardMarkup:
    """
    建立多選 InlineKeyboard（帶 ✅/☐ 切換）。
    """
    start = page * _PAGE_SIZE
    end   = min(start + _PAGE_SIZE, len(options))
    chunk = options[start:end]

    rows = []
    for i in range(0, len(chunk), _ITEMS_PER_ROW):
        row = []
        for o in chunk[i:i + _ITEMS_PER_ROW]:
            label = f"✅ {o['text']}" if o["value"] in selected_values else f"☐ {o['text']}"
            row.append(InlineKeyboardButton(
                text=label,
                callback_data=f"{sel_prefix}:{_encode_val(o['value'])}",
            ))
        rows.append(row)

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("◀ 上一頁", callback_data=f"{page_prefix}:{page - 1}"))
    if end < len(options):
        nav.append(InlineKeyboardButton("下一頁 ▶", callback_data=f"{page_prefix}:{page + 1}"))
    if nav:
        rows.append(nav)

    # 不限 + 確定
    rows.append([
        InlineKeyboardButton("不限（清除全選）", callback_data=all_data),
        InlineKeyboardButton(f"✅ 確定 ({len(selected_values)})", callback_data=confirm_data),
    ])
    return InlineKeyboardMarkup(rows)


# ── 訂閱設定步驟 ──────────────────────────────────────────────────────────────

async def _ask_location(user_id: int, chat_id: int, bot) -> None:
    """步驟 1：多選工作地點。"""
    opts = _location_options()
    if not opts:
        # 選單無法從 DGPA 取得，提示使用者點「不限」繼續
        await bot.send_message(
            chat_id=chat_id,
            text=(
                "⚠️ 無法載入工作地點選項（DGPA 連線失敗）\n"
                "請點「不限地區」繼續，稍後可重新 /subscribe 重試。"
            ),
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("不限地區（繼續）", callback_data="LC:ALL")
            ]]),
        )
        _conv[user_id].update({"step": "setup_location", "page": 0, "loc_options": []})
        return
    selected = set(_conv[user_id].get("pending", {}).get("work_place_codes", "").split(",")) - {""}
    _conv[user_id].update({"step": "setup_location", "page": 0, "loc_options": opts})
    kb = _build_multiselect_kb(opts, 0, "LC", "LP", selected, "LC:CONFIRM", "LC:ALL")
    await bot.send_message(chat_id=chat_id, text="📍 請選擇工作地點（可多選）：", reply_markup=kb)


async def _ask_rank_types(user_id: int, chat_id: int, bot) -> None:
    """步驟 2：多選官等類別。"""
    selected_codes = set(
        c for c in _conv[user_id].get("pending", {}).get("rank_types", "").split(",") if c
    )
    opts = [{"value": code, "text": name} for code, name in RANK_TYPE_NAMES.items()]
    _conv[user_id].update({"step": "setup_rank_types", "page": 0})

    rows = []
    for i in range(0, len(opts), _ITEMS_PER_ROW):
        row = []
        for o in opts[i:i + _ITEMS_PER_ROW]:
            label = f"✅ {o['text']}" if o["value"] in selected_codes else f"☐ {o['text']}"
            row.append(InlineKeyboardButton(label, callback_data=f"RC:{o['value']}"))
        rows.append(row)
    rows.append([
        InlineKeyboardButton("不限官等", callback_data="RC:ALL"),
        InlineKeyboardButton(f"✅ 確定 ({len(selected_codes)})", callback_data="RC:CONFIRM"),
    ])
    await bot.send_message(
        chat_id=chat_id,
        text="👔 請選擇官等類別（可複選）：",
        reply_markup=InlineKeyboardMarkup(rows),
    )


async def _ask_sysnam_grp(user_id: int, chat_id: int, bot) -> None:
    """步驟 3：單選職系大分類。"""
    opts = SYSNAM_GRP_OPTIONS
    _conv[user_id].update({"step": "setup_sysnam_grp"})
    rows = [[
        InlineKeyboardButton(o["text"], callback_data=f"SC:{_encode_val(o['value'])}")
        for o in opts
    ]]
    await bot.send_message(
        chat_id=chat_id,
        text="🗂 請選擇職系大分類：",
        reply_markup=InlineKeyboardMarkup(rows),
    )


async def _ask_sysnam_names(user_id: int, chat_id: int, bot, sysnam_grp: str) -> None:
    """步驟 4：多選職系細項（依大分類動態載入）。"""
    opts_raw = get_sysnam_names_for_grp(sysnam_grp)  # list[str]
    opts = [{"value": n, "text": n} for n in opts_raw]
    if not opts:
        # 選單無法取得，直接跳過職系細項
        _conv[user_id].update({"step": "setup_sysnam_names", "page": 0, "sysnam_options": []})
        _conv[user_id].setdefault("pending", {})["sysnam_names"] = ""
        await bot.send_message(
            chat_id=chat_id,
            text=(
                "⚠️ 無法載入職系細項（DGPA 連線失敗）\n"
                "點「不限細項」繼續，稍後可重新 /subscribe 重試。"
            ),
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("不限細項（繼續）", callback_data="NC:ALL")
            ]]),
        )
        return
    selected = set(
        n for n in _conv[user_id].get("pending", {}).get("sysnam_names", "").split(",") if n
    )
    _conv[user_id].update({"step": "setup_sysnam_names", "page": 0, "sysnam_options": opts})
    kb = _build_multiselect_kb(opts, 0, "NC", "NP", selected, "NC:CONFIRM", "NC:ALL")
    await bot.send_message(
        chat_id=chat_id,
        text="🗂 請選擇職系細項（可多選）：",
        reply_markup=kb,
    )


async def _ask_rank_grade(user_id: int, chat_id: int, bot) -> None:
    """步驟 5：文字輸入職務列等區間。"""
    _conv[user_id]["step"] = "setup_rank_grade"
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("略過", callback_data="SKIP")]])
    await bot.send_message(
        chat_id=chat_id,
        text=(
            "📊 請輸入職等範圍（格式：最低-最高，如 5-9）\n"
            "單一職等直接輸入數字（如 9）\n"
            "職等範圍 1~14\n\n"
            "或點「略過」不限職等："
        ),
        reply_markup=kb,
    )


async def _ask_keywords(user_id: int, chat_id: int, bot) -> None:
    """步驟 6：文字輸入關鍵字。"""
    _conv[user_id]["step"] = "setup_keywords"
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("略過", callback_data="SKIP")]])
    await bot.send_message(
        chat_id=chat_id,
        text=(
            "🔍 請輸入搜尋關鍵字（逗號分隔），\n"
            "比對職稱、機關、資格、工作項目\n"
            "例如：採購,資訊,行政\n\n"
            "或點「略過」不限關鍵字："
        ),
        reply_markup=kb,
    )


async def _save_and_confirm(user_id: int, keywords: str, chat_id: int, bot) -> None:
    """步驟 7：儲存並顯示摘要。"""
    pending = _conv.get(user_id, {}).get("pending", {})
    rank_types = pending.get("rank_types", "")
    type_names = rank_names(rank_types)

    sub = Subscription(
        platform          = "telegram",
        platform_user_id  = str(user_id),
        work_place_codes  = pending.get("work_place_codes", ""),
        work_place_names  = pending.get("work_place_names", "不限"),
        rank_types        = rank_types,
        rank_grade_min    = pending.get("rank_grade_min", 0),
        rank_grade_max    = pending.get("rank_grade_max", 0),
        sysnam_grp        = pending.get("sysnam_grp", ""),
        sysnam_grp_name   = pending.get("sysnam_grp_name", "不限"),
        sysnam_names      = pending.get("sysnam_names", ""),
        keywords          = keywords,
    )
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, save_subscription, sub)
    _conv.pop(user_id, None)

    grade_str = grade_label(sub.rank_grade_min, sub.rank_grade_max, "不限")

    await bot.send_message(chat_id=chat_id, text="\n".join([
        "✅ 訂閱設定完成！",
        "",
        f"📍 地點：{comma_to_jap(sub.work_place_names)}",
        f"👔 官等：{'、'.join(type_names) or '不限'}",
        f"🗂 職系：{sub.sysnam_grp_name}" + (f"（{comma_to_jap(sub.sysnam_names)}）" if sub.sysnam_names else ""),
        f"📊 職等：{grade_str}",
        f"🔍 關鍵字：{sub.keywords or '不限'}",
        "",
        "傳任何訊息即可查詢最新職缺。",
    ]))


# ── 職等解析工具 ──────────────────────────────────────────────────────────────

def _parse_grade_range(text: str) -> tuple[int, int]:
    text = text.strip()
    if not text or text in ("略過", "不限"):
        return (0, 0)
    m = re.match(r"^(\d+)\s*[-~至]\s*(\d+)$", text)
    if m:
        lo, hi = int(m.group(1)), int(m.group(2))
        return (min(lo, hi), max(lo, hi))
    m2 = re.match(r"^(\d+)$", text)
    if m2:
        v = int(m2.group(1))
        return (v, v)
    return (0, 0)


# ── Command handlers ──────────────────────────────────────────────────────────

async def cmd_start(update: Update, context) -> None:
    await update.message.reply_text("\n".join([
        "👋 歡迎使用政府職缺查詢 Bot！",
        "",
        "指令：",
        "/subscribe          設定訂閱條件",
        "/mysubscription     查看目前設定",
        "/deletesubscription 刪除訂閱",
        "/help               使用說明",
        "",
        "傳任何訊息即可查詢最新職缺！",
    ]))


async def cmd_subscribe(update: Update, context) -> None:
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    _conv[user_id] = {"step": "setup_location", "pending": {}}
    await _ask_location(user_id, chat_id, context.bot)


async def cmd_mysubscription(update: Update, context) -> None:
    sub = get_subscription("telegram", str(update.effective_user.id))
    if not sub:
        await update.message.reply_text("尚未設定訂閱條件。\n\n輸入 /subscribe 開始設定。")
    else:
        type_names = rank_names(sub.rank_types)
        grade_str = grade_label(sub.rank_grade_min, sub.rank_grade_max, "不限")
        await update.message.reply_text("\n".join([
            "📋 目前訂閱設定",
            "",
            f"📍 地點：{comma_to_jap(sub.work_place_names) or '不限'}",
            f"👔 官等：{'、'.join(type_names) or '不限'}",
            f"🗂 職系：{sub.sysnam_grp_name or '不限'}" + (f"（{comma_to_jap(sub.sysnam_names)}）" if sub.sysnam_names else ""),
            f"📊 職等：{grade_str}",
            f"🔍 關鍵字：{sub.keywords or '不限'}",
            "",
            "輸入 /subscribe 可重新設定。",
        ]))


async def cmd_deletesubscription(update: Update, context) -> None:
    user_id = update.effective_user.id
    delete_subscription("telegram", str(user_id))
    _conv.pop(user_id, None)
    await update.message.reply_text("✅ 已刪除訂閱設定。\n輸入 /subscribe 可重新設定。")


async def cmd_help(update: Update, context) -> None:
    await update.message.reply_text("\n".join([
        "📋 使用說明",
        "",
        "/subscribe          設定訂閱條件",
        "/results            依訂閱條件查詢職缺",
        "/mysubscription     查看目前設定",
        "/deletesubscription 刪除訂閱",
        "",
        "傳任何文字（如「行政」「台北」）",
        "  → 以輸入文字為關鍵字查詢",
    ]))


async def cmd_results(update: Update, context) -> None:
    """依完整訂閱條件（含儲存的關鍵字）查詢職缺。"""
    user_id = update.effective_user.id
    loop = asyncio.get_event_loop()
    result, parse_mode = await loop.run_in_executor(
        None, handle_user_query, "telegram", str(user_id)
    )
    if parse_mode == "HTML":
        await update.message.reply_text(result, parse_mode="HTML")
    else:
        await update.message.reply_text(result)


# ── Callback query handler ────────────────────────────────────────────────────

async def handle_callback(update: Update, context) -> None:
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    data    = query.data
    step    = _conv.get(user_id, {}).get("step", "idle")

    pending = _conv.get(user_id, {}).setdefault("pending", {})

    # ── 地點相關 ─────────────────────────────────────────────────────────────
    if step == "setup_location":
        opts = _conv[user_id].get("loc_options") or _location_options()
        selected = set(c for c in pending.get("work_place_codes", "").split(",") if c)

        def _loc_status(sel: set) -> str:
            names = [o["text"] for o in opts if o["value"] in sel]
            return "、".join(names) if names else "（未選擇，點確定等於不限）"

        if data.startswith("LP:"):
            page = int(data[3:])
            _conv[user_id]["page"] = page
            await query.edit_message_text(
                f"📍 請選擇工作地點（可多選）：\n已選：{_loc_status(selected)}",
                reply_markup=_build_multiselect_kb(opts, page, "LC", "LP", selected, "LC:CONFIRM", "LC:ALL"),
            )
            return

        if data.startswith("LC:") and data not in ("LC:CONFIRM", "LC:ALL"):
            code = _decode_val(data[3:])
            if code in selected:
                selected.discard(code)
            else:
                selected.add(code)
            names = [o["text"] for o in opts if o["value"] in selected]
            pending["work_place_codes"] = ",".join(selected)
            pending["work_place_names"] = ",".join(names) if names else "不限"
            page = _conv[user_id].get("page", 0)
            await query.edit_message_text(
                f"📍 請選擇工作地點（可多選）：\n已選：{_loc_status(selected)}",
                reply_markup=_build_multiselect_kb(opts, page, "LC", "LP", selected, "LC:CONFIRM", "LC:ALL"),
            )
            return

        if data == "LC:ALL":
            pending["work_place_codes"] = ""
            pending["work_place_names"] = "不限"
            await query.edit_message_text("📍 地點：不限 ✓")
            await _ask_rank_types(user_id, chat_id, context.bot)
            return

        if data == "LC:CONFIRM":
            names = pending.get("work_place_names", "不限")
            await query.edit_message_text(f"📍 地點：{comma_to_jap(names) or '不限'} ✓")
            await _ask_rank_types(user_id, chat_id, context.bot)
            return

    # ── 官等相關 ─────────────────────────────────────────────────────────────
    if step == "setup_rank_types":
        selected_codes = set(c for c in pending.get("rank_types", "").split(",") if c)

        def _rank_kb(sel: set) -> InlineKeyboardMarkup:
            rank_opts = [{"value": c, "text": n} for c, n in RANK_TYPE_NAMES.items()]
            rows = []
            for i in range(0, len(rank_opts), _ITEMS_PER_ROW):
                row = []
                for o in rank_opts[i:i + _ITEMS_PER_ROW]:
                    label = f"✅ {o['text']}" if o["value"] in sel else f"☐ {o['text']}"
                    row.append(InlineKeyboardButton(label, callback_data=f"RC:{o['value']}"))
                rows.append(row)
            rows.append([
                InlineKeyboardButton("不限官等", callback_data="RC:ALL"),
                InlineKeyboardButton(f"✅ 確定 ({len(sel)})", callback_data="RC:CONFIRM"),
            ])
            return InlineKeyboardMarkup(rows)

        def _rank_status(sel: set) -> str:
            names = rank_names(",".join(sel))
            return "、".join(names) if names else "（未選擇，點確定等於不限）"

        if data.startswith("RC:") and data not in ("RC:CONFIRM", "RC:ALL"):
            code = data[3:]
            if code in selected_codes:
                selected_codes.discard(code)
            else:
                selected_codes.add(code)
            pending["rank_types"] = ",".join(selected_codes)
            await query.edit_message_text(
                f"👔 請選擇官等類別（可複選）：\n已選：{_rank_status(selected_codes)}",
                reply_markup=_rank_kb(selected_codes),
            )
            return

        if data == "RC:ALL":
            pending["rank_types"] = ""
            await query.edit_message_text("👔 官等：不限 ✓")
            await _ask_sysnam_grp(user_id, chat_id, context.bot)
            return

        if data == "RC:CONFIRM":
            selected_codes = set(c for c in pending.get("rank_types", "").split(",") if c)
            type_names = rank_names(",".join(selected_codes))
            await query.edit_message_text(f"👔 官等：{'、'.join(type_names) or '不限'} ✓")
            await _ask_sysnam_grp(user_id, chat_id, context.bot)
            return

    # ── 職系大分類 ────────────────────────────────────────────────────────────
    if data.startswith("SC:") and step == "setup_sysnam_grp":
        grp  = _decode_val(data[3:])
        name = next((o["text"] for o in SYSNAM_GRP_OPTIONS if o["value"] == grp), "不限")
        pending.update({"sysnam_grp": grp, "sysnam_grp_name": name})
        await query.edit_message_text(f"🗂 職系大分類：{name} ✓")
        if grp:
            await _ask_sysnam_names(user_id, chat_id, context.bot, grp)
        else:
            pending["sysnam_names"] = ""
            await _ask_rank_grade(user_id, chat_id, context.bot)
        return

    # ── 職系細項 ─────────────────────────────────────────────────────────────
    if step == "setup_sysnam_names":
        sysnam_opts = _conv[user_id].get("sysnam_options", [])
        selected = set(n for n in pending.get("sysnam_names", "").split(",") if n)

        def _sysnam_status(sel: set) -> str:
            return "、".join(sel) if sel else "（未選擇，點確定等於不限）"

        if data.startswith("NP:"):
            page = int(data[3:])
            _conv[user_id]["page"] = page
            await query.edit_message_text(
                f"🗂 請選擇職系細項（可多選）：\n已選：{_sysnam_status(selected)}",
                reply_markup=_build_multiselect_kb(sysnam_opts, page, "NC", "NP", selected, "NC:CONFIRM", "NC:ALL"),
            )
            return

        if data.startswith("NC:") and data not in ("NC:CONFIRM", "NC:ALL"):
            name = _decode_val(data[3:])
            if name in selected:
                selected.discard(name)
            else:
                selected.add(name)
            pending["sysnam_names"] = ",".join(selected)
            page = _conv[user_id].get("page", 0)
            await query.edit_message_text(
                f"🗂 請選擇職系細項（可多選）：\n已選：{_sysnam_status(selected)}",
                reply_markup=_build_multiselect_kb(sysnam_opts, page, "NC", "NP", selected, "NC:CONFIRM", "NC:ALL"),
            )
            return

        if data == "NC:ALL":
            pending["sysnam_names"] = ""
            await query.edit_message_text("🗂 職系細項：不限 ✓")
            await _ask_rank_grade(user_id, chat_id, context.bot)
            return

        if data == "NC:CONFIRM":
            selected = set(n for n in pending.get("sysnam_names", "").split(",") if n)
            names_str = "、".join(selected) if selected else "不限"
            await query.edit_message_text(f"🗂 職系細項：{names_str} ✓")
            await _ask_rank_grade(user_id, chat_id, context.bot)
            return

    # ── 略過（職等/關鍵字）────────────────────────────────────────────────────
    if data == "SKIP":
        if step == "setup_rank_grade":
            pending.update({"rank_grade_min": 0, "rank_grade_max": 0})
            await query.edit_message_text("📊 職等：不限 ✓")
            await _ask_keywords(user_id, chat_id, context.bot)
            return
        if step == "setup_keywords":
            await query.edit_message_text("🔍 關鍵字：不限 ✓")
            await _save_and_confirm(user_id, "", chat_id, context.bot)
            return


# ── Message handler ───────────────────────────────────────────────────────────

async def handle_message(update: Update, context) -> None:
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    text    = update.message.text.strip()
    step    = _conv.get(user_id, {}).get("step", "idle")

    logger.info(f"Telegram user={user_id} step={step!r}")

    # 記錄使用者
    try:
        upsert_telegram_user(
            user_id,
            username   = update.effective_user.username or "",
            first_name = update.effective_user.first_name or "",
        )
    except Exception:
        pass

    # 中文快速指令
    if text in {"訂閱", "設定條件", "設定訂閱"}:
        _conv[user_id] = {"step": "setup_location", "pending": {}}
        await _ask_location(user_id, chat_id, context.bot)
        return
    if text in {"我的訂閱", "查看訂閱"}:
        await cmd_mysubscription(update, context)
        return
    if text in {"刪除訂閱", "取消訂閱"}:
        await cmd_deletesubscription(update, context)
        return
    if text in {"說明", "help"}:
        await cmd_help(update, context)
        return

    # 職等輸入步驟
    if step == "setup_rank_grade":
        lo, hi = _parse_grade_range(text)
        _conv[user_id].setdefault("pending", {}).update({
            "rank_grade_min": lo,
            "rank_grade_max": hi,
        })
        grade_str = grade_label(lo, hi, "不限")
        await update.message.reply_text(f"📊 職等：{grade_str} ✓")
        await _ask_keywords(user_id, chat_id, context.bot)
        return

    # 關鍵字輸入步驟
    if step == "setup_keywords":
        await _save_and_confirm(user_id, text, chat_id, context.bot)
        return

    # 預設：以輸入文字為關鍵字，合併訂閱其他條件查詢
    loop = asyncio.get_event_loop()
    result, parse_mode = await loop.run_in_executor(
        None, handle_user_query, "telegram", str(user_id), text
    )
    if parse_mode == "HTML":
        await update.message.reply_text(result, parse_mode="HTML")
    else:
        await update.message.reply_text(result)


# ── Application 管理 ──────────────────────────────────────────────────────────

def build_telegram_app() -> Application:
    if not TELEGRAM_BOT_TOKEN:
        raise ValueError("TELEGRAM_BOT_TOKEN 未設定")
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start",              cmd_start))
    app.add_handler(CommandHandler("subscribe",          cmd_subscribe))
    app.add_handler(CommandHandler("results",            cmd_results))
    app.add_handler(CommandHandler("mysubscription",     cmd_mysubscription))
    app.add_handler(CommandHandler("deletesubscription", cmd_deletesubscription))
    app.add_handler(CommandHandler("help",               cmd_help))
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
        await _tg_app.bot.set_webhook(
            webhook_url,
            secret_token=TELEGRAM_WEBHOOK_SECRET or None,
        )
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
