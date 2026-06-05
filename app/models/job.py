"""
職缺資料模型（v3.1）。

所有日期均以 YYYY-MM-DD 字串儲存。
rank_grade_min / rank_grade_max = 0 表示無法解析或不分職等。
"""
from pydantic import BaseModel


class Job(BaseModel):
    # ── 基本識別 ────────────────────────────────────────────────────────────────
    job_id: str                      # DGPA work_id（URL 參數）

    # ── 列表頁欄位 ──────────────────────────────────────────────────────────────
    title: str = ""                  # 職稱
    org_name: str = ""               # 機關名稱
    work_place: str = ""             # 工作地點（已清除代碼前綴，如「臺北市」）
    work_place_code: str = ""        # 工作地點代碼（DGPA dropdown value）
    rank_type: str = ""              # 官等原始文字（如「薦任第6至第9職等」）
    rank_type_codes: str = ""        # 推算代碼，逗號分隔（1=簡任,2=薦任,3=委任,4=其他）
    rank_grade_min: int = 0          # 最低職等（0=無法解析）
    rank_grade_max: int = 0          # 最高職等（0=無法解析）
    job_series: str = ""             # 職系名稱（如「綜合行政」）
    sysnam_grp: str = ""             # 職系大分類：'' / 'A'（行政）/ 'B'（技術）

    # ── 詳細頁欄位（fetch_detail=True 時填入）──────────────────────────────────
    regular_slots: int = 0           # 正取名額
    alternate_slots: int = 0         # 候補名額
    qualifications: str = ""         # 資格條件（PLWORK_QUALITY）
    work_items: str = ""             # 工作項目（PLWORK_ITEM）
    work_address: str = ""           # 詳細工作地址（PLWORK_ADDRESS）

    # ── 日期欄位（均為 YYYY-MM-DD）──────────────────────────────────────────────
    publish_date: str = ""           # 公告日
    deadline_start: str = ""         # 受理起始日
    deadline_end: str = ""           # 截止日（供 DB 篩選）

    # ── 全文搜尋 ────────────────────────────────────────────────────────────────
    search_text: str = ""            # title+org_name+qualifications+work_items（供 pg_trgm）

    # ── 連結 ────────────────────────────────────────────────────────────────────
    job_url: str = ""                # 詳細頁完整 URL
