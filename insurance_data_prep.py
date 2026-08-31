import utils


def main():
    collection_name="insurance_FAQ_collection"
    persist_directory = "/vectordb"
    query = "What does life insurance cover?"
    db_path='insurance_support.db'
    df=utils.create_faq_dataset()
    print("faq_dataset created")
    print(df.shape)
    df.head()
    chroma_client=utils.create_chroma_client(persist_directory)
    collection=utils.create_chroma_vector_db(chroma_client,collection_name)
    print("vectordb created")
    utils.add_data_to_collection(df,collection)
    print("added data to vectordb")
    results=utils.retrieve_data(query,chroma_client,collection_name)
    utils.print_query_results(results)
    sample_data=utils.generate_sample_data(random_state=42)
    print("sample_data created")
    utils.setup_insurance_database(sample_data,db_path)
    print("added data to vectordb")
    

if __name__ == "__main__":
    main()