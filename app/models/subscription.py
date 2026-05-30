from pydantic import BaseModel


class Subscription(BaseModel):
    line_user_id: str
    work_place_code: str = ""
    work_place_name: str = ""
    person_kind_code: str = ""
    person_kind_name: str = ""
    title_keyword: str = ""
    org_keyword: str = ""
