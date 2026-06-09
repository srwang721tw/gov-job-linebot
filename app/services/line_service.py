"""
LINE Messaging API v3.1 webhook 處理。

訂閱設定流程（7 步驟）：
  1. 工作地點（文字輸入，逗號分隔縣市名稱，Quick Reply 有「不限地區」快捷鍵）
  2. 官等類別（Quick Reply 逐一累加，點「✅確定」結束）
  3. 職系大分類（Quick Reply 單選：不限/行政類/技術類）
  4. 職系細項（文字輸入，可略過）
  5. 職務列等區間（文字輸入 "最低-最高" 或單一職等，可略過）
  6. 關鍵字（文字輸入，逗號分隔，可略過）
  7. 完成確認

查詢觸發：任何文字訊息（非設定指令）→ handle_user_query → 回覆純文字
"""
import re

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

from app.crawler.form_options import SYSNAM_GRP_OPTIONS, get_form_options
from app.db.database import delete_subscription, get_subscription, save_subscription, upsert_line_user
from app.models.subscription import Subscription
from app.services.query_service import handle_user_query
from app.utils.config import LINE_CHANNEL_ACCESS_TOKEN, LINE_CHANNEL_SECRET
from app.utils.logger import logger

configuration = Configuration(access_token=LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# LINE Quick Reply 上限 13 個按鈕，保留 2 個給翻頁
_PAGE_SIZE = 11

_NAV_NEXT  = "下一頁▶"
_NAV_PREV  = "◀上一頁"
_SKIP      = "略過"

# 官等代碼 → 名稱
_RANK_TYPE_NAMES = {
    "1": "簡任",
    "2": "薦任",
    "3": "委任",
    "4": "其他",
}

# 各使用者的對話狀態
_conv: dict[str, dict] = {}

_HELP_TEXT = "\n".join([
    "📋 使用說明",
    "",
    "「/results」或「最新職缺」",
    "  → 依訂閱條件查詢職缺",
    "",
    "傳任何文字（如「行政」「台北」）",
    "  → 以輸入文字為關鍵字查詢",
    "",
    "「訂閱」",
    "  → 設定地點／官等／職系／職等／關鍵字",
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
_TRIGGERS_RESULTS    = {"/results", "results", "查看職缺", "最新職缺"}


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


# ── 地點解析工具 ──────────────────────────────────────────────────────────────

def _parse_location_text(text: str) -> tuple[str, str]:
    """
    解析使用者輸入的縣市名稱，回傳 (codes, names)（逗號分隔）。
    '臺北市, 臺中市' → ('10,42', '臺北市,臺中市')
    '台北市' → ('10', '臺北市')（台/臺 互換）
    """
    opts = get_form_options().get("work_place", [])
    name_map: dict[str, tuple[str, str]] = {}  # text → (code, 標準名稱)
    for o in opts:
        if o["value"].endswith("00"):
            continue
        clean = re.sub(r"^\d+-", "", o["text"])  # '10-臺北市' → '臺北市'
        name_map[clean] = (o["value"], clean)
        alt = clean.replace("臺", "台")
        if alt != clean:
            name_map[alt] = (o["value"], clean)

    inputs = re.split(r"[\s、，,]+", text.strip())
    codes, names = [], []
    for inp in inputs:
        inp = inp.strip()
        if not inp:
            continue
        if inp in name_map:
            code, std_name = name_map[inp]
            if code not in codes:
                codes.append(code)
                names.append(std_name)
        else:
            # 模糊比對（部分包含）
            matched = [(code, name) for key, (code, name) in name_map.items() if inp in key]
            if matched:
                code, std_name = matched[0]
                if code not in codes:
                    codes.append(code)
                    names.append(std_name)

    return (",".join(codes), ",".join(names))


# ── 職等解析工具 ──────────────────────────────────────────────────────────────

def _parse_grade_range(text: str) -> tuple[int, int]:
    """
    解析職等範圍輸入。
    '5-9' → (5, 9)
    '9'   → (9, 9)
    '5至9' → (5, 9)
    '不限' / '略過' / '' → (0, 0)
    """
    text = text.strip()
    if not text or text in (_SKIP, "不限", "略過"):
        return (0, 0)
    # 數字範圍：5-9 or 5~9 or 5至9
    m = re.match(r"^(\d+)\s*[-~至]\s*(\d+)$", text)
    if m:
        lo, hi = int(m.group(1)), int(m.group(2))
        return (min(lo, hi), max(lo, hi))
    # 單一數字
    m2 = re.match(r"^(\d+)$", text)
    if m2:
        v = int(m2.group(1))
        return (v, v)
    return (0, 0)


# ── 訂閱流程各步驟 ────────────────────────────────────────────────────────────

def _ask_location(user_id: str, reply_token: str):
    """步驟 1：詢問工作地點（文字輸入 + 「不限地區」快捷鍵）。"""
    _conv[user_id].update({"step": "setup_location"})
    _reply(reply_token, TextMessage(
        text=(
            "📍 請輸入工作地點（逗號分隔），\n"
            "例如：臺北市,新北市,臺中市\n\n"
            "或點「不限地區」："
        ),
        quick_reply=QuickReply(items=[
            QuickReplyItem(action=MessageAction(label="不限地區", text="不限地區")),
        ]),
    ))


def _ask_rank_types(user_id: str, reply_token: str):
    """步驟 2：詢問官等類別（Quick Reply 逐一累加）。"""
    selected_codes = _conv[user_id].get("pending", {}).get("rank_types", "").split(",")
    selected_codes = [c for c in selected_codes if c]

    # 建立 Quick Reply 選項
    items = []
    for code, name in _RANK_TYPE_NAMES.items():
        label = f"✅ {name}" if code in selected_codes else name
        items.append(QuickReplyItem(action=MessageAction(label=label, text=f"官等:{name}")))

    items.append(QuickReplyItem(action=MessageAction(label="不限官等", text="不限官等")))
    items.append(QuickReplyItem(action=MessageAction(label="✅ 確定", text="官等:確定")))

    selected_names = [_RANK_TYPE_NAMES[c] for c in ["1","2","3","4"] if c in selected_codes]
    current = f"已選：{', '.join(selected_names)}" if selected_names else "（未選擇，等於不限）"
    _conv[user_id].update({"step": "setup_rank_types"})
    _reply(reply_token, TextMessage(
        text=f"👔 請選擇官等類別（可複選）：\n{current}",
        quick_reply=QuickReply(items=items),
    ))


def _ask_sysnam_grp(user_id: str, reply_token: str):
    """步驟 3：詢問職系大分類（Quick Reply 單選）。"""
    opts = SYSNAM_GRP_OPTIONS  # [{"value":"","text":"不限"}, {"value":"A","text":"行政類"}, ...]
    _conv[user_id].update({"step": "setup_sysnam_grp", "options": opts})
    _reply(reply_token, TextMessage(
        text="🗂 請選擇職系大分類：",
        quick_reply=_make_quick_reply(opts, 0),
    ))


def _ask_sysnam_names(user_id: str, reply_token: str):
    """步驟 4：詢問職系細項（文字輸入，可略過）。"""
    _conv[user_id].update({"step": "setup_sysnam_names"})
    _reply(reply_token, TextMessage(
        text=(
            "🗂 請輸入職系名稱（逗號分隔），\n"
            "例如：綜合行政,社會行政\n\n"
            "或點「略過」不限職系細項："
        ),
        quick_reply=QuickReply(items=[
            QuickReplyItem(action=MessageAction(label=_SKIP, text=_SKIP)),
        ]),
    ))


def _ask_rank_grade(user_id: str, reply_token: str):
    """步驟 5：詢問職務列等區間（文字輸入，可略過）。"""
    _conv[user_id].update({"step": "setup_rank_grade"})
    _reply(reply_token, TextMessage(
        text=(
            "📊 請輸入職等範圍（格式：最低-最高，如 5-9）\n"
            "單一職等直接輸入數字（如 9）\n"
            "職等範圍 1~14\n\n"
            "或點「略過」不限職等："
        ),
        quick_reply=QuickReply(items=[
            QuickReplyItem(action=MessageAction(label=_SKIP, text=_SKIP)),
        ]),
    ))


def _ask_keywords(user_id: str, reply_token: str):
    """步驟 6：詢問關鍵字（文字輸入，可略過）。"""
    _conv[user_id].update({"step": "setup_keywords"})
    _reply(reply_token, TextMessage(
        text=(
            "🔍 請輸入搜尋關鍵字（逗號分隔），\n"
            "比對職稱、機關、資格、工作項目\n"
            "例如：採購,資訊,行政\n\n"
            "或點「略過」不限關鍵字："
        ),
        quick_reply=QuickReply(items=[
            QuickReplyItem(action=MessageAction(label=_SKIP, text=_SKIP)),
        ]),
    ))


def _save_and_confirm(user_id: str, reply_token: str):
    """步驟 7：儲存訂閱並顯示確認訊息。"""
    pending = _conv.get(user_id, {}).get("pending", {})
    rank_types = pending.get("rank_types", "")
    type_names = [_RANK_TYPE_NAMES[c] for c in ["1","2","3","4"] if c in rank_types.split(",")]

    sub = Subscription(
        platform          = "line",
        platform_user_id  = user_id,
        work_place_codes  = pending.get("work_place_codes", ""),
        work_place_names  = pending.get("work_place_names", "不限"),
        rank_types        = rank_types,
        rank_grade_min    = pending.get("rank_grade_min", 0),
        rank_grade_max    = pending.get("rank_grade_max", 0),
        sysnam_grp        = pending.get("sysnam_grp", ""),
        sysnam_grp_name   = pending.get("sysnam_grp_name", "不限"),
        sysnam_names      = pending.get("sysnam_names", ""),
        keywords          = pending.get("keywords", ""),
    )
    save_subscription(sub)
    _conv.pop(user_id, None)

    grade_min = sub.rank_grade_min
    grade_max = sub.rank_grade_max
    if grade_min == 0 and grade_max == 0:
        grade_str = "不限"
    elif grade_min == grade_max:
        grade_str = f"{grade_min}職等"
    else:
        grade_str = f"{grade_min}-{grade_max}職等"

    _reply(reply_token, TextMessage(text="\n".join([
        "✅ 訂閱設定完成！",
        "",
        f"📍 地點：{sub.work_place_names.replace(',', '、')}",
        f"👔 官等：{'、'.join(type_names) or '不限'}",
        f"🗂 職系：{sub.sysnam_grp_name}" + (f"（{sub.sysnam_names.replace(',','、')}）" if sub.sysnam_names else ""),
        f"📊 職等：{grade_str}",
        f"🔍 關鍵字：{sub.keywords or '不限'}",
        "",
        "傳任何訊息即可查詢最新職缺。",
    ])))


# ── 步驟處理器 ────────────────────────────────────────────────────────────────

def _handle_location_step(user_id: str, text: str, reply_token: str):
    pending = _conv[user_id].setdefault("pending", {})
    if text == "不限地區":
        pending.update({"work_place_codes": "", "work_place_names": "不限"})
    else:
        codes, names = _parse_location_text(text)
        if not codes:
            # 無法解析 → 提示重新輸入
            _reply(reply_token, TextMessage(
                text=(
                    f"❌ 無法識別「{text}」\n\n"
                    "請輸入縣市名稱（如：臺北市,臺中市），\n"
                    "或點「不限地區」："
                ),
                quick_reply=QuickReply(items=[
                    QuickReplyItem(action=MessageAction(label="不限地區", text="不限地區")),
                ]),
            ))
            return
        pending.update({"work_place_codes": codes, "work_place_names": names})
    _ask_rank_types(user_id, reply_token)


def _handle_rank_types_step(user_id: str, text: str, reply_token: str):
    pending = _conv[user_id].setdefault("pending", {})
    current_codes = [c for c in pending.get("rank_types", "").split(",") if c]

    if text == "不限官等":
        pending["rank_types"] = ""
        _ask_sysnam_grp(user_id, reply_token)
        return

    if text == "官等:確定":
        _ask_sysnam_grp(user_id, reply_token)
        return

    # 點選官等名稱（格式 "官等:薦任"）
    if text.startswith("官等:"):
        name = text[3:]
        code = next((c for c, n in _RANK_TYPE_NAMES.items() if n == name), None)
        if code:
            if code in current_codes:
                current_codes.remove(code)  # 取消選取
            else:
                current_codes.append(code)
            pending["rank_types"] = ",".join(current_codes)
    _ask_rank_types(user_id, reply_token)  # 刷新 Quick Reply 顯示


def _handle_sysnam_grp_step(user_id: str, text: str, reply_token: str):
    options = SYSNAM_GRP_OPTIONS
    selected = next((o for o in options if o["text"] == text), None)
    if selected is None:
        _ask_sysnam_grp(user_id, reply_token)
        return
    _conv[user_id].setdefault("pending", {}).update({
        "sysnam_grp":      selected["value"],
        "sysnam_grp_name": selected["text"],
    })
    # 如果選了大分類（不是不限），再詢問細項
    if selected["value"]:
        _ask_sysnam_names(user_id, reply_token)
    else:
        _conv[user_id]["pending"]["sysnam_names"] = ""
        _ask_rank_grade(user_id, reply_token)


def _handle_sysnam_names_step(user_id: str, text: str, reply_token: str):
    if text == _SKIP:
        _conv[user_id].setdefault("pending", {})["sysnam_names"] = ""
    else:
        # 直接存使用者輸入（逗號分隔職系名稱）
        names = ",".join([n.strip() for n in re.split(r"[\s、，,]+", text.strip()) if n.strip()])
        _conv[user_id].setdefault("pending", {})["sysnam_names"] = names
    _ask_rank_grade(user_id, reply_token)


def _handle_rank_grade_step(user_id: str, text: str, reply_token: str):
    lo, hi = _parse_grade_range(text)
    _conv[user_id].setdefault("pending", {}).update({
        "rank_grade_min": lo,
        "rank_grade_max": hi,
    })
    _ask_keywords(user_id, reply_token)


def _handle_keywords_step(user_id: str, text: str, reply_token: str):
    keywords = "" if text == _SKIP else text
    _conv[user_id].setdefault("pending", {})["keywords"] = keywords
    _save_and_confirm(user_id, reply_token)


# ── 主要 handler ──────────────────────────────────────────────────────────────

@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event: MessageEvent) -> None:
    user_id     = event.source.user_id
    text        = event.message.text.strip()
    reply_token = event.reply_token
    step        = _conv.get(user_id, {}).get("step", "idle")

    logger.info(f"LINE user={user_id[:8]} step={step!r} text={text[:50]!r}")

    # 記錄使用者
    try:
        upsert_line_user(user_id)
    except Exception:
        pass

    # ── 全域指令（優先於對話狀態）────────────────────────────────────────────
    if text in _TRIGGERS_SUBSCRIBE:
        _conv[user_id] = {"step": "setup_location", "pending": {}}
        _ask_location(user_id, reply_token)
        return

    if text in _TRIGGERS_MY_SUB:
        sub = get_subscription("line", user_id)
        if not sub:
            _reply(reply_token, TextMessage(
                text="尚未設定訂閱條件。\n\n輸入「訂閱」開始設定。"
            ))
        else:
            rank_types = sub.rank_types
            type_names = [_RANK_TYPE_NAMES[c] for c in ["1","2","3","4"] if c in rank_types.split(",")]
            grade_min, grade_max = sub.rank_grade_min, sub.rank_grade_max
            if grade_min == 0 and grade_max == 0:
                grade_str = "不限"
            elif grade_min == grade_max:
                grade_str = f"{grade_min}職等"
            else:
                grade_str = f"{grade_min}-{grade_max}職等"
            _reply(reply_token, TextMessage(text="\n".join([
                "📋 目前訂閱設定",
                "",
                f"📍 地點：{sub.work_place_names.replace(',', '、') or '不限'}",
                f"👔 官等：{'、'.join(type_names) or '不限'}",
                f"🗂 職系：{sub.sysnam_grp_name or '不限'}" + (f"（{sub.sysnam_names.replace(',','、')}）" if sub.sysnam_names else ""),
                f"📊 職等：{grade_str}",
                f"🔍 關鍵字：{sub.keywords or '不限'}",
                "",
                "輸入「訂閱」可重新設定。",
            ])))
        return

    if text in _TRIGGERS_DEL_SUB:
        delete_subscription("line", user_id)
        _conv.pop(user_id, None)
        _reply(reply_token, TextMessage(
            text="✅ 已刪除訂閱設定。\n輸入「訂閱」可重新設定。"
        ))
        return

    if text in _TRIGGERS_HELP:
        _reply(reply_token, TextMessage(text=_HELP_TEXT))
        return

    if text in _TRIGGERS_RESULTS:
        result, _ = handle_user_query("line", user_id)   # 不帶 keyword → 使用訂閱關鍵字
        _reply(reply_token, TextMessage(text=result))
        return

    # ── 對話狀態機 ────────────────────────────────────────────────────────────
    if step == "setup_location":
        _handle_location_step(user_id, text, reply_token)
        return

    if step == "setup_rank_types":
        _handle_rank_types_step(user_id, text, reply_token)
        return

    if step == "setup_sysnam_grp":
        _handle_sysnam_grp_step(user_id, text, reply_token)
        return

    if step == "setup_sysnam_names":
        _handle_sysnam_names_step(user_id, text, reply_token)
        return

    if step == "setup_rank_grade":
        _handle_rank_grade_step(user_id, text, reply_token)
        return

    if step == "setup_keywords":
        _handle_keywords_step(user_id, text, reply_token)
        return

    # ── 預設：以輸入文字為關鍵字，合併訂閱其他條件查詢 ────────────────────────
    result, _ = handle_user_query("line", user_id, keyword=text)
    _reply(reply_token, TextMessage(text=result))
