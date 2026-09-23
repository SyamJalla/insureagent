# InsureAgent app image. Build from a CLEAN committed tree (the image
# copies the working tree). Models + FAQ store are baked at BUILD time —
# the running container never downloads anything but OpenAI API calls.
FROM python:3.11-slim
WORKDIR /app

# Dependencies first, alone — layer caching: a code-only change skips this
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Application code
COPY app/ app/
COPY prompts/ prompts/
COPY scripts/ scripts/
COPY create_vectordb.py .

# Bake: ONNX injection classifier + MiniLM (~800 MB), then the FAQ store
# (downloads the HuggingFace corpus once, embeds 500 docs)
RUN python scripts/fetch_models.py
RUN python create_vectordb.py

COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
EXPOSE 8000
ENTRYPOINT ["/entrypoint.sh"]
