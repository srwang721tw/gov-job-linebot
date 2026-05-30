"""
LINE Messaging API v3 webhook 處理。
包含：訂閱設定的多步驟對話流程（Quick Reply 選單）、查詢觸發。

對話狀態用 in-memory dict 維護（server restart 後重置，可接受）。
"""
from linebot.v3 import WebhookHandler
from linebot.v3.messaging import (
    ApiClient,
    Configuration,
    MessagingApi,
    ReplyMessageRequest,
    TextMessage,
    QuickReply,
    QuickReplyItem,
    MessageAction,
)
from linebot.v3.webhooks import MessageEvent, TextMessageContent

from app.crawler.form_options import get_form_options
from app.db.database import delete_subscription, get_subscription, save_subscription
from app.models.subscription import Subscription
from app.services.query_service import handle_user_query
from app.utils.config import LINE_CHANNEL_ACCESS_TOKEN, LINE_CHANNEL_SECRET
from app.utils.logger import logger

configuration = Configuration(access_token=LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# 每頁 Quick Reply 顯示幾個選項（LINE 上限 13，保留 2 個給翻頁按鈕）
_PAGE_SIZE = 11

# 翻頁用的特殊文字（使用者在 LINE 畫面上看到這些中文）
_NAV_NEXT = "下一頁▶"
_NAV_PREV = "◀上一頁"
_SKIP     = "略過"

# 各使用者的對話狀態
# {user_id: {"step": str, "page": int, "options": list, "pending": dict}}
_conv: dict[str, dict] = {}

_HELP_TEXT = "\n".join([
    "📋 使用說明",
    "",
    "傳任何訊息",
    "  → 查詢最新職缺",
    "",
    "「訂閱」",
    "  → 設定地點／類別／關鍵字",
    "",
    "「我的訂閱」",
    "  → 查看目前設定",
    "",
    "「刪除訂閱」",
    "  → 清除所有條件",
])

_TRIGGERS_SUBSCRIBE  = {"訂閱", "設定條件", "設定訂閱", "訂閱設定", "重新訂閱"}
_TRIGGERS_MY_SUB     = {"我的訂閱", "查看訂閱", "訂閱資訊", "目前條件"}
_TRIGGERS_DEL_SUB    = {"刪除訂閱", "取消訂閱", "清除訂閱"}
_TRIGGERS_HELP       = {"說明", "help", "Help", "?", "？"}


# ── 回覆工具 ─────────────────────────────────────────────────────────────────

def _reply(reply_token: str, *messages):
    with ApiClient(configuration) as api_client:
        MessagingApi(api_client).reply_message(
            ReplyMessageRequest(reply_token=reply_token, messages=list(messages))
        )


def _make_quick_reply(options: list[dict], page: int) -> QuickReply:
    """建立分頁 Quick Reply，選項超過一頁時加入翻頁按鈕。"""
    start = page * _PAGE_SIZE
    end   = min(start + _PAGE_SIZE, len(options))
    chunk = options[start:end]

    items = [
        QuickReplyItem(action=MessageAction(label=o["text"][:20], text=o["text"]))
        for o in chunk
    ]
    if page > 0:
        items.insert(0, QuickReplyItem(
            action=MessageAction(label=_NAV_PREV, text=_NAV_PREV)
        ))
    if end < len(options):
        items.append(QuickReplyItem(
            action=MessageAction(label=_NAV_NEXT, text=_NAV_NEXT)
        ))
    return QuickReply(items=items)


# ── 訂閱流程各步驟 ────────────────────────────────────────────────────────────

def _ask_location(user_id: str, reply_token: str, page: int = 0):
    opts = [{"value": "", "text": "不限地區"}] + get_form_options().get("work_place", [])
    _conv[user_id].update({"step": "setup_location", "page": page, "options": opts})
    _reply(reply_token, TextMessage(
        text="📍 請選擇工作地點：",
        quick_reply=_make_quick_reply(opts, page),
    ))


def _ask_person_kind(user_id: str, reply_token: str, page: int = 0):
    opts = [{"value": "", "text": "不限類別"}] + get_form_options().get("person_kind", [])
    _conv[user_id].update({"step": "setup_person_kind", "page": page, "options": opts})
    _reply(reply_token, TextMessage(
        text="👤 請選擇人員類別：",
        quick_reply=_make_quick_reply(opts, page),
    ))


def _ask_keyword(user_id: str, reply_token: str):
    _conv[user_id]["step"] = "setup_keyword"
    _reply(reply_token, TextMessage(
        text=(
            "🔍 請輸入職缺名稱關鍵字\n"
            "（例如：新聞輿情、採購、資訊）\n\n"
            "或點「略過」不限職缺類型："
        ),
        quick_reply=QuickReply(items=[
            QuickReplyItem(action=MessageAction(label=_SKIP, text=_SKIP)),
        ]),
    ))


def _save_and_confirm(user_id: str, reply_token: str):
    pending = _conv.get(user_id, {}).get("pending", {})
    sub = Subscription(
        line_user_id     = user_id,
        work_place_code  = pending.get("work_place_code", ""),
        work_place_name  = pending.get("work_place_name", "不限"),
        person_kind_code = pending.get("person_kind_code", ""),
        person_kind_name = pending.get("person_kind_name", "不限"),
        title_keyword    = pending.get("title_keyword", ""),
    )
    save_subscription(sub)
    _conv.pop(user_id, None)

    _reply(reply_token, TextMessage(text="\n".join([
        "✅ 訂閱設定完成！",
        "",
        f"📍 地點：{sub.work_place_name}",
        f"👤 類別：{sub.person_kind_name}",
        f"🔍 關鍵字：{sub.title_keyword or '不限'}",
        "",
        "傳任何訊息即可查詢最新職缺。",
    ])))


# ── 步驟處理器 ────────────────────────────────────────────────────────────────

def _handle_location_step(user_id: str, text: str, reply_token: str):
    state   = _conv[user_id]
    page    = state.get("page", 0)
    options = state.get("options", [])

    if text == _NAV_NEXT:
        _ask_location(user_id, reply_token, page + 1)
        return
    if text == _NAV_PREV:
        _ask_location(user_id, reply_token, max(0, page - 1))
        return

    selected = next((o for o in options if o["text"] == text), None)
    if selected is None:
        _ask_location(user_id, reply_token, page)  # 無效輸入 → 重新顯示
        return

    state.setdefault("pending", {}).update({
        "work_place_code": selected["value"],
        "work_place_name": selected["text"],
    })
    _ask_person_kind(user_id, reply_token)


def _handle_person_kind_step(user_id: str, text: str, reply_token: str):
    state   = _conv[user_id]
    page    = state.get("page", 0)
    options = state.get("options", [])

    if text == _NAV_NEXT:
        _ask_person_kind(user_id, reply_token, page + 1)
        return
    if text == _NAV_PREV:
        _ask_person_kind(user_id, reply_token, max(0, page - 1))
        return

    selected = next((o for o in options if o["text"] == text), None)
    if selected is None:
        _ask_person_kind(user_id, reply_token, page)
        return

    state.setdefault("pending", {}).update({
        "person_kind_code": selected["value"],
        "person_kind_name": selected["text"],
    })
    _ask_keyword(user_id, reply_token)


def _handle_keyword_step(user_id: str, text: str, reply_token: str):
    keyword = "" if text == _SKIP else text
    _conv[user_id].setdefault("pending", {})["title_keyword"] = keyword
    _save_and_confirm(user_id, reply_token)


# ── 主要 handler ──────────────────────────────────────────────────────────────

@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event: MessageEvent) -> None:
    user_id     = event.source.user_id
    text        = event.message.text.strip()
    reply_token = event.reply_token
    step        = _conv.get(user_id, {}).get("step", "idle")

    logger.info(f"user={user_id[:8]} step={step!r} text={text[:50]!r}")

    # ── 全域指令（優先於對話狀態）────────────────────────────────────────────
    if text in _TRIGGERS_SUBSCRIBE:
        _conv[user_id] = {"step": "setup_location", "pending": {}}
        _ask_location(user_id, reply_token)
        return

    if text in _TRIGGERS_MY_SUB:
        sub = get_subscription(user_id)
        if not sub:
            _reply(reply_token, TextMessage(
                text="尚未設定訂閱條件。\n\n輸入「訂閱」開始設定。"
            ))
        else:
            _reply(reply_token, TextMessage(text="\n".join([
                "📋 目前訂閱設定",
                "",
                f"📍 地點：{sub.work_place_name or '不限'}",
                f"👤 類別：{sub.person_kind_name or '不限'}",
                f"🔍 關鍵字：{sub.title_keyword or '不限'}",
                "",
                "輸入「訂閱」可重新設定。",
            ])))
        return

    if text in _TRIGGERS_DEL_SUB:
        delete_subscription(user_id)
        _conv.pop(user_id, None)
        _reply(reply_token, TextMessage(
            text="✅ 已刪除訂閱設定。\n輸入「訂閱」可重新設定。"
        ))
        return

    if text in _TRIGGERS_HELP:
        _reply(reply_token, TextMessage(text=_HELP_TEXT))
        return

    # ── 對話狀態機 ────────────────────────────────────────────────────────────
    if step == "setup_location":
        _handle_location_step(user_id, text, reply_token)
        return

    if step == "setup_person_kind":
        _handle_person_kind_step(user_id, text, reply_token)
        return

    if step == "setup_keyword":
        _handle_keyword_step(user_id, text, reply_token)
        return

    # ── 預設：以訂閱條件查詢 ──────────────────────────────────────────────────
    result = handle_user_query(user_id)
    _reply(reply_token, TextMessage(text=result))
