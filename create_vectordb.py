"""Build (or rebuild) the FAQ vector store — ChromaDB.

Derived data: the corpus comes from Hugging Face (deccan-ai/insuranceQA-v2),
so this store is always rebuildable. Running twice is safe and deterministic:
the FAQ collection is dropped and re-ingested; the user_memory collection in
the same store is real user data and is never touched.

Run with the app STOPPED (or restart it after): the app caches a handle to
the collection (app/tools/faq_tools.py), and a rebuild invalidates it.

Run:  python create_vectordb.py
"""
import hashlib
from datetime import date

import chromadb
import pandas as pd
from datasets import load_dataset
from tqdm import tqdm

# Matches settings.faq_collection_name — kept literal so this offline build
# script runs without .env / app config.
COLLECTION_NAME = "insurance_data_FAQ_collection"
PERSIST_DIRECTORY = "datasources/vector_database"
DATASET_NAME = "deccan-ai/insuranceQA-v2"
# Knowledge-coverage decision: raising this changes what retrieval returns.
# Change only alongside a golden-set eval run (the FAQ cases are the gate).
SAMPLE_SIZE = 500
SAMPLE_SEED = 42
BATCH_SIZE = 100


def build_faq_dataframe() -> pd.DataFrame:
    ds = load_dataset(DATASET_NAME)
    df = pd.concat([split.to_pandas() for split in ds.values()], ignore_index=True)
    df["combined"] = "Question: " + df["input"] + " \n Answer:  " + df["output"]
    return df


def _stable_id(row_text: str) -> str:
    """Content-based ID (hash of question+answer): growth or resampling never
    reassigns an existing document's ID, so future incremental upserts stay
    possible. The same question can appear with several answers in this
    corpus, which is why the answer is part of the identity."""
    return hashlib.sha1(row_text.encode("utf-8")).hexdigest()[:16]


def rebuild_faq_collection(df: pd.DataFrame) -> None:
    client = chromadb.PersistentClient(path=PERSIST_DIRECTORY)
    if any(c.name == COLLECTION_NAME for c in client.list_collections()):
        client.delete_collection(COLLECTION_NAME)
        print(f"dropped existing collection {COLLECTION_NAME}")
    collection = client.create_collection(
        name=COLLECTION_NAME,
        metadata={
            "dataset": DATASET_NAME,
            "sample_size": SAMPLE_SIZE,
            "sample_seed": SAMPLE_SEED,
            "built_on": date.today().isoformat(),
        },
    )

    sample = df.sample(SAMPLE_SIZE, random_state=SAMPLE_SEED).reset_index(drop=True)
    deduped = sample.drop_duplicates(subset="combined")
    if len(deduped) < len(sample):
        print(f"dropped {len(sample) - len(deduped)} exact-duplicate rows")

    for start in tqdm(range(0, len(deduped), BATCH_SIZE)):
        batch = deduped.iloc[start:start + BATCH_SIZE]
        collection.add(  # default embeddings (sentence-transformers MiniLM)
            ids=[_stable_id(t) for t in batch["combined"]],
            documents=batch["combined"].tolist(),
            metadatas=[
                {"question": q, "answer": a}
                for q, a in zip(batch["input"], batch["output"])
            ],
        )
    print(f"{COLLECTION_NAME}: {collection.count()} items")


def main() -> None:
    df = build_faq_dataframe()
    print(f"faq dataset loaded: {df.shape}")
    rebuild_faq_collection(df)


if __name__ == "__main__":
    main()
