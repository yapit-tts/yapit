FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app
COPY pyproject.toml README.md ./
RUN uv pip install ".[gateway]" --no-cache-dir --system

COPY yapit/ /app/yapit

ARG GIT_COMMIT=unknown
RUN echo "$GIT_COMMIT" > /app/version.txt

RUN useradd -m -u 1000 appuser \
    && mkdir -p /data/audio_cache /data/document_cache /data/extraction_cache /data/gateway /data/images \
    && chown -R appuser:appuser /app /data

USER appuser
ENV PYTHONUNBUFFERED=1 PYTHONPATH=/app/gateway SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt
EXPOSE 8000
CMD ["uvicorn", "yapit.gateway:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*", "--timeout-keep-alive", "65"]
