from fastapi import APIRouter, HTTPException
from api.schemas import ChatRequest, ChatResponse
import os
from core.config import create_client, create_logger, create_langfuse, logger_name
from db.vector_db import create_chroma_client, create_chroma_vector_db
from agents.graph import run_workflow

router = APIRouter()

# Initialize global clients for the router
try:
    openai_api_key = os.getenv('OPENAI_API_KEY')
    if not openai_api_key:
        raise ValueError('OPENAI_API_KEY not found in environment')
    
    logger = create_logger(logger_name)
    langfuse_client = create_langfuse()
    openai_client = create_client(openai_api_key)
    
    # Resolve path relative to backend/ regardless of server launch CWD
    _backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    persist_directory = os.path.join(_backend_dir, 'datasources', 'vector_database')
    collection_name = 'insurance_data_FAQ_collection'
    chroma_client = create_chroma_client(persist_directory)
    collection = chroma_client.get_collection(name=collection_name)
    
    # Workflow App
    workflow_app = run_workflow(
        client=openai_client,
        logger=logger,
        langfuse=langfuse_client,
        collection=collection
    )
except Exception as e:
    print(f'Error initializing dependencies: {e}')
    workflow_app = None

@router.post('/chat', response_model=ChatResponse)
async def chat_endpoint(request: ChatRequest):
    if not workflow_app:
        raise HTTPException(status_code=500, detail='Workflow app not initialized')
        
    initial_state = {
        'n_iteration': 0,
        'messages': [],
        'user_input': request.query,
        'user_intent': '',
        'claim_id': '',
        'next_agent': 'supervisor_agent',
        'extracted_entities': {},
        'database_lookup_result': {},
        'requires_human_escalation': False,
        'escalation_reason': '',
        'billing_amount': None,
        'payment_method': None,
        'billing_frequency': None,
        'invoice_date': None,
        'conversation_history': f'User: {request.query}',
        'task': 'Help user with their query',
        'final_answer': ''
    }
    
    try:
        final_state = workflow_app.invoke(initial_state)
        final_answer = final_state.get('final_answer', 'No final answer generated.')
        return ChatResponse(response=final_answer)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
