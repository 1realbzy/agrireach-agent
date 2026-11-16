FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY src/ ./src/
COPY data/ ./data/
COPY scripts/ ./scripts/
COPY .streamlit/ ./.streamlit/

RUN useradd --create-home --uid 10001 agrireach && \
    mkdir -p /var/lib/agrireach && \
    chown agrireach:agrireach /var/lib/agrireach
USER agrireach

CMD ["python", "-m", "uvicorn", "agrireach.api:app", "--host", "0.0.0.0", "--port", "8000", "--ws", "none", "--no-access-log"]
