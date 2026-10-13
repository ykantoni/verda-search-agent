FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY src/ ./src/

ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    VLLM_BASE_URL=http://vllm-router-service.vllm.svc.cluster.local/v1 \
    VLLM_MODEL=gemma-4-e4b \
    MCP_SERVER_URL=http://localhost:8001/mcp

EXPOSE 8000
CMD ["uvicorn", "agent.main:app", "--host", "0.0.0.0", "--port", "8000"]
