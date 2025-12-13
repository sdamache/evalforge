# Dockerfile for EvalForge Ingestion Service
# Built for Cloud Run deployment

FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Copy dependency specifications
COPY pyproject.toml ./

# Install dependencies from pyproject.toml
# Note: We install the package in editable mode to make src/ importable
RUN pip install --no-cache-dir -e .

# Install uvicorn (web server) - not in pyproject.toml but required for Cloud Run
RUN pip install --no-cache-dir uvicorn[standard]

# Copy application source code
COPY src/ ./src/

# Environment variables
# PORT is automatically injected by Cloud Run (defaults to 8080)
ENV PORT=8080

# Expose the port (informational - Cloud Run manages this)
EXPOSE ${PORT}

# Run uvicorn server bound to 0.0.0.0:$PORT
# Cloud Run requires binding to 0.0.0.0 (not localhost)
CMD uvicorn src.ingestion.main:app --host 0.0.0.0 --port ${PORT}
