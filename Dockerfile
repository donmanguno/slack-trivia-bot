FROM python:3.12-slim

# Links this image to the GitHub repository (used by ghcr.io)
LABEL org.opencontainers.image.source="https://github.com/donmanguno/slack-trivia-bot"

# Prevents .pyc files and enables unbuffered stdout/stderr for Docker logs
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install curl for health checks
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

# Install dependencies first (layer cached unless requirements.txt changes)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY app.py .
COPY health_check.py .
COPY trivia/ trivia/
COPY data/ data/

# The SQLite database lives in /data so it can be persisted via a named volume.
# Set DB_PATH in your environment or docker run command to override.
ENV DB_PATH=/data/trivia.db
RUN mkdir /data

VOLUME ["/data"]

# Health check configuration:
# - start-period: 20s (grace period during startup, monitor won't mark unhealthy)
# - interval: 5s (check frequently to catch stuck state quickly)
# - timeout: 3s (max time to wait for response)
# - retries: 2 (2 failures = 10s to mark unhealthy)
# Total: After 20s startup grace + 10s of failures = 30s before restart
HEALTHCHECK --interval=5s --timeout=3s --retries=2 --start-period=20s \
    CMD curl -f http://localhost:8080/health || exit 1

CMD ["python", "app.py"]
