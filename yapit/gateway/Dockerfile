FROM python:3.12-slim

RUN rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml README.md ./
RUN pip install uv --no-cache-dir && uv pip install ".[gateway]" --no-cache-dir --system

# Install Playwright browser and its system dependencies
RUN playwright install --with-deps chromium

COPY yapit/ /app/yapit

ARG GIT_COMMIT=unknown
RUN echo "$GIT_COMMIT" > /app/version.txt

ENV PYTHONUNBUFFERED=1 PYTHONPATH=/app/gateway
EXPOSE 8000
CMD ["uvicorn", "yapit.gateway:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
