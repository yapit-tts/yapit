FROM python:3.12-slim

WORKDIR /app

# Install dependencies
COPY pyproject.toml README.md ./
RUN pip install uv --no-cache-dir && \
    uv pip install ".[runpod]" --no-cache-dir --system

# Copy application code
COPY yapit/ /app/yapit

# Set Python to unbuffered mode
ENV PYTHONUNBUFFERED=1

CMD ["python", "-m", "yapit.workers.processors.runpod"]