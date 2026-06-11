RANK_TYPE_NAMES = {"1": "簡任", "2": "薦任", "3": "委任", "4": "其他"}


def rank_names(codes: str) -> list[str]:
    """'1,2,3' → ['簡任', '薦任', '委任']（保持官等排序）"""
    return [RANK_TYPE_NAMES[c] for c in ["1", "2", "3", "4"] if c in codes.split(",")]


def grade_label(mn: int, mx: int, zero_label: str = "不分職等") -> str:
    """(5,9)→'5-9職等', (9,9)→'9職等', (0,0)→zero_label"""
    if mn == 0 and mx == 0:
        return zero_label
    return f"{mn}職等" if mn == mx else f"{mn}-{mx}職等"


def comma_to_jap(text: str) -> str:
    """'臺北市,新北市' → '臺北市、新北市'"""
    return text.replace(",", "、")
