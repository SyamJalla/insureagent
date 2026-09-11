import os
import sys

# Add backend to path
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from db.vector_db import create_faq_dataset, create_chroma_client, create_chroma_vector_db, add_data_to_collection
from db.sql_db import generate_sample_data, setup_insurance_database

def main():
    collection_name = 'insurance_data_FAQ_collection'
    # Resolve paths relative to backend/ regardless of CWD
    _backend_dir = os.path.join(os.path.dirname(__file__), '..')
    persist_directory = os.path.normpath(os.path.join(_backend_dir, 'datasources', 'vector_database'))
    db_path = os.path.normpath(os.path.join(_backend_dir, 'datasources', 'database', 'insurance_support.db'))
    
    df = create_faq_dataset()
    print('faq_dataset created')
    print(df.shape)
    
    chroma_client = create_chroma_client(persist_directory)
    collection = create_chroma_vector_db(chroma_client, collection_name)
    print('vectordb created')
    
    add_data_to_collection(df, collection)
    print('added data to vectordb')
    
    sample_data = generate_sample_data(random_state=42)
    print('sample_data created')
    
    setup_insurance_database(sample_data, db_path)
    print('added data to database')

if __name__ == '__main__':
    main()
