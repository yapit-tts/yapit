FROM bosonai/higgs-audio-vllm:latest

WORKDIR /app

RUN pip install --no-cache-dir runpod

# Set cache directories - can be overridden
ENV HF_HOME=/root/.cache/huggingface
ENV TRANSFORMERS_CACHE=/root/.cache/huggingface/transformers
ENV VLLM_DOWNLOAD_DIR=/root/.cache/vllm

COPY yapit/ /app/yapit

# Install curl for health checks
RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*

# Copy startup script
COPY yapit/workers/higgs_audio_v2/start.sh /app/start.sh
RUN chmod +x /app/start.sh

ENV ADAPTER_CLASS=yapit.workers.adapters.higgs_audio_v2.HiggsAudioV2Adapter
ENTRYPOINT ["/app/start.sh"]
