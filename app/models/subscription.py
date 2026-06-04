"""
使用者訂閱條件模型（v3）。
同時支援 LINE 和 Telegram（以 platform + platform_user_id 識別）。
"""
from pydantic import BaseModel


class Subscription(BaseModel):
    platform: str                    # 'line' | 'telegram'
    platform_user_id: str            # LINE: 'U...' | Telegram: str(int)

    work_place_code: str = ""        # 工作地點代碼
    work_place_name: str = ""        # 工作地點名稱
    person_kind_code: str = ""       # 人員區分代碼
    person_kind_name: str = ""       # 人員區分名稱
    sysnam_grp: str = ""             # 職系大分類：'' / 'A' / 'B'
    sysnam_grp_name: str = ""        # 職系大分類名稱：'不限' / '行政類' / '技術類'
    title_keyword: str = ""          # 職缺名稱關鍵字
    org_keyword: str = ""            # 機關名稱關鍵字
