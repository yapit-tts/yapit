FROM python:3.10-slim

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends espeak-ng tini && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY . .

RUN python -m venv /opt/venv && \
    /opt/venv/bin/pip install --upgrade pip wheel && \
    /opt/venv/bin/pip install -r workers/kokoro_cpu/requirements.txt

ENV PATH="/opt/venv/bin:$PATH" HF_HOME=/app/.cache OMP_THREADS=2
ENTRYPOINT ["/usr/bin/tini","--"]
CMD ["python","kokoro_worker.py"]
