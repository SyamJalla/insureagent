"""FAQ tool — industry-general knowledge from the Chroma vector store.

ctx is unused today; it becomes the access_level retrieval filter when the
knowledge pipeline v2 (metadata-aware corpus) lands.
"""
from functools import lru_cache

import chromadb

from app.auth.models import RequestContext
from app.config import get_settings


@lru_cache
def _collection():
    s = get_settings()
    client = chromadb.PersistentClient(path=str(s.vector_db_path))
    return client.get_collection(name=s.faq_collection_name)


def search_faq(ctx: RequestContext, query: str):
    results = _collection().query(query_texts=[query], n_results=3)
    out = []
    for doc, meta in zip(results["documents"][0], results["metadatas"][0]):
        out.append({
            "question": meta.get("question", ""),
            "answer": meta.get("answer", doc),
            "source": "insuranceQA-v2 (industry-general)",
        })
    return out
