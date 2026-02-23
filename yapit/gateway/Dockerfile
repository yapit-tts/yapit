FROM python:3.12-slim

RUN rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml README.md ./
RUN pip install uv --no-cache-dir && uv pip install ".[gateway]" --no-cache-dir --system

ENV PLAYWRIGHT_BROWSERS_PATH=/opt/ms-playwright
RUN playwright install --with-deps chromium

COPY yapit/ /app/yapit

ARG GIT_COMMIT=unknown
RUN echo "$GIT_COMMIT" > /app/version.txt

RUN useradd -m -u 1000 appuser \
    && mkdir -p /data/audio_cache /data/document_cache /data/extraction_cache /data/gateway /data/images \
    && chown -R appuser:appuser /opt/ms-playwright /app /data

USER appuser
ENV PYTHONUNBUFFERED=1 PYTHONPATH=/app/gateway SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt
EXPOSE 8000
CMD ["uvicorn", "yapit.gateway:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*", "--timeout-keep-alive", "65"]
