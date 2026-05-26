from pydantic import BaseModel


class Job(BaseModel):
    job_id: str
    title: str
    agency: str
    location: str = ""
    job_series: str = ""
    rank_type: str = ""
    description: str = ""
    requirement: str = ""
    contact: str = ""
    apply_method: str = ""
    note: str = ""
    publish_date: str = ""
    deadline: str = ""
    detail_url: str = ""
