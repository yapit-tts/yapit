FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends wget && rm -rf /var/lib/apt/lists/* \
    && ARCH="$(dpkg --print-architecture)" \
    && wget -q "https://github.com/jgm/pandoc/releases/download/3.9.0.2/pandoc-3.9.0.2-1-$ARCH.deb" \
    && dpkg -i "pandoc-3.9.0.2-1-$ARCH.deb" \
    && rm "pandoc-3.9.0.2-1-$ARCH.deb"

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv export --frozen --no-dev --no-emit-project -o requirements.txt \
    && uv pip install -r requirements.txt --no-cache-dir --system \
    && rm requirements.txt pyproject.toml uv.lock

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
