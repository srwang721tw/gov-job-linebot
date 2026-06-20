"""Pydantic model representing a single DGPA job posting.

All date fields are stored as ISO 8601 strings (``"YYYY-MM-DD"``).
A ``rank_grade_min`` or ``rank_grade_max`` value of ``0`` indicates
that the grade is unspecified (``不分職等``) or could not be parsed.
"""
from pydantic import BaseModel


class Job(BaseModel):
    """A civil-service job posting scraped from the DGPA job board.

    Fields are grouped by source:

    - **Identification**: always populated from the list page URL.
    - **List-page fields**: parsed from the GridView table row.
    - **Detail-page fields**: populated only when ``fetch_detail=True``.
    - **Date fields**: all ``YYYY-MM-DD`` strings.
    - **Search**: ``search_text`` concatenates key text fields for
      full-text indexing with ``pg_trgm``.
    """

    # Identification
    job_id: str
    """DGPA ``work_id`` URL parameter; used as the database primary key."""

    # List-page fields
    title: str = ""
    """Job title."""
    org_name: str = ""
    """Hiring agency name."""
    work_place: str = ""
    """Work location with numeric code prefix stripped (e.g. ``"臺北市"``)."""
    work_place_code: str = ""
    """DGPA dropdown value for the work location (e.g. ``"10"``)."""
    rank_type: str = ""
    """Raw rank/grade text from the site (e.g. ``"薦任第6至第9職等"``)."""
    rank_type_codes: str = ""
    """Inferred rank-type codes, comma-separated (``1``=簡任, ``2``=薦任,
    ``3``=委任, ``4``=其他)."""
    rank_grade_min: int = 0
    """Lowest grade number; ``0`` if unspecified or unparseable."""
    rank_grade_max: int = 0
    """Highest grade number; ``0`` if unspecified or unparseable."""
    job_series: str = ""
    """Job series name (e.g. ``"綜合行政"``)."""
    sysnam_grp: str = ""
    """Series group: ``""`` (unknown), ``"A"`` (行政類), ``"B"`` (技術類)."""

    # Detail-page fields (populated when fetch_detail=True)
    regular_slots: int = 0
    """Number of regular (正取) openings."""
    alternate_slots: int = 0
    """Number of alternate (候補) openings."""
    qualifications: str = ""
    """Qualification requirements (``PLWORK_QUALITY`` element)."""
    work_items: str = ""
    """Work description (``PLWORK_ITEM`` element)."""
    work_address: str = ""
    """Physical work address (``PLWORK_ADDRESS`` element)."""

    # Date fields (all YYYY-MM-DD)
    publish_date: str = ""
    """Announcement date."""
    deadline_start: str = ""
    """Application period start date."""
    deadline_end: str = ""
    """Application deadline; used for DB expiry filtering."""

    # Full-text search
    search_text: str = ""
    """Concatenation of title, org_name, qualifications, and work_items;
    indexed with a GIN ``pg_trgm`` index for similarity search."""

    # URL
    job_url: str = ""
    """Full URL of the job detail page."""
