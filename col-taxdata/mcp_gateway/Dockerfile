FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY gateway.py server.py runtime_smoke.py /app/
RUN python3 /app/runtime_smoke.py \
    && rm /app/runtime_smoke.py \
    && useradd --create-home --uid 10001 --shell /usr/sbin/nologin mcp

USER mcp

ENV MCP_TRANSPORT=streamable-http \
    MCP_PORT=8000 \
    MCP_PATH=/mcp

EXPOSE 8000

CMD ["python3", "/app/server.py"]
