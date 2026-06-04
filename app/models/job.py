"""
職缺資料模型（v3）。
欄位同時對應列表頁與詳細頁的資料，由爬蟲在合併後建立。
"""
from pydantic import BaseModel


class Job(BaseModel):
    # ── 基本識別 ────────────────────────────────────────────────────────────────
    job_id: str                      # DGPA work_id（URL 參數）

    # ── 列表頁欄位 ──────────────────────────────────────────────────────────────
    title: str = ""                  # 職稱
    org_name: str = ""               # 機關名稱
    work_place: str = ""             # 工作地點（已清除代碼前綴）
    work_place_code: str = ""        # 工作地點代碼（DGPA dropdown value）
    rank_type: str = ""              # 官等（簡任/薦任/委任/其他）
    job_series: str = ""             # 職系名稱（e.g. 綜合行政）
    sysnam_grp: str = ""             # 職系大分類：'' / 'A'（行政）/ 'B'（技術）

    # ── 詳細頁欄位（fetch_detail=True 時填入）──────────────────────────────────
    person_kind: str = ""            # 人員區分名稱（e.g. 聘用人員）
    person_kind_code: str = ""       # 人員區分代碼
    regular_slots: int = 0           # 正取名額（TODO: 確認 DGPA element ID）
    alternate_slots: int = 0         # 候補名額（TODO: 確認 DGPA element ID）
    qualifications: str = ""         # 應徵資格條件
    work_items: str = ""             # 工作說明
    work_address: str = ""           # 詳細工作地址
    contact_method: str = ""         # 聯絡方式
    apply_method: str = ""           # 應徵方式

    # ── 日期欄位 ────────────────────────────────────────────────────────────────
    publish_date: str = ""           # 公告日（民國年字串）
    deadline: str = ""               # 有效期間原始字串 "115/05/30~115/06/03"
    deadline_end_iso: str = ""       # 截止日 ISO 格式 "2026-06-03"（供 DB 篩選）

    # ── 連結 ────────────────────────────────────────────────────────────────────
    job_url: str = ""                # 詳細頁完整 URL
