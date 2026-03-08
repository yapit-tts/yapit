FROM node:22-slim AS defuddle-bundle
WORKDIR /tmp/defuddle
COPY docker/defuddle/package*.json ./
RUN npm ci --omit=dev

FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app
COPY docker/defuddle/pyproject.toml ./
RUN uv pip install . --no-cache-dir --system

ENV PLAYWRIGHT_BROWSERS_PATH=/opt/ms-playwright
RUN playwright install --with-deps chromium

COPY --from=defuddle-bundle /tmp/defuddle/node_modules/defuddle/dist/index.full.js /app/defuddle_bundle.js
COPY docker/defuddle/app.py /app/app.py

RUN useradd -m -u 1000 appuser \
    && chown -R appuser:appuser /opt/ms-playwright /app

USER appuser
ENV PYTHONUNBUFFERED=1
EXPOSE 8001
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8001"]
