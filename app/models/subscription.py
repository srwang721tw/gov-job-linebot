"""
使用者訂閱條件模型（v3.1）。
同時支援 LINE 和 Telegram（以 platform + platform_user_id 識別）。

work_place_codes / rank_types / sysnam_names 均為逗號分隔字串，空字串表示不限。
rank_grade_min / rank_grade_max = 0 表示不限職等。
"""
from pydantic import BaseModel


class Subscription(BaseModel):
    platform: str                    # 'line' | 'telegram'
    platform_user_id: str            # LINE: 'U...' | Telegram: str(int)

    # ── 工作地點（可多選）────────────────────────────────────────────────────────
    work_place_codes: str = ""       # 逗號分隔代碼，如 "10,42"（空=不限）
    work_place_names: str = ""       # 逗號分隔名稱，如 "臺北市,臺中市"

    # ── 官等類別（可多選）────────────────────────────────────────────────────────
    rank_types: str = ""             # 逗號分隔代碼，如 "2,3"（1=簡任,2=薦任,3=委任,4=其他，空=不限）

    # ── 職務列等區間 ─────────────────────────────────────────────────────────────
    rank_grade_min: int = 0          # 最低職等（0=不限）
    rank_grade_max: int = 0          # 最高職等（0=不限）

    # ── 職系 ─────────────────────────────────────────────────────────────────────
    sysnam_grp: str = ""             # 職系大分類：'' / 'A'（行政）/ 'B'（技術）
    sysnam_grp_name: str = ""        # 職系大分類名稱：'不限' / '行政類' / '技術類'
    sysnam_names: str = ""           # 逗號分隔職系名稱，如 "綜合行政,社會行政"（空=不限）

    # ── 關鍵字（逗號/空格分隔，不傳給爬蟲）─────────────────────────────────────
    keywords: str = ""               # 比對職稱、機關名稱、資格條件、工作項目
