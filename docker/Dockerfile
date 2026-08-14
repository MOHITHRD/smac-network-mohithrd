# One image, four containers: your three agents, and the console that calls
# them. Each is the same code with a different command and port, which is what
# an agent is in deployment too - a process with an identity and an address.

FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app/src:/app/application

WORKDIR /app

# Dependencies first, so editing an agent does not reinstall them.
RUN pip install --no-cache-dir "mcp>=2.0.0,<3" "httpx>=0.27" "wandb>=0.18"

COPY src /app/src
COPY application /app/application

# Datasets and geocoding results are cached here, mounted as a volume so the
# 28 MB GTFS download survives a restart.
RUN mkdir -p /app/src/.cache

EXPOSE 8000 8001 8002 8080
CMD ["python", "/app/src/agents/charging.py"]
