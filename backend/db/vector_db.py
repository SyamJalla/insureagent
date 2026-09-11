import os
import pandas as pd
from datasets import load_dataset
import chromadb
from tqdm import tqdm

# Resolve the backend root from this file's location (db/vector_db.py → backend/)
_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def create_faq_dataset():
    ds = load_dataset('deccan-ai/insuranceQA-v2')
    df = pd.concat([split.to_pandas() for split in ds.values()], ignore_index=True)
    df['combined'] = 'Question: ' + df['input'] + '\nAnswer: ' + df['output']
    df.to_csv(os.path.join(_BACKEND_DIR, 'datasources', 'insurance_faq.csv'), index=False)
    return df

def create_chroma_client(persist_directory):
    return chromadb.PersistentClient(path=persist_directory)

def create_chroma_vector_db(chroma_client, collection_name):
    return chroma_client.get_or_create_collection(name=collection_name)

def add_data_to_collection(df, collection):
    df = df.sample(500, random_state=42).reset_index(drop=True)
    batch_size = 100
    for i in tqdm(range(0, len(df), batch_size)):
        batch_df = df.iloc[i:i+batch_size]
        collection.add(
            documents=batch_df['combined'].tolist(),
            metadatas=[{'question': q, 'answer': a} for q, a in zip(batch_df['input'], batch_df['output'])],
            ids=batch_df.index.astype(str).tolist()
        )
