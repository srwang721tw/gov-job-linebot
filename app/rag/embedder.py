from langchain_huggingface import HuggingFaceEmbeddings

from app.utils.config import EMBEDDING_MODEL

_embedder: HuggingFaceEmbeddings | None = None


def get_embedder() -> HuggingFaceEmbeddings:
    global _embedder
    if _embedder is None:
        _embedder = HuggingFaceEmbeddings(
            model_name=EMBEDDING_MODEL,
            model_kwargs={"device": "cpu"},
            encode_kwargs={"normalize_embeddings": True},
        )
    return _embedder
