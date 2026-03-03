FROM python:3.12-slim

# Prevents .pyc files and enables unbuffered stdout/stderr for Docker logs
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install dependencies first (layer cached unless requirements.txt changes)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY app.py .
COPY trivia/ trivia/

# The SQLite database lives in /data so it can be persisted via a named volume.
# Set DB_PATH in your environment or docker run command to override.
ENV DB_PATH=/data/trivia.db
RUN mkdir /data

VOLUME ["/data"]

CMD ["python", "app.py"]
