FROM python:3.12-slim

ARG EMBEDDING_MODEL
ENV PYTHONUNBUFFERED=1 FASTEMBED_CACHE_PATH=/opt/fastembed

WORKDIR /app
COPY api/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Baking the model into the image means a cold start doesn't have to download it.
RUN python -c "import sys; from fastembed import TextEmbedding; TextEmbedding(model_name=sys.argv[1])" "$EMBEDDING_MODEL" \
    && chmod -R a+rX /opt/fastembed

COPY api/ api/

RUN useradd --create-home app
USER app

CMD ["sh", "-c", "exec uvicorn api.main:app --host 0.0.0.0 --port ${PORT:-8080}"]
