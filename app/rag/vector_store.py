from typing import List

import chromadb
from langchain_chroma import Chroma
from langchain_core.documents import Document

from app.models.job import Job
from app.rag.embedder import get_embedder
from app.utils.config import CHROMA_COLLECTION, CHROMA_PATH, TOP_K_RESULTS
from app.utils.logger import logger


def _job_to_document(job: Job) -> Document:
    text = "\n".join(filter(None, [
        job.title,
        job.agency,
        job.location,
        job.job_series,
        job.rank_type,
        job.description,
        job.requirement,
    ]))
    return Document(
        page_content=text,
        metadata={
            "job_id": job.job_id,
            "title": job.title,
            "agency": job.agency,
            "location": job.location,
            "deadline": job.deadline,
            "detail_url": job.detail_url,
        },
    )


def get_vector_store() -> Chroma:
    return Chroma(
        collection_name=CHROMA_COLLECTION,
        embedding_function=get_embedder(),
        persist_directory=CHROMA_PATH,
    )


def rebuild_index(jobs: List[Job]) -> None:
    client = chromadb.PersistentClient(path=CHROMA_PATH)
    try:
        client.delete_collection(CHROMA_COLLECTION)
        logger.info("Deleted existing ChromaDB collection")
    except Exception:
        pass

    if not jobs:
        logger.warning("No jobs to index")
        return

    docs = [_job_to_document(j) for j in jobs]
    Chroma.from_documents(
        documents=docs,
        embedding=get_embedder(),
        collection_name=CHROMA_COLLECTION,
        persist_directory=CHROMA_PATH,
    )
    logger.info(f"Indexed {len(docs)} jobs into ChromaDB")


def search_jobs(query: str, k: int = TOP_K_RESULTS) -> List[Document]:
    vs = get_vector_store()
    return vs.similarity_search(query, k=k)
