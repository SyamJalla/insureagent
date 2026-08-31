from dotenv import load_dotenv
import os
import utils

# Load environment variables
load_dotenv()

LOGGER_NAME = "insurance_agent.log"


def main():

    # NEVER hardcode API keys
    openai_api_key = os.getenv("OPENAI_API_KEY")
    #phoenix_endpoint = os.getenv("PHOENIX_ENDPOINT")

    if not openai_api_key:
        raise ValueError("OPENAI_API_KEY not found in environment")

    logger = utils.create_logger(LOGGER_NAME)

    # Create tracer
    #tracer = utils.create_tracer(phoenix_endpoint)

    langfuse = utils.create_langfuse()

    # Create OpenAI client
    client = utils.create_client(openai_api_key)

    
    collection_name="insurance_data_FAQ_collection"
    persist_directory = "datasources/vector_database"
    chroma_client=utils.create_chroma_client(persist_directory)
    collection = chroma_client.get_collection(name=collection_name) 
    


    # Build workflow
    app = utils.run_workflow(
        client=client,
        logger=logger,
        langfuse=langfuse,
        collection=collection
    )

    test_query = "What is the premium of my auto insurance policy?" #POL000004
    #test_query = "In general, what does life insurance cover?"
    # test_query = "I want to talk to human executive"

    final_output = utils.run_test_query(test_query, app,langfuse)

    return final_output


if __name__ == "__main__":
    main()