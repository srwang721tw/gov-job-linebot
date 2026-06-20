"""Shared text-formatting helpers for rank types, grade labels, and punctuation.

Centralises logic that was previously duplicated across ``line_service``,
``telegram_service``, and ``query_service``.
"""

RANK_TYPE_NAMES = {"1": "簡任", "2": "薦任", "3": "委任", "4": "其他"}
"""Mapping from rank-type code to Chinese display name."""


def rank_names(codes: str) -> list[str]:
    """Convert comma-separated rank-type codes to ordered display names.

    Preserves the canonical ordering 簡任 → 薦任 → 委任 → 其他 regardless
    of the order in ``codes``.

    Args:
        codes: Comma-separated rank-type code string, e.g. ``"3,2"``.

    Returns:
        List of Chinese rank-type names in canonical order, e.g.
        ``["薦任", "委任"]`` for input ``"3,2"``.

    Example:
        >>> rank_names("2,3")
        ['薦任', '委任']
    """
    return [RANK_TYPE_NAMES[c] for c in ["1", "2", "3", "4"] if c in codes.split(",")]


def grade_label(mn: int, mx: int, zero_label: str = "不分職等") -> str:
    """Format a grade range as a human-readable string.

    Args:
        mn: Minimum grade number.
        mx: Maximum grade number.
        zero_label: Label returned when both ``mn`` and ``mx`` are ``0``
            (unspecified).  Defaults to ``"不分職等"``.

    Returns:
        - ``zero_label`` when both are ``0``.
        - ``"N職等"`` when ``mn == mx`` (single grade).
        - ``"N-M職等"`` when ``mn != mx`` (range).

    Example:
        >>> grade_label(5, 9)
        '5-9職等'
        >>> grade_label(9, 9)
        '9職等'
        >>> grade_label(0, 0)
        '不分職等'
    """
    if mn == 0 and mx == 0:
        return zero_label
    return f"{mn}職等" if mn == mx else f"{mn}-{mx}職等"


def comma_to_jap(text: str) -> str:
    """Replace ASCII commas with the full-width Japanese comma (、).

    Args:
        text: String with ASCII commas as list separators.

    Returns:
        String with every ``,`` replaced by ``"、"``.

    Example:
        >>> comma_to_jap("臺北市,新北市")
        '臺北市、新北市'
    """
    return text.replace(",", "、")
