# Jump Test API - FastAPI + CMJ/DJ analysis
FROM python:3.11-slim

WORKDIR /app

# Install dependencies (no venv needed in container)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code (use .dockerignore to exclude dev/local files)
COPY . .

# Build MkDocs so /documentation is available
RUN mkdocs build 2>/dev/null || true

# Optional: copy static admin/my-tests if not in api/
# (api/static is under api/ already)

ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

EXPOSE 8000

# Default: run API (override CMD for migrations or one-off scripts)
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
