FROM nvidia/cuda:12.0.1-cudnn8-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
      python3.10 python3.10-venv python3-pip python3-setuptools \
      espeak-ng tini curl ca-certificates && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY . .

RUN python3.10 -m venv /opt/venv && \
    /opt/venv/bin/pip install --upgrade pip wheel && \
    /opt/venv/bin/pip install -r requirements.txt

RUN useradd -m -u 1000 appuser && \
    mkdir -p /app/.cache && \
    chown -R appuser:appuser /app && \
    chmod -R 755 /app

ENV PATH="/opt/venv/bin:$PATH" \
    HF_HOME=/app/.cache \
    OMP_THREADS=4

USER appuser

ENTRYPOINT ["/usr/bin/tini","--"]
CMD ["python","worker.py"]

