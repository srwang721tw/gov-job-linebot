from app.rag.query import rag_query


def handle_user_query(text: str) -> str:
    text = text.strip()
    if not text:
        return "請輸入您想查詢的職缺條件，例如：桃園 資訊 python"
    return rag_query(text)
