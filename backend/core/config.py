import logging
import os
from dotenv import load_dotenv
from opentelemetry import trace
from langfuse import Langfuse
from openai import OpenAI

# Load .env from the backend/ directory (or any parent) at import time
load_dotenv(dotenv_path=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env'))

tracer = trace.get_tracer(__name__)
logger_name='insurance_agent.log'

def create_langfuse():
    return Langfuse(
        public_key=os.getenv('LANGFUSE_PUBLIC_KEY'),
        secret_key=os.getenv('LANGFUSE_SECRET_KEY'),
        host=os.getenv('LANGFUSE_BASE_URL')
    )

def create_client(openai_api_key):
    client = OpenAI(api_key=openai_api_key)
    return client

def create_logger(logger_name):
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(logger_name),
            logging.StreamHandler()
        ]
    )
    logger = logging.getLogger(__name__)
    return logger
