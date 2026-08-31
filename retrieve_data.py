import utils

def main():
    collection_name="insurance_data_FAQ_collection"
    persist_directory = "datasources/vector_database"
    query = "What does life insurance cover?"
    db_path='datasources/database/insurance_support.db'    
    chroma_client=utils.create_chroma_client(persist_directory) 
    results=utils.retrieve_data(query,chroma_client,collection_name)
    utils.print_query_results(results)
    db_query= "SELECT * FROM customers LIMIT 5;"
    df_sql=utils.test_db(db_query,db_path)
    print(df_sql)

    
    

if __name__ == "__main__":
    main()