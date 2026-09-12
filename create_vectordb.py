"""Build the FAQ vector store (ChromaDB).

Enterprise data seeding moved to scripts/seed_enterprise.py (Postgres).
Run:  python create_vectordb.py
"""
import utils


def main():
    collection_name = "insurance_data_FAQ_collection"
    persist_directory = "datasources/vector_database"
    df = utils.create_faq_dataset()
    print(f"faq_dataset created: {df.shape}")
    chroma_client = utils.create_chroma_client(persist_directory)
    collection = utils.create_chroma_vector_db(chroma_client, collection_name)
    utils.add_data_to_collection(df, collection)
    print("FAQ data added to vector store")


if __name__ == "__main__":
    main()
