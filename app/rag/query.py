"""
Semantic search using ChromaDB + HuggingFace embeddings.
No LLM — results are formatted via template.
"""
from app.rag.vector_store import search_jobs
from app.utils.config import TOP_K_RESULTS
from app.utils.logger import logger


def rag_query(user_query: str) -> str:
    try:
        docs = search_jobs(user_query, k=TOP_K_RESULTS)
    except Exception as e:
        logger.error(f"Vector search error: {e}")
        return "查詢時發生錯誤，請稍後再試。"

    if not docs:
        return "目前沒有找到符合條件的職缺，請嘗試其他關鍵字，例如：地點、機關名稱或專業技能。"

    lines = [f"為您找到 {len(docs)} 個相關職缺：\n"]
    for i, doc in enumerate(docs, 1):
        m = doc.metadata
        title    = m.get("title", "（未知）")
        agency   = m.get("agency", "")
        location = m.get("location", "")
        deadline = m.get("deadline", "")
        url      = m.get("detail_url", "")

        block = [f"【{i}】{title}"]
        if agency:
            block.append(f"機關：{agency}")
        if location:
            block.append(f"地點：{location}")
        if deadline:
            block.append(f"截止：{deadline}")
        if url:
            block.append(f"連結：{url}")

        lines.append("\n".join(block))

    return "\n\n".join(lines)
