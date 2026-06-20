"""Pydantic model representing a user's job-alert subscription.

A subscription is identified by the composite key
``(platform, platform_user_id)``.  Multi-select fields are stored as
comma-separated strings; an empty string means "no filter" (all values
match).  Grade fields use ``0`` to represent "no filter".
"""
from pydantic import BaseModel


class Subscription(BaseModel):
    """A user's saved job-search subscription across LINE or Telegram.

    Fields are grouped by subscription step:

    - **Identity**: platform + user ID pair.
    - **Location** (step 1): multi-select work locations.
    - **Rank** (steps 2–3): rank category codes and grade range.
    - **Job series** (steps 4–5): series group and specific series names.
    - **Keywords** (step 6): free-text matching terms.
    """

    # Identity
    platform: str
    """Platform identifier: ``"line"`` or ``"telegram"``."""
    platform_user_id: str
    """Platform-specific user ID (LINE ``U...`` string or Telegram integer
    cast to string)."""

    # Work location (step 1, multi-select)
    work_place_codes: str = ""
    """Comma-separated DGPA location codes, e.g. ``"10,42"``.
    Empty string = all locations."""
    work_place_names: str = ""
    """Comma-separated human-readable location names, e.g. ``"臺北市,臺中市"``."""

    # Rank category (step 2, multi-select)
    rank_types: str = ""
    """Comma-separated rank-type codes, e.g. ``"2,3"``
    (``1``=簡任, ``2``=薦任, ``3``=委任, ``4``=其他).
    Empty string = all rank types."""

    # Grade range (step 3)
    rank_grade_min: int = 0
    """Minimum desired grade (``0`` = no lower bound)."""
    rank_grade_max: int = 0
    """Maximum desired grade (``0`` = no upper bound)."""

    # Job series (steps 4–5)
    sysnam_grp: str = ""
    """Series group code: ``""`` (all), ``"A"`` (行政類), ``"B"`` (技術類)."""
    sysnam_grp_name: str = ""
    """Human-readable series group: ``"不限"``, ``"行政類"``, or ``"技術類"``."""
    sysnam_names: str = ""
    """Comma-separated job-series names, e.g. ``"綜合行政,社會行政"``.
    Empty string = all series within the group."""

    # Keywords (step 6)
    keywords: str = ""
    """Comma- or space-separated search keywords.  Matched against
    ``title``, ``org_name``, ``qualifications``, and ``work_items`` via
    ``pg_trgm`` similarity (PostgreSQL) or ``LIKE`` (SQLite)."""
